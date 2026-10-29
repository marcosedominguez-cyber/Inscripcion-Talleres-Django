"""Integración real del CU #4 en MongoDB local con transacciones, nunca Atlas."""

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import timedelta
from threading import Barrier, local
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.utils import timezone
from django.test import RequestFactory
from types import SimpleNamespace

from talleres import servicios
from talleres.api_participantes import inscripcion_participante_api
from talleres.consultas import consultar_espera, listar_talleres_proximos
from talleres.models import Cancelacion, Inscripcion, Taller, Usuario


LOCAL_SEGURO = (
    connection.vendor == "mongodb"
    and connection.settings_dict.get("HOST") == "mongodb://127.0.0.1:27017"
    and connection.settings_dict.get("NAME") == "k1_migration_isolated"
)
pytestmark = [
    pytest.mark.skipif(not LOCAL_SEGURO, reason="Solo con --ds=config.settings_test_mongodb_local y MongoDB local con replica set."),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def datos():
    assert LOCAL_SEGURO
    inicio = (timezone.now() + timedelta(days=10)).replace(microsecond=0)
    participantes = []

    def persona():
        ci = str(80000000 + len(participantes))
        participante = servicios.registrar_participante(f"Prueba {ci}", ci)
        participantes.append(participante)
        return participante

    def taller(nombre, fecha=inicio, cupos=5):
        resultado = servicios.registrar_taller(nombre, cupos, fecha, fecha + timedelta(days=2))
        Taller.objects.filter(pk=resultado.pk).update(estado_aprobacion=Taller.Aprobacion.APROBADO)
        resultado.refresh_from_db()
        return resultado

    return inicio, persona, taller


def test_rechazo_por_superposicion_no_escribe_y_cancelada_no_bloquea(datos):
    inicio, persona, taller = datos
    p = persona()
    primero, segundo = taller("Primero"), taller("Cruce", inicio + timedelta(days=1))
    original = servicios.inscribir_participante(p.ci, primero.codigo)
    antes = list(Inscripcion.objects.values())
    with pytest.raises(servicios.SuperposicionHorariaError, match=primero.codigo):
        servicios.inscribir_participante(p.ci, segundo.codigo)
    assert list(Inscripcion.objects.values()) == antes
    assert servicios.cupos_disponibles(segundo) == segundo.cupos
    request = RequestFactory().post(
        "/api/participantes/inscripciones/",
        data=json.dumps({"codigo_taller": segundo.codigo}), content_type="application/json",
    )
    request.user = SimpleNamespace(is_authenticated=True, is_active=True, perfil=p)
    respuesta = inscripcion_participante_api(request)
    assert respuesta.status_code == 409
    assert primero.codigo in json.loads(respuesta.content)["detail"]
    assert list(Inscripcion.objects.values()) == antes
    original.refresh_from_db()
    assert original.estado == Inscripcion.Estado.CONFIRMADA
    p.refresh_from_db()
    assert p.cancelaciones_consecutivas == 0
    servicios.cancelar_inscripcion(p.ci, primero.codigo)
    servicios.inscribir_participante(p.ci, segundo.codigo)
    assert Cancelacion.objects.filter(participante=p).count() == 1


def test_espera_rechaza_cruce_con_una_confirmacion(datos):
    inicio, persona, taller = datos
    p = persona()
    primero, lleno = taller("Primero"), taller("Lleno", inicio + timedelta(days=1))
    servicios.inscribir_participante(p.ci, primero.codigo)
    for _ in range(lleno.cupos):
        servicios.inscribir_participante(persona().ci, lleno.codigo)
    with pytest.raises(servicios.SuperposicionHorariaError):
        servicios.solicitar_espera(p.ci, lleno.codigo)
    assert consultar_espera(lleno) == []
    assert servicios.cupos_disponibles(lleno) == 0


def test_promocion_conserva_fifo_entre_habilitados_y_no_confirma_cruces(datos):
    inicio, persona, taller = datos
    destino = taller("Espera", cupos=10)
    titulares = [persona() for _ in range(destino.cupos)]
    for p in titulares:
        servicios.inscribir_participante(p.ci, destino.codigo)
    incompatible, habilitado = persona(), persona()
    servicios.solicitar_espera(incompatible.ci, destino.codigo)
    servicios.solicitar_espera(habilitado.ci, destino.codigo)
    otro = taller("Otro", inicio + timedelta(days=1))
    # Estar en espera no equivale a una confirmación en el primer taller.
    servicios.inscribir_participante(incompatible.ci, otro.codigo)
    resultado = servicios.cancelar_inscripcion(titulares[0].ci, destino.codigo)
    assert resultado.promovido
    assert Inscripcion.objects.get(participante=habilitado, taller=destino).estado == "confirmada"
    assert [i.participante_id for i in consultar_espera(destino)] == [incompatible.pk]
    assert servicios.cupos_disponibles(destino) == 0


@pytest.mark.parametrize("segundos, permitido", [(61, True), (60, True), (59, False), (0, False)])
def test_catalogo_y_servicio_respetan_limite_real_sin_consumir_plaza(datos, segundos, permitido):
    inicio, persona, taller = datos
    destino, p = taller("Plazo"), persona()
    with patch.object(servicios.timezone, "now", return_value=inicio - timedelta(seconds=segundos)):
        assert (destino.codigo in [t.codigo for t in listar_talleres_proximos()]) is permitido
        if permitido:
            servicios.inscribir_participante(p.ci, destino.codigo)
        else:
            with pytest.raises(servicios.PlazoInscripcionVencidoError):
                servicios.inscribir_participante(p.ci, destino.codigo)
    assert Inscripcion.objects.filter(taller=destino).count() == int(permitido)


def test_cancelacion_en_ultimo_minuto_no_promueve_fuera_de_plazo(datos):
    inicio, persona, taller = datos
    destino = taller("Plazo espera")
    titulares = [persona() for _ in range(destino.cupos)]
    for p in titulares:
        servicios.inscribir_participante(p.ci, destino.codigo)
    pendiente = persona()
    servicios.solicitar_espera(pendiente.ci, destino.codigo)
    with patch.object(servicios.timezone, "now", return_value=inicio - timedelta(seconds=30)):
        resultado = servicios.cancelar_inscripcion(titulares[0].ci, destino.codigo)
    assert not resultado.promovido and "Fuera de plazo" in resultado.motivo_sin_promocion
    assert servicios.cupos_disponibles(destino) == 1
    assert [i.participante_id for i in consultar_espera(destino)] == [pendiente.pk]


def sincronizar_escrituras(participante_id):
    barrera, hilo = Barrier(2), local()
    original = servicios._serializar_inscripciones

    def serializar(participante):
        if participante.pk == participante_id and not getattr(hilo, "sincronizado", False):
            hilo.sincronizado = True
            barrera.wait(timeout=10)
        return original(participante)

    return serializar


def test_solicitudes_simultaneas_en_talleres_cruzados_solo_confirman_una(datos):
    inicio, persona, taller = datos
    p = persona()
    destinos = [taller("Concurrente A"), taller("Concurrente B", inicio + timedelta(days=1))]

    def inscribir(destino):
        try:
            servicios.inscribir_participante(p.ci, destino.codigo)
            return "confirmada"
        except servicios.SuperposicionHorariaError:
            return "rechazada"
        finally:
            connections.close_all()

    with patch.object(servicios, "_serializar_inscripciones", side_effect=sincronizar_escrituras(p.pk)), \
         ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(inscribir, destinos))
    assert sorted(resultados) == ["confirmada", "rechazada"]
    assert Inscripcion.objects.filter(participante=p).count() == 1
    p.refresh_from_db()
    assert p.cancelaciones_consecutivas == 0


def test_promocion_simultanea_con_otra_inscripcion_no_crea_dos_confirmaciones(datos):
    inicio, persona, taller = datos
    destino, otro = taller("Promoción"), taller("Inscripción", inicio + timedelta(days=1))
    titulares = [persona() for _ in range(destino.cupos)]
    for titular in titulares:
        servicios.inscribir_participante(titular.ci, destino.codigo)
    p = persona()
    servicios.solicitar_espera(p.ci, destino.codigo)

    def operar(cancelar):
        try:
            if cancelar:
                servicios.cancelar_inscripcion(titulares[0].ci, destino.codigo)
            else:
                servicios.inscribir_participante(p.ci, otro.codigo)
        except servicios.SuperposicionHorariaError:
            assert not cancelar
        finally:
            connections.close_all()

    with patch.object(servicios, "_serializar_inscripciones", side_effect=sincronizar_escrituras(p.pk)), \
         ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(operar, [True, False]))
    assert Inscripcion.objects.filter(participante=p, estado="confirmada").count() == 1
    assert Cancelacion.objects.filter(participante=titulares[0]).count() == 1
    p.refresh_from_db()
    assert p.cancelaciones_consecutivas == 0
