"""Pruebas aisladas para la inscripción desde el catálogo de participantes."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from proyecto.reglas_inscripciones import (
    CupoAgotadoError,
    InscripcionDuplicadaError,
    PlazoInscripcionVencidoError,
    TallerNoAprobadoError,
)
from talleres import services
from talleres.api_participantes import inscripcion_participante_api
from talleres.models import Inscripcion, Taller, Usuario


class ServicioInscripcionTests(SimpleTestCase):
    """El manager y la transacción se simulan; no se usa Atlas ni SQLite."""

    ahora = datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc)

    def ejecutar(self, *, estado=Taller.Aprobacion.APROBADO, inicio=None,
                 duplicada=False, disponibles=1, ahora=None):
        participante = SimpleNamespace(pk="participante-id")
        taller = SimpleNamespace(
            pk="taller-id", fecha_inicio=inicio or self.ahora + timedelta(minutes=5),
            estado_aprobacion=estado,
        )
        inscripcion = SimpleNamespace(pk="inscripcion-id", estado=Inscripcion.Estado.CONFIRMADA)
        manager_inscripciones = Mock()
        manager_inscripciones.filter.return_value.exists.return_value = duplicada
        manager_inscripciones.create.return_value = inscripcion
        manager_talleres = Mock()
        manager_talleres.get.return_value = taller
        with patch.object(services, "atomic", return_value=nullcontext()),              patch.object(services.Usuario, "objects") as usuarios,              patch.object(services.Taller, "objects", manager_talleres),              patch.object(services.Inscripcion, "objects", manager_inscripciones),              patch.object(services, "cupos_disponibles", return_value=disponibles),              patch.object(services.timezone, "now", return_value=ahora or self.ahora):
            usuarios.get.return_value = participante
            resultado = services.inscribir_participante("12345678", "T-001")
        return resultado, participante, taller, manager_talleres, manager_inscripciones, usuarios

    def test_inscripcion_exitosa_en_el_limite_de_un_minuto(self):
        limite = self.ahora + timedelta(minutes=5) - timedelta(minutes=1)
        resultado, participante, taller, _, inscripciones, usuarios = self.ejecutar(
            inicio=self.ahora + timedelta(minutes=5), ahora=limite,
        )
        self.assertEqual(resultado.pk, "inscripcion-id")
        usuarios.get.assert_called_once()
        inscripciones.create.assert_called_once_with(participante=participante, taller=taller)

    def test_rechaza_taller_no_aprobado(self):
        for estado in (Taller.Aprobacion.PENDIENTE, Taller.Aprobacion.RECHAZADO):
            with self.subTest(estado=estado), self.assertRaises(TallerNoAprobadoError):
                self.ejecutar(estado=estado)

    def test_rechaza_duplicada_y_sin_cupos(self):
        with self.assertRaises(InscripcionDuplicadaError):
            self.ejecutar(duplicada=True)
        with self.assertRaises(CupoAgotadoError):
            self.ejecutar(disponibles=0)

    def test_rechaza_menos_de_un_minuto_y_limite_vencido(self):
        inicio = self.ahora + timedelta(minutes=5)
        for ahora in (inicio - timedelta(seconds=59), inicio, inicio + timedelta(seconds=1)):
            with self.subTest(ahora=ahora), self.assertRaises(PlazoInscripcionVencidoError):
                self.ejecutar(inicio=inicio, ahora=ahora)


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

    def test_requiere_sesion_y_rol_participante(self):
        self.assertEqual(inscripcion_participante_api(self.solicitar()).status_code, 401)
        instructor = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR, ci="12345678"),
        )
        self.assertEqual(
            inscripcion_participante_api(self.solicitar(instructor, {"codigo_taller": "T-1"})).status_code,
            403,
        )

    def test_usa_identidad_de_perfil_y_no_acepta_identificador_cliente(self):
        participante = SimpleNamespace(
            is_authenticated=True,
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

    def test_responde_conflicto_de_regla_de_negocio(self):
        participante = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
        )
        with patch(
            "talleres.api_participantes.inscribir_participante",
            side_effect=CupoAgotadoError("No hay cupos."),
        ):
            response = inscripcion_participante_api(
                self.solicitar(participante, {"codigo_taller": "T-1"})
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["detail"], "No hay cupos.")
