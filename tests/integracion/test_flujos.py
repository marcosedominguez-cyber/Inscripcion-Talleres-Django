"""Doce casos de servicios y API con persistencia y transacciones reales."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from bson import ObjectId
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import Client

from talleres import servicios
from talleres.consultas import consultar_espera, cupos_disponibles, listar_talleres_proximos
from talleres.models import Bloqueo, Cancelacion, Inscripcion, Notificacion, Taller, Usuario

pytestmark = pytest.mark.django_db(transaction=True)


def test_registro_login_por_ci_y_privilegios(fabrica):
    cliente = Client(enforce_csrf_checks=True)
    token = cliente.get("/api/cuentas/sesion/").json()["csrfToken"]
    datos = dict(nombre_usuario="Ana", ci="12345678", rol="participante",
                 contrasena=fabrica.clave, confirmar_contrasena=fabrica.clave)
    assert cliente.post("/api/cuentas/registro/", datos, content_type="application/json").status_code == 403
    cliente.defaults["HTTP_X_CSRFTOKEN"] = token
    assert cliente.post("/api/cuentas/registro/", {**datos, "is_staff": "true"}, content_type="application/json").status_code == 400
    assert not Usuario.objects.filter(ci=datos["ci"]).exists()
    assert cliente.post("/api/cuentas/registro/", datos, content_type="application/json").status_code == 201
    perfil = Usuario.objects.get(ci=datos["ci"])
    assert not perfil.cuenta.is_staff and not perfil.cuenta.is_superuser
    assert perfil.cuenta.check_password(fabrica.clave)
    cliente = fabrica.cliente(perfil)
    assert cliente.get("/api/cuentas/sesion/").json()["usuario"]["ci"] == datos["ci"]
    assert cliente.post("/api/cuentas/logout/").status_code == 200
    assert cliente.get("/api/cuentas/sesion/").json()["usuario"] is None
    instructor = fabrica.persona(cuenta=True, rol=Usuario.Rol.INSTRUCTOR)
    for persona in (perfil, instructor):
        cliente = Client(enforce_csrf_checks=True)
        cliente.defaults["HTTP_X_CSRFTOKEN"] = cliente.get("/api/cuentas/sesion/").json()["csrfToken"]
        datos_login = {"ci": persona.ci, "contrasena": fabrica.clave}
        assert cliente.post("/api/cuentas/login/", datos_login, content_type="application/json").status_code == 400
        otro_rol = "instructor" if persona.rol == "participante" else "participante"
        respuesta = cliente.post("/api/cuentas/login/", {**datos_login, "rol": otro_rol}, content_type="application/json")
        assert respuesta.status_code == 403
        assert cliente.get("/api/cuentas/sesion/").json()["usuario"] is None
        assert fabrica.cliente(persona).get("/api/cuentas/sesion/").json()["usuario"]["rol"] == persona.rol


def test_ultimo_cupo_duplicados_y_limite_de_espera(fabrica):
    taller = fabrica.taller(cupos=10)
    titulares = [fabrica.persona() for _ in range(10)]
    for persona in titulares:
        servicios.inscribir_participante(persona.ci, taller.codigo)
    with pytest.raises(servicios.InscripcionDuplicadaError):
        servicios.inscribir_participante(titulares[0].ci, taller.codigo)
    with pytest.raises(servicios.CupoAgotadoError):
        servicios.inscribir_participante(fabrica.persona().ci, taller.codigo)
    primero, segundo, tercero = [fabrica.persona() for _ in range(3)]
    assert servicios.solicitar_espera(primero.ci, taller.codigo).posicion_espera == 1
    assert servicios.solicitar_espera(segundo.ci, taller.codigo).posicion_espera == 2
    with pytest.raises(servicios.ListaEsperaLlenaError):
        servicios.solicitar_espera(tercero.ci, taller.codigo)
    assert [s.participante_id for s in consultar_espera(taller)] == [primero.pk, segundo.pk]
    assert cupos_disponibles(taller) == 0
    assert Inscripcion.objects.filter(taller=taller, estado="confirmada").count() == 10


@pytest.mark.parametrize("segundos, permitido", [(61, True), (60, True), (59, False)])
def test_catalogo_y_servicio_comparten_el_limite(fabrica, segundos, permitido):
    taller, persona = fabrica.taller(), fabrica.persona()
    lleno = fabrica.taller("Espera y promoción")
    titulares = [fabrica.persona() for _ in range(5)]
    for titular in titulares:
        servicios.inscribir_participante(titular.ci, lleno.codigo)
    pendiente = fabrica.persona()
    servicios.solicitar_espera(pendiente.ci, lleno.codigo)
    with patch.object(servicios.timezone, "now", return_value=taller.fecha_inicio - timedelta(seconds=segundos)):
        assert (taller.codigo in [t.codigo for t in listar_talleres_proximos()]) is permitido
        if permitido:
            servicios.inscribir_participante(persona.ci, taller.codigo)
        else:
            with pytest.raises(servicios.PlazoInscripcionVencidoError, match="un minuto"):
                servicios.inscribir_participante(persona.ci, taller.codigo)
            with pytest.raises(servicios.PlazoInscripcionVencidoError):
                servicios.solicitar_espera(fabrica.persona().ci, lleno.codigo)
        cancelacion = servicios.cancelar_inscripcion(titulares[0].ci, lleno.codigo)
        assert cancelacion.promovido is permitido
        if not permitido:
            assert "Fuera de plazo" in cancelacion.motivo_sin_promocion
    assert Inscripcion.objects.filter(taller=taller).count() == int(permitido)
    assert Inscripcion.objects.get(participante=pendiente, taller=lleno).estado == ("confirmada" if permitido else "en_espera")
    assert Notificacion.objects.filter(participante=pendiente, tipo="promocion").count() == int(permitido)
    persona.refresh_from_db()
    assert persona.cancelaciones_consecutivas == 0


def test_superposicion_rechaza_sin_escribir_y_cancelacion_libera(fabrica):
    persona = fabrica.persona(cuenta=True)
    primero = fabrica.taller("Primero")
    otro = fabrica.taller("Cruce", fecha=fabrica.inicio + timedelta(days=1))
    servicios.inscribir_participante(persona.ci, primero.codigo)
    antes = list(Inscripcion.objects.values())
    cliente = fabrica.cliente(persona)
    respuesta = cliente.post("/api/participantes/inscripciones/", {"codigo_taller": otro.codigo}, content_type="application/json")
    assert respuesta.status_code == 409 and primero.codigo in respuesta.json()["detail"]
    assert list(Inscripcion.objects.values()) == antes and cupos_disponibles(otro) == otro.cupos
    servicios.cancelar_inscripcion(persona.ci, primero.codigo)
    servicios.inscribir_participante(persona.ci, otro.codigo)
    assert Cancelacion.objects.filter(participante=persona).count() == 1
    assert Inscripcion.objects.get(participante=persona).taller_id == otro.pk


def test_promocion_salta_bloqueados_y_cruces_y_conserva_fifo_con_aviso(fabrica):
    taller = fabrica.taller(cupos=15)
    titulares = [fabrica.persona() for _ in range(15)]
    for persona in titulares:
        servicios.inscribir_participante(persona.ci, taller.codigo)
    bloqueado, incompatible, siguiente = fabrica.persona(), fabrica.persona(), fabrica.persona()
    servicios.solicitar_espera(bloqueado.ci, taller.codigo)
    servicios.solicitar_espera(incompatible.ci, taller.codigo)
    servicios.solicitar_espera(siguiente.ci, taller.codigo)
    otro = fabrica.taller("Horario incompatible", fecha=fabrica.inicio + timedelta(days=1))
    servicios.inscribir_participante(incompatible.ci, otro.codigo)
    adicional = fabrica.taller("Otra inscripción del bloqueado", fecha=fabrica.inicio + timedelta(days=3), cupos=10)
    for persona in [bloqueado] + [fabrica.persona() for _ in range(9)]:
        servicios.inscribir_participante(persona.ci, adicional.codigo)
    espera_adicional = [fabrica.persona(), fabrica.persona()]
    for persona in espera_adicional:
        servicios.solicitar_espera(persona.ci, adicional.codigo)
    administrador = fabrica.administrador()
    anteriores = list(Inscripcion.objects.order_by("id").values())
    with patch.object(servicios, "_notificar", side_effect=RuntimeError("Entrega interrumpida")):
        with pytest.raises(RuntimeError, match="Entrega interrumpida"):
            servicios.bloquear_participante(bloqueado, Bloqueo.Motivo.MANUAL, administrador)
    bloqueado.refresh_from_db()
    assert not bloqueado.bloqueado
    assert list(Inscripcion.objects.order_by("id").values()) == anteriores
    assert not Cancelacion.objects.filter(participante=bloqueado).exists()
    assert not Bloqueo.objects.filter(participante=bloqueado).exists()
    assert not Notificacion.objects.exists()
    servicios.bloquear_participante(bloqueado, Bloqueo.Motivo.MANUAL, administrador)
    bloqueado.refresh_from_db()
    assert bloqueado.bloqueado and bloqueado.cancelaciones_consecutivas == 0
    assert not Inscripcion.objects.filter(participante=bloqueado).exists()
    assert Cancelacion.objects.filter(participante=bloqueado).count() == 2
    assert {c.estado_anterior for c in Cancelacion.objects.filter(participante=bloqueado)} == {"confirmada", "en_espera"}
    assert Inscripcion.objects.get(participante=espera_adicional[0], taller=adicional).estado == "confirmada"
    assert [s.participante_id for s in consultar_espera(adicional)] == [espera_adicional[1].pk]
    assert cupos_disponibles(adicional) == 0
    with pytest.raises(servicios.ParticipanteYaBloqueadoError):
        servicios.bloquear_participante(bloqueado, Bloqueo.Motivo.MANUAL, administrador)
    assert Cancelacion.objects.filter(participante=bloqueado).count() == 2
    assert Notificacion.objects.filter(participante=bloqueado, tipo="bloqueo").count() == 1
    assert servicios.cancelar_inscripcion(titulares[0].ci, taller.codigo).promovido
    assert [s.participante_id for s in consultar_espera(taller)] == [incompatible.pk]
    assert Inscripcion.objects.get(participante=siguiente, taller=taller).estado == "confirmada"
    assert Notificacion.objects.filter(participante=siguiente, tipo="promocion").count() == 1
    assert not Notificacion.objects.filter(participante=bloqueado, tipo="promocion").exists()
    assert not Notificacion.objects.filter(participante=incompatible, tipo="promocion").exists()
    assert cupos_disponibles(taller) == 0


def test_tercera_cancelacion_bloquea_y_rehabilitacion_conserva_historial(fabrica):
    persona = fabrica.persona()
    futuro = fabrica.taller("Confirmada pendiente", fecha=fabrica.inicio + timedelta(days=12))
    servicios.inscribir_participante(persona.ci, futuro.codigo)
    lleno = fabrica.taller("Espera pendiente", fecha=fabrica.inicio + timedelta(days=15))
    for _ in range(5):
        servicios.inscribir_participante(fabrica.persona().ci, lleno.codigo)
    servicios.solicitar_espera(persona.ci, lleno.codigo)
    iniciado = fabrica.taller("Taller iniciado", fecha=fabrica.inicio + timedelta(days=18))
    servicios.inscribir_participante(persona.ci, iniciado.codigo)
    Taller.objects.filter(pk=iniciado.pk).update(
        fecha_inicio=fabrica.inicio - timedelta(days=12), fecha_fin=fabrica.inicio - timedelta(days=9))
    for n in range(3):
        taller = fabrica.taller(fecha=fabrica.inicio + timedelta(days=3 * n))
        servicios.inscribir_participante(persona.ci, taller.codigo)
        servicios.cancelar_inscripcion(persona.ci, taller.codigo)
    persona.refresh_from_db()
    assert persona.bloqueado and persona.cancelaciones_consecutivas == 3
    assert Cancelacion.objects.filter(participante=persona).count() == 6
    assert not Inscripcion.objects.filter(participante=persona).exists()
    assert Notificacion.objects.filter(participante=persona, tipo="bloqueo").count() == 1
    destino = fabrica.taller()
    with pytest.raises(servicios.CuentaBloqueadaError):
        servicios.inscribir_participante(persona.ci, destino.codigo)
    servicios.rehabilitar_participante(persona, fabrica.administrador())
    persona.refresh_from_db()
    assert not persona.bloqueado and persona.cancelaciones_consecutivas == 0
    assert Bloqueo.objects.get(participante=persona).fecha_desbloqueo is not None
    assert Cancelacion.objects.filter(participante=persona).count() == 6
    assert not Inscripcion.objects.filter(participante=persona).exists()
    servicios.inscribir_participante(persona.ci, destino.codigo)


def test_edicion_revierte_cupo_invalido_y_notifica_cambios_reales(fabrica):
    instructor = fabrica.persona(cuenta=True, rol=Usuario.Rol.INSTRUCTOR)
    taller = fabrica.taller(cupos=5, instructor=instructor)
    for _ in range(5):
        servicios.inscribir_participante(fabrica.persona().ci, taller.codigo)
    with pytest.raises(ValidationError):
        servicios.actualizar_taller(taller, {"cupos": 4})
    taller.refresh_from_db()
    assert taller.cupos == 5 and taller.estado_aprobacion == "aprobado"
    assert Notificacion.objects.count() == 0
    respuesta = fabrica.cliente(instructor).patch(f"/api/gestion/talleres/{taller.codigo}/", {"nombre": "Actualizado"}, content_type="application/json")
    assert respuesta.status_code == 200
    taller.refresh_from_db()
    assert taller.nombre == "Actualizado" and taller.estado_aprobacion == "pendiente"
    assert Notificacion.objects.filter(taller=taller, tipo="edicion_taller").count() == 5
    with pytest.raises(servicios.TallerNoAprobadoError):
        servicios.inscribir_participante(fabrica.persona().ci, taller.codigo)


def test_bandeja_real_pagina_solo_avisos_propios_y_lectura_idempotente(fabrica):
    persona, otra = fabrica.persona(cuenta=True), fabrica.persona(cuenta=True)
    for n in range(21):
        servicios._notificar(persona, "promocion", "Plaza", "Mensaje", f"evento:{n}")
    ajeno = servicios._notificar(otra, "bloqueo", "Bloqueo", "Mensaje", "evento:ajeno")
    cliente = fabrica.cliente(persona)
    pagina = cliente.get("/api/participantes/notificaciones/").json()
    assert len(pagina["notificaciones"]) == 20 and pagina["no_leidas"] == 21
    ultima = cliente.get("/api/participantes/notificaciones/", {"antes": pagina["siguiente"]}).json()
    assert len(ultima["notificaciones"]) == 1 and ultima["siguiente"] is None
    assert {n["id"] for n in pagina["notificaciones"]}.isdisjoint({n["id"] for n in ultima["notificaciones"]})
    assert cliente.post(f"/api/participantes/notificaciones/{ajeno.pk}/leer/").status_code == 404
    identificador = pagina["notificaciones"][0]["id"]
    for _ in range(2):
        assert cliente.post(f"/api/participantes/notificaciones/{identificador}/leer/").status_code == 200
    leido = Notificacion.objects.get(pk=ObjectId(identificador))
    servicios._notificar(persona, leido.tipo, leido.titulo, leido.mensaje, leido.clave_evento)
    assert Notificacion.objects.filter(participante=persona).count() == 21
    assert cliente.get("/api/participantes/notificaciones/").json()["no_leidas"] == 20
    ajeno.refresh_from_db()
    assert not ajeno.leida


def ejecutar_en_paralelo(operaciones):
    barrera = Barrier(len(operaciones))

    def ejecutar(operacion):
        try:
            barrera.wait(timeout=10)
            operacion()
            return "confirmada"
        except (servicios.CupoAgotadoError, servicios.SuperposicionHorariaError):
            return "rechazada"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(operaciones)) as pool:
        return sorted(pool.map(ejecutar, operaciones))


def test_dos_solicitudes_simultaneas_no_sobrevenden_ultimo_cupo(fabrica):
    taller = fabrica.taller(cupos=4)
    for _ in range(3):
        servicios.inscribir_participante(fabrica.persona().ci, taller.codigo)
    personas = [fabrica.persona(), fabrica.persona()]
    resultado = ejecutar_en_paralelo([
        lambda p=p: servicios.inscribir_participante(p.ci, taller.codigo) for p in personas
    ])
    assert resultado == ["confirmada", "rechazada"]
    assert Inscripcion.objects.filter(taller=taller).count() == 4 and cupos_disponibles(taller) == 0


def test_solicitudes_simultaneas_no_confirman_horarios_cruzados(fabrica):
    persona = fabrica.persona()
    talleres = [fabrica.taller("A"), fabrica.taller("B", fecha=fabrica.inicio + timedelta(days=1))]
    resultado = ejecutar_en_paralelo([
        lambda t=t: servicios.inscribir_participante(persona.ci, t.codigo) for t in talleres
    ])
    assert resultado == ["confirmada", "rechazada"]
    assert Inscripcion.objects.filter(participante=persona, estado="confirmada").count() == 1
    persona.refresh_from_db()
    assert persona.cancelaciones_consecutivas == 0
