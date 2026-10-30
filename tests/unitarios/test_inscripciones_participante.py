"""Pruebas aisladas para la inscripción desde el catálogo de participantes."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.db import IntegrityError
import pytest

from django.test import RequestFactory, SimpleTestCase

from talleres.servicios import InscripcionDuplicadaError
from talleres import servicios
from talleres.api_participantes import inscripcion_participante_api
from talleres.models import Inscripcion, Taller, Usuario


class ServicioInscripcionTests(SimpleTestCase):
    """El manager y la transacción se simulan; no se usa Atlas ni SQLite."""

    ahora = datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc)


    def ejecutar(self, *, estado=Taller.Aprobacion.APROBADO, inicio=None,
                 duplicada=False, disponibles=1, ahora=None, create_error=None):
        participante = SimpleNamespace(pk="participante-id")
        taller = SimpleNamespace(
            pk="taller-id", fecha_inicio=inicio or self.ahora + timedelta(minutes=5),
            estado_aprobacion=estado,
        )
        inscripcion = SimpleNamespace(pk="inscripcion-id", estado=Inscripcion.Estado.CONFIRMADA)
        manager_inscripciones = Mock()
        manager_inscripciones.filter.return_value.exists.return_value = duplicada
        manager_inscripciones.create.return_value = inscripcion
        manager_inscripciones.create.side_effect = create_error
        manager_talleres = Mock()
        manager_talleres.get.return_value = taller
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Usuario, "objects") as usuarios,
            patch.object(servicios.Taller, "objects", manager_talleres),
            patch.object(servicios.Inscripcion, "objects", manager_inscripciones),
            patch.object(servicios, "cupos_disponibles", return_value=disponibles),
            patch.object(servicios, "buscar_superposicion", return_value=None),
            patch.object(servicios.timezone, "now", return_value=ahora or self.ahora),
        ):
            usuarios.get.return_value = participante
            resultado = servicios.inscribir_participante("12345678", "T-001")
        return resultado, participante, taller, manager_talleres, manager_inscripciones, usuarios


    def test_convierte_carrera_de_inscripcion_duplicada_en_error_de_negocio(self):
        with self.assertRaises(InscripcionDuplicadaError):
            self.ejecutar(create_error=IntegrityError("duplicada"))


class ApiInscripcionParticipanteTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def solicitar(self, user=None, datos=None):
        request = self.factory.post(
            "/api/participantes/inscripciones/",
            data=json.dumps(datos) if datos is not None else "{}",
            content_type="application/json",
        )
        request.user = user if user is not None else AnonymousUser()
        return request


    def test_usa_identidad_de_perfil_y_no_acepta_identificador_cliente(self):
        participante = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
        )
        creado = SimpleNamespace(pk="inscripcion-id", estado=Inscripcion.Estado.CONFIRMADA)
        with patch("talleres.api_participantes.inscribir_participante", return_value=creado) as servicio:
            response = inscripcion_participante_api(
                self.solicitar(participante, {"codigo_taller": "T-1"})
            )
        self.assertEqual(response.status_code, 201)
        servicio.assert_called_once_with("12345678", "T-1")
        response = inscripcion_participante_api(
            self.solicitar(participante, {"codigo_taller": "T-1", "ci": "otra-persona"})
        )
        self.assertEqual(response.status_code, 400)
        servicio.assert_called_once()

    def test_post_de_inscripcion_exige_csrf(self):
        request = self.factory.post(
            "/api/participantes/inscripciones/",
            data=json.dumps({"codigo_taller": "T-1"}),
            content_type="application/json",
        )
        request.user = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
        )
        middleware = CsrfViewMiddleware(lambda req: None)
        middleware.process_request(request)
        response = middleware.process_view(request, inscripcion_participante_api, (), {})
        self.assertEqual(response.status_code, 403)


class EscenarioEspera:
    def ejecutar(self, *, cupos=10, ocupadas=0, disponibles=0, duplicada=False):
        taller = SimpleNamespace(pk="t", cupos=cupos,
            estado_aprobacion=Taller.Aprobacion.APROBADO,
            fecha_inicio=ServicioInscripcionTests.ahora + timedelta(days=1))
        self.escrituras = Mock()
        self.inscripciones = Mock()
        self.inscripciones.filter.return_value.exists.return_value = duplicada
        self.inscripciones.create.return_value = SimpleNamespace(pk="nueva")
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects") as usuarios, \
             patch.object(servicios.Taller, "objects", self.escrituras), \
             patch.object(servicios.Inscripcion, "objects", self.inscripciones), \
             patch.object(servicios, "cupos_disponibles", return_value=disponibles), \
             patch.object(servicios, "buscar_superposicion", return_value=None), \
             patch.object(servicios, "consultar_espera", side_effect=[[None] * ocupadas, [SimpleNamespace(pk="nueva")]]), \
             patch.object(servicios.timezone, "now", return_value=ServicioInscripcionTests.ahora):
            usuarios.get.return_value = SimpleNamespace(pk="p")
            self.escrituras.get.return_value = taller
            return servicios.solicitar_espera("123", "T-001")


@pytest.mark.parametrize("opciones, error", [
    ({"ocupadas": 2}, servicios.ListaEsperaLlenaError),
    ({"cupos": 4}, servicios.ListaEsperaLlenaError),
    ({"disponibles": 1}, servicios.TallerConCuposError),
    ({"duplicada": True}, InscripcionDuplicadaError),
], ids=["espera-llena", "veinte-por-ciento", "hay-cupos", "duplicada"])
def test_rechazo_de_espera_no_escribe_ni_reordena(opciones, error):
    escenario = EscenarioEspera()
    with pytest.raises(error):
        escenario.ejecutar(**opciones)
    escenario.inscripciones.create.assert_not_called()
    escenario.escrituras.filter.assert_not_called()
