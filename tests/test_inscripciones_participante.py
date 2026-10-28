"""Pruebas aisladas para la inscripción desde el catálogo de participantes."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import nullcontext

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.db import DatabaseError, IntegrityError
from django.test import RequestFactory, SimpleTestCase

from talleres.servicios import (
    CupoAgotadoError,
    DatosParticipanteInvalidosError,
    InscripcionDuplicadaError,
    PlazoInscripcionVencidoError,
    TallerNoAprobadoError,
)
from talleres import servicios
from talleres.api_participantes import inscripcion_participante_api
from talleres.models import Inscripcion, Taller, Usuario


class ServicioInscripcionTests(SimpleTestCase):
    """El manager y la transacción se simulan; no se usa Atlas ni SQLite."""

    ahora = datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc)

    def test_nombre_vacio_usa_excepcion_web_sin_persistir(self):
        with self.assertRaises(DatosParticipanteInvalidosError):
            servicios.registrar_participante("   ", "11111111")

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
            patch.object(servicios.timezone, "now", return_value=ahora or self.ahora),
        ):
            usuarios.get.return_value = participante
            resultado = servicios.inscribir_participante("12345678", "T-001")
        return resultado, participante, taller, manager_talleres, manager_inscripciones, usuarios

    def test_acepta_inscripcion_un_segundo_antes_del_limite(self):
        inicio = self.ahora + timedelta(minutes=5)
        limite = inicio - timedelta(minutes=1)
        resultado, participante, taller, talleres, inscripciones, usuarios = self.ejecutar(
            inicio=inicio, ahora=limite - timedelta(seconds=1),
        )
        self.assertEqual(resultado.pk, "inscripcion-id")
        usuarios.get.assert_called_once()
        self.assertEqual(talleres.filter.call_count, 2)
        inscripciones.create.assert_called_once_with(participante=participante, taller=taller)

    def test_rechaza_inscripcion_en_el_limite_exacto_de_un_minuto(self):
        inicio = self.ahora + timedelta(minutes=5)
        with self.assertRaises(PlazoInscripcionVencidoError):
            self.ejecutar(inicio=inicio, ahora=inicio - timedelta(minutes=1))

    def test_rechaza_taller_no_aprobado(self):
        for estado in (Taller.Aprobacion.PENDIENTE, Taller.Aprobacion.RECHAZADO):
            with self.subTest(estado=estado), self.assertRaises(TallerNoAprobadoError):
                self.ejecutar(estado=estado)

    def test_rechaza_duplicada_y_sin_cupos(self):
        with self.assertRaises(InscripcionDuplicadaError):
            self.ejecutar(duplicada=True)
        with self.assertRaises(CupoAgotadoError):
            self.ejecutar(disponibles=0)

    def test_convierte_carrera_de_inscripcion_duplicada_en_error_de_negocio(self):
        with self.assertRaises(InscripcionDuplicadaError):
            self.ejecutar(create_error=IntegrityError("duplicada"))

    def test_rechaza_despues_del_limite_y_al_inicio_del_taller(self):
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
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR, ci="12345678"),
        )
        self.assertEqual(
            inscripcion_participante_api(self.solicitar(instructor, {"codigo_taller": "T-1"})).status_code,
            403,
        )
        inactivo = SimpleNamespace(
            is_authenticated=True,
            is_active=False,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="12345678"),
        )
        self.assertEqual(
            inscripcion_participante_api(
                self.solicitar(inactivo, {"codigo_taller": "T-1"})
            ).status_code,
            403,
        )

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

    def test_responde_conflicto_de_regla_de_negocio(self):
        participante = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
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


class ServicioEsperaTests(SimpleTestCase):
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
             patch.object(servicios, "consultar_espera", side_effect=[[None] * ocupadas, [SimpleNamespace(pk="nueva")]]), \
             patch.object(servicios.timezone, "now", return_value=ServicioInscripcionTests.ahora):
            usuarios.get.return_value = SimpleNamespace(pk="p")
            self.escrituras.get.return_value = taller
            return servicios.solicitar_espera("123", "T-001")

    def test_admite_ultimo_lugar_sin_consumir_plaza_confirmada(self):
        self.ejecutar(ocupadas=1)
        self.assertEqual(self.inscripciones.create.call_args.kwargs["estado"], Inscripcion.Estado.EN_ESPERA)

    def test_rechazos_no_escriben_ni_reordenan(self):
        for opciones, error in [
            ({"ocupadas": 2}, servicios.ListaEsperaLlenaError),
            ({"cupos": 4}, servicios.ListaEsperaLlenaError),
            ({"disponibles": 1}, servicios.TallerConCuposError),
            ({"duplicada": True}, InscripcionDuplicadaError),
        ]:
            with self.subTest(opciones=opciones), self.assertRaises(error):
                self.ejecutar(**opciones)
            self.inscripciones.create.assert_not_called()
            self.escrituras.filter.assert_not_called()

    def test_redondeo(self):
        from talleres.reglas import limite_espera
        for cupos, esperado in [(4, 0), (5, 1), (9, 1), (10, 2), (14, 2), (40, 8)]:
            self.assertEqual(limite_espera(cupos), esperado)


class ApiEsperaTests(SimpleTestCase):
    setUp = ApiInscripcionParticipanteTests.setUp
    solicitar = ApiInscripcionParticipanteTests.solicitar

    def test_espera_usa_sesion_y_rechaza_suplantacion(self):
        from talleres.api_participantes import espera_participante_api
        user = SimpleNamespace(is_authenticated=True, is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE, ci="123"))
        with patch("talleres.api_participantes.solicitar_espera",
                   return_value=SimpleNamespace(pk="i", estado="en_espera")) as guardar:
            response = espera_participante_api(self.solicitar(user, {"codigo_taller": "T-1"}))
            self.assertEqual(response.status_code, 201)
            guardar.assert_called_once_with("123", "T-1")
            self.assertEqual(json.loads(response.content)["inscripcion"]["estado"], "en_espera")
            self.assertEqual(espera_participante_api(self.solicitar(user,
                {"codigo_taller": "T-1", "ci": "otra"})).status_code, 400)
        self.assertEqual(espera_participante_api(self.solicitar()).status_code, 401)
        with patch("talleres.api_participantes.solicitar_espera",
                   side_effect=servicios.ListaEsperaLlenaError("Llena")):
            self.assertEqual(espera_participante_api(self.solicitar(user,
                {"codigo_taller": "T-1"})).status_code, 409)


class ApiMisInscripcionesTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.participante = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(
                rol=Usuario.Rol.PARTICIPANTE, ci="12345678",
                cancelaciones_consecutivas=0,
            ),
        )
        self.cancelaciones = patch(
            "talleres.api_participantes.listar_cancelaciones_participante",
            return_value=[],
        )
        self.cancelaciones.start()
        self.addCleanup(self.cancelaciones.stop)

    def solicitar(self, user=None):
        request = self.factory.get("/api/participantes/inscripciones/")
        request.user = user if user is not None else AnonymousUser()
        return request

    def inscripcion(self, *, codigo, estado, taller_id=None, inicio=None, instructor=True):
        taller = SimpleNamespace(
            codigo=codigo,
            nombre=f"Taller {codigo}",
            descripcion="",
            cupos=10,
            fecha_inicio=inicio or datetime(2030, 10, 15, 10, 0, tzinfo=dt_timezone.utc),
            fecha_fin=datetime(2030, 10, 15, 12, 0, tzinfo=dt_timezone.utc),
            instructor_id="instructor-1" if instructor else None,
            instructor=SimpleNamespace(nombre="Ana Pérez") if instructor else None,
        )
        return SimpleNamespace(
            taller_id=taller_id or codigo,
            taller=taller,
            estado=estado,
            fecha_solicitud=datetime(2030, 10, 1, 12, 0, tzinfo=dt_timezone.utc),
        )

    def test_requiere_sesion_y_rol_participante(self):
        self.assertEqual(inscripcion_participante_api(self.solicitar()).status_code, 401)
        instructor = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR, ci="12345678"),
        )
        self.assertEqual(
            inscripcion_participante_api(self.solicitar(instructor)).status_code,
            403,
        )

    def test_lista_estados_sin_posiciones_y_con_datos_del_taller(self):
        confirmada = self.inscripcion(
            codigo="T-001", estado=Inscripcion.Estado.CONFIRMADA,
        )
        en_espera = self.inscripcion(
            codigo="T-002", estado=Inscripcion.Estado.EN_ESPERA,
            inicio=datetime(2030, 10, 20, 10, 0, tzinfo=dt_timezone.utc),
        )
        with patch(
            "talleres.api_participantes.listar_inscripciones_participante",
            return_value=[en_espera, confirmada],
        ) as consulta:
            response = inscripcion_participante_api(self.solicitar(self.participante))

        self.assertEqual(response.status_code, 200)
        datos = json.loads(response.content)
        self.assertEqual(set(datos), {
            "inscripciones", "cancelaciones", "cancelaciones_consecutivas",
            "limite_cancelaciones", "inscripciones_bloqueadas", "zona_horaria",
        })
        self.assertEqual(datos["zona_horaria"], "America/La_Paz")
        self.assertEqual(datos["cancelaciones"], [])
        self.assertFalse(datos["inscripciones_bloqueadas"])
        self.assertEqual(
            [item["estado"] for item in datos["inscripciones"]],
            [Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.EN_ESPERA],
        )
        self.assertEqual(datos["inscripciones"][0]["instructor"], "Ana Pérez")
        self.assertEqual(datos["inscripciones"][0]["cupos"], 10)
        self.assertIn("fecha_solicitud", datos["inscripciones"][0])
        self.assertNotIn("posicion_espera", datos["inscripciones"][0])
        consulta.assert_called_once_with(self.participante.perfil)

    def test_promocion_no_duplica_el_taller_y_prioriza_confirmada(self):
        en_espera = self.inscripcion(
            codigo="T-001", estado=Inscripcion.Estado.EN_ESPERA, taller_id="taller-1",
        )
        confirmada = self.inscripcion(
            codigo="T-001", estado=Inscripcion.Estado.CONFIRMADA, taller_id="taller-1",
        )
        with patch(
            "talleres.api_participantes.listar_inscripciones_participante",
            return_value=[en_espera, confirmada],
        ):
            response = inscripcion_participante_api(self.solicitar(self.participante))

        datos = json.loads(response.content)
        self.assertEqual(len(datos["inscripciones"]), 1)
        self.assertEqual(datos["inscripciones"][0]["estado"], Inscripcion.Estado.CONFIRMADA)

    def test_lista_vacia_y_error_de_consulta(self):
        with patch(
            "talleres.api_participantes.listar_inscripciones_participante",
            return_value=[],
        ):
            response = inscripcion_participante_api(self.solicitar(self.participante))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["inscripciones"], [])

        with patch(
            "talleres.api_participantes.listar_inscripciones_participante",
            side_effect=DatabaseError("fallo"),
        ):
            response = inscripcion_participante_api(self.solicitar(self.participante))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"],
            "No se pudieron consultar tus inscripciones.",
        )

    def test_endpoint_omite_talleres_finalizados_en_ambos_estados(self):
        ahora = datetime(2030, 10, 15, 12, 0, tzinfo=dt_timezone.utc)
        finalizada_confirmada = self.inscripcion(
            codigo="T-001", estado=Inscripcion.Estado.CONFIRMADA,
        )
        finalizada_confirmada.taller.fecha_fin = ahora - timedelta(seconds=1)
        finalizada_en_espera = self.inscripcion(
            codigo="T-002", estado=Inscripcion.Estado.EN_ESPERA,
        )
        finalizada_en_espera.taller.fecha_fin = ahora
        futura = self.inscripcion(
            codigo="T-003", estado=Inscripcion.Estado.CONFIRMADA,
        )
        futura.taller.fecha_fin = ahora + timedelta(seconds=1)
        manager = Mock()
        manager.filter.return_value.select_related.return_value = [
            finalizada_confirmada, finalizada_en_espera, futura,
        ]
        with patch("talleres.consultas.Inscripcion.objects", manager), patch(
            "talleres.consultas.timezone.now", return_value=ahora
        ):
            response = inscripcion_participante_api(self.solicitar(self.participante))

        datos = json.loads(response.content)
        self.assertEqual([item["codigo"] for item in datos["inscripciones"]], ["T-003"])
