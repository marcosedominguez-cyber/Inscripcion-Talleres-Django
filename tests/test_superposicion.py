"""Reglas compartidas, rechazos sin cambios y mensajes del caso de uso #4."""

import json
from contextlib import nullcontext, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError
from django.test import RequestFactory

from talleres import servicios
from talleres.api_participantes import espera_participante_api, inscripcion_participante_api
from talleres.consultas import buscar_superposicion
from talleres.models import Inscripcion, Taller, Usuario
from talleres.reglas import horarios_superpuestos


INICIO = datetime(2030, 10, 15, 10, tzinfo=ZoneInfo("America/La_Paz"))


@pytest.mark.parametrize("inicio_horas, fin_horas, esperado", [
    (-2, 0, False), (2, 4, False), (3, 5, False),
    (-1, 1, True), (1, 3, True), (0, 2, True),
    (-1, 3, True), (0.5, 1.5, True),
])
def test_solapamiento_real_y_extremos_adyacentes(inicio_horas, fin_horas, esperado):
    otro_inicio = INICIO + timedelta(hours=inicio_horas)
    otro_fin = INICIO + timedelta(hours=fin_horas)
    assert horarios_superpuestos(INICIO, INICIO + timedelta(hours=2), otro_inicio, otro_fin) is esperado
    assert horarios_superpuestos(otro_inicio, otro_fin, INICIO, INICIO + timedelta(hours=2)) is esperado


def test_superposicion_compara_fechas_completas_y_zonas_horarias():
    medianoche = INICIO.replace(hour=23)
    siguiente = medianoche + timedelta(hours=2)
    assert horarios_superpuestos(
        medianoche, siguiente,
        (medianoche + timedelta(hours=1)).astimezone(ZoneInfo("UTC")),
        (siguiente + timedelta(hours=1)).astimezone(ZoneInfo("UTC")),
    )
    assert not horarios_superpuestos(
        INICIO, INICIO + timedelta(hours=2),
        INICIO + timedelta(days=1), INICIO + timedelta(days=1, hours=2),
    )


def test_consulta_solo_confirmadas_de_la_persona_y_excluye_el_mismo_taller():
    participante = SimpleNamespace(pk="p")
    taller = SimpleNamespace(pk="destino", fecha_inicio=INICIO, fecha_fin=INICIO + timedelta(hours=2))
    otro = SimpleNamespace(fecha_inicio=INICIO + timedelta(hours=1), fecha_fin=INICIO + timedelta(hours=3))
    with patch.object(Inscripcion, "objects") as manager:
        manager.filter.return_value.exclude.return_value.select_related.return_value = [
            SimpleNamespace(taller=otro),
        ]
        assert buscar_superposicion(participante, taller) is otro
    manager.filter.assert_called_once_with(participante=participante, estado=Inscripcion.Estado.CONFIRMADA)
    manager.filter.return_value.exclude.assert_called_once_with(taller_id="destino")


@pytest.fixture(params=[False, True], ids=["inscripcion", "espera"])
def escenario(request):
    espera = request.param
    participante = SimpleNamespace(pk="p", cancelaciones_consecutivas=0)
    taller = SimpleNamespace(
        pk="t", codigo="T-002", nombre="Destino", cupos=5,
        fecha_inicio=INICIO + timedelta(hours=1), fecha_fin=INICIO + timedelta(hours=3),
        estado_aprobacion=Taller.Aprobacion.APROBADO,
    )
    previo = SimpleNamespace(
        pk="anterior", codigo="T-001", nombre="Python",
        fecha_inicio=INICIO, fecha_fin=INICIO + timedelta(hours=2),
    )
    creada = SimpleNamespace(pk="nueva", estado="en_espera" if espera else "confirmada")
    inscripciones = Mock()
    inscripciones.filter.return_value.exists.return_value = False
    inscripciones.filter.return_value.exclude.return_value.select_related.return_value = [
        SimpleNamespace(taller=previo),
    ]
    inscripciones.create.return_value = creada
    with (
        patch.object(servicios, "atomic", return_value=nullcontext()),
        patch.object(Usuario, "objects") as usuarios,
        patch.object(Taller, "objects") as talleres,
        patch.object(Inscripcion, "objects", inscripciones),
        patch.object(servicios, "cupos_disponibles", return_value=0 if espera else 1),
        patch.object(servicios, "consultar_espera", side_effect=[[], [creada]]),
        patch.object(servicios.timezone, "now", return_value=INICIO - timedelta(days=1)),
    ):
        usuarios.get.return_value = participante
        talleres.get.return_value = taller
        yield SimpleNamespace(
            espera=espera, taller=taller, previo=previo, participante=participante,
            usuarios=usuarios, talleres=talleres, inscripciones=inscripciones,
            servicio=servicios.solicitar_espera if espera else servicios.inscribir_participante,
            api=espera_participante_api if espera else inscripcion_participante_api,
        )


def test_rechazo_conserva_inscripcion_anterior_y_no_consume_plaza(escenario):
    with pytest.raises(servicios.SuperposicionHorariaError) as error:
        escenario.servicio("12345678", "T-002")
    mensaje = str(error.value)
    assert "Superposición de horarios" in mensaje
    assert "T-001" in mensaje and "Python" in mensaje
    assert "15/10/2030 10:00" in mensaje and "12:00" in mensaje
    escenario.inscripciones.create.assert_not_called()
    escenario.talleres.filter.assert_not_called()
    escenario.usuarios.filter.assert_not_called()
    assert escenario.previo.fecha_inicio == INICIO


@pytest.mark.parametrize("desplazamiento", [timedelta(hours=2), timedelta(days=1)])
def test_acepta_horario_adyacente_o_de_otro_dia(escenario, desplazamiento):
    escenario.taller.fecha_inicio = INICIO + desplazamiento
    escenario.taller.fecha_fin = INICIO + desplazamiento + timedelta(hours=2)
    resultado = escenario.servicio("12345678", "T-002")
    assert resultado.estado == ("en_espera" if escenario.espera else "confirmada")
    escenario.inscripciones.create.assert_called_once()
    # Las dos escrituras de serialización conservan el contador original.
    assert escenario.usuarios.filter.return_value.update.call_count == 2


def test_api_devuelve_motivo_de_superposicion_con_409(escenario):
    request = RequestFactory().post(
        "/api/participantes/espera/" if escenario.espera else "/api/participantes/inscripciones/",
        data=json.dumps({"codigo_taller": "T-002"}), content_type="application/json",
    )
    request.user = SimpleNamespace(
        is_authenticated=True, is_active=True,
        perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
    )
    respuesta = escenario.api(request)
    assert respuesta.status_code == 409
    assert "Superposición de horarios" in json.loads(respuesta.content)["detail"]
    escenario.inscripciones.create.assert_not_called()


def test_reintento_transitorio_vuelve_a_comprobar_la_superposicion(escenario):
    transitorio = Mock()
    transitorio.has_error_label.return_value = True
    # La causa real de DatabaseError es una excepción con esa etiqueta MongoDB.
    causa = RuntimeError("conflicto de escritura")
    causa.has_error_label = transitorio.has_error_label
    error = DatabaseError("reintentar")
    error.__cause__ = causa
    with patch.object(servicios, "buscar_superposicion", side_effect=[None, escenario.previo]), \
         patch.object(servicios, "_serializar_inscripciones", side_effect=error), \
         patch.object(servicios.time, "sleep"):
        with pytest.raises(servicios.SuperposicionHorariaError):
            escenario.servicio("12345678", "T-002")
    assert escenario.usuarios.get.call_count == 2
    escenario.inscripciones.create.assert_not_called()


@pytest.mark.parametrize("error", [
    servicios.PlazoInscripcionVencidoError("Fuera de plazo: límite vencido."),
    servicios.SuperposicionHorariaError("Superposición de horarios: T-001."),
])
def test_cli_muestra_el_motivo_de_rechazo_sin_traceback(error):
    from proyecto import main

    salida = StringIO()
    with patch("builtins.input", side_effect=["4", "12345678", "T-002", "9"]), \
         patch.object(main.servicios, "inscribir_participante", side_effect=error), \
         redirect_stdout(salida):
        main.ejecutar()
    assert str(error) in salida.getvalue()
    assert "Traceback" not in salida.getvalue()


def test_admin_no_permite_saltar_las_reglas_con_altas_ediciones_o_borrados_directos():
    from talleres.admin import InscripcionAdmin
    from talleres.admin_site import admin_site

    administrador = InscripcionAdmin(Inscripcion, admin_site)
    assert not administrador.has_add_permission(None)
    assert not administrador.has_change_permission(None)
    assert not administrador.has_delete_permission(None)
