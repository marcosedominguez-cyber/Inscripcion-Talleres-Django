"""Plazo común de inscripción y espera; ORM y transacciones simulados."""

import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from django.test import RequestFactory

from talleres import servicios
from talleres.api_participantes import espera_participante_api, inscripcion_participante_api
from talleres.models import Inscripcion, Taller, Usuario


INICIO = datetime(2030, 10, 15, 12, 0, tzinfo=ZoneInfo("America/La_Paz"))


@pytest.fixture(params=[False, True], ids=["confirmada", "en_espera"])
def solicitud(request):
    espera = request.param
    participante = SimpleNamespace(pk="participante-id")
    taller = SimpleNamespace(
        pk="taller-id", cupos=5, fecha_inicio=INICIO,
        fecha_fin=INICIO + timedelta(days=7),
        estado_aprobacion=Taller.Aprobacion.APROBADO,
    )
    creada = SimpleNamespace(
        pk="inscripcion-id",
        estado=Inscripcion.Estado.EN_ESPERA if espera else Inscripcion.Estado.CONFIRMADA,
    )
    talleres = Mock()
    talleres.get.return_value = taller
    inscripciones = Mock()
    inscripciones.filter.return_value.exists.return_value = False
    inscripciones.create.return_value = creada
    with (
        patch.object(servicios, "atomic", return_value=nullcontext()),
        patch.object(servicios.Usuario, "objects") as usuarios,
        patch.object(servicios.Taller, "objects", talleres),
        patch.object(servicios.Inscripcion, "objects", inscripciones),
        patch.object(servicios, "cupos_disponibles", return_value=0 if espera else 1) as cupos,
        patch.object(servicios, "buscar_superposicion", return_value=None),
        patch.object(servicios, "consultar_espera", side_effect=[[], [creada]]) as cola,
        patch.object(servicios.timezone, "now") as reloj,
    ):
        usuarios.get.return_value = participante
        yield SimpleNamespace(
            espera=espera, participante=participante, taller=taller, creada=creada,
            talleres=talleres, inscripciones=inscripciones, cupos=cupos, cola=cola,
            reloj=reloj,
            servicio=servicios.solicitar_espera if espera else servicios.inscribir_participante,
            api=espera_participante_api if espera else inscripcion_participante_api,
        )


@pytest.mark.parametrize("segundos_antes, permitido", [
    (61, True), (60, True), (59, False), (0, False), (-1, False),
])
def test_servicios_comparten_plazo_y_el_rechazo_no_escribe(solicitud, segundos_antes, permitido):
    solicitud.reloj.return_value = INICIO - timedelta(seconds=segundos_antes)
    if permitido:
        resultado = solicitud.servicio("12345678", "T-001")
        assert resultado is solicitud.creada
        datos = {"participante": solicitud.participante, "taller": solicitud.taller}
        if solicitud.espera:
            datos["estado"] = Inscripcion.Estado.EN_ESPERA
            assert resultado.posicion_espera == 1
        solicitud.inscripciones.create.assert_called_once_with(**datos)
    else:
        with pytest.raises(servicios.PlazoInscripcionVencidoError):
            solicitud.servicio("12345678", "T-001")
        solicitud.inscripciones.create.assert_not_called()
        solicitud.talleres.filter.assert_not_called()
        solicitud.cupos.assert_not_called()
        solicitud.cola.assert_not_called()


@pytest.mark.parametrize("segundos_antes, estado_http", [(60, 201), (59, 409), (0, 409)])
def test_api_aplica_el_plazo_del_servicio_sin_confiar_en_el_reloj_del_cliente(
    solicitud, segundos_antes, estado_http,
):
    solicitud.reloj.return_value = INICIO - timedelta(seconds=segundos_antes)
    request = RequestFactory().post(
        "/api/participantes/espera/" if solicitud.espera else "/api/participantes/inscripciones/",
        data=json.dumps({"codigo_taller": "T-001"}),
        content_type="application/json",
    )
    request.user = SimpleNamespace(
        is_authenticated=True, is_active=True,
        perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
    )

    respuesta = solicitud.api(request)

    assert respuesta.status_code == estado_http
    datos = json.loads(respuesta.content)
    if estado_http == 201:
        assert datos["inscripcion"]["estado"] == solicitud.creada.estado
    else:
        assert datos["detail"].startswith("Fuera de plazo:")
        assert "15/10/2030 a las 11:59:00" in datos["detail"]
        assert "America/La_Paz" in datos["detail"]
        solicitud.inscripciones.create.assert_not_called()
        solicitud.talleres.filter.assert_not_called()
