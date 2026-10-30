"""Pruebas aisladas de cancelación, historial y bloqueo por reincidencia."""

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from talleres import servicios
from talleres.api_participantes import cancelar_inscripcion_api, inscripcion_participante_api
from talleres.models import Bloqueo, Inscripcion, Taller, Usuario


class ServicioCancelacionTests(SimpleTestCase):
    ahora = datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc)

    def ejecutar(self, *, estado=Inscripcion.Estado.CONFIRMADA, inicio=None,
                 cancelaciones=0, activa=True, promovido="crear", ahora=None):
        participante = SimpleNamespace(
            pk="participante-id", cancelaciones_consecutivas=cancelaciones,
        )
        taller = SimpleNamespace(
            pk="taller-id", codigo="T-001", nombre="Taller de prueba",
            fecha_inicio=inicio or self.ahora + timedelta(days=1),
            estado_aprobacion=Taller.Aprobacion.APROBADO,
        )
        inscripcion = None
        if activa:
            inscripcion = SimpleNamespace(estado=estado, delete=Mock())
        siguiente = None
        if promovido == "crear":
            siguiente = SimpleNamespace(
                estado=Inscripcion.Estado.EN_ESPERA, save=Mock(),
                participante=SimpleNamespace(pk="espera-id", cancelaciones_consecutivas=0),
            )
        elif promovido is not None:
            siguiente = promovido
        cancelacion = SimpleNamespace(
            pk="cancelacion-id", codigo_taller="T-001",
            nombre_taller="Taller de prueba", estado_anterior=estado,
            fecha_cancelacion=self.ahora,
        )
        usuarios = Mock()
        usuarios.get.return_value = participante
        talleres = Mock()
        talleres.get.return_value = taller
        inscripciones = Mock()
        inscripciones.filter.return_value.first.return_value = inscripcion
        inscripciones.filter.return_value.order_by.return_value.first.return_value = siguiente
        cancelaciones_manager = Mock()
        cancelaciones_manager.create.return_value = cancelacion
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = None
        bloqueos.create.return_value = SimpleNamespace(pk="bloqueo-id")
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Usuario, "objects", usuarios),
            patch.object(servicios.Taller, "objects", talleres),
            patch.object(servicios.Inscripcion, "objects", inscripciones),
            patch.object(servicios.Cancelacion, "objects", cancelaciones_manager),
            patch.object(servicios, "consultar_espera", return_value=[siguiente] if siguiente else []),
            patch.object(servicios, "buscar_superposicion", return_value=None),
            patch.object(servicios, "_serializar_inscripciones"),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.timezone, "now", return_value=ahora or self.ahora),
        ):
            resultado = servicios.cancelar_inscripcion("12345678", "T-001")
        return resultado, {
            "participante": participante, "taller": taller,
            "inscripcion": inscripcion, "siguiente": siguiente,
            "usuarios": usuarios, "talleres": talleres,
            "inscripciones": inscripciones,
            "cancelaciones": cancelaciones_manager,
            "bloqueos": bloqueos,
        }

    def test_confirma_cancelacion_conserva_antecedente_y_promueve(self):
        resultado, mocks = self.ejecutar()

        mocks["cancelaciones"].create.assert_called_once_with(
            participante=mocks["participante"], taller=mocks["taller"],
            codigo_taller="T-001", nombre_taller="Taller de prueba",
            estado_anterior=Inscripcion.Estado.CONFIRMADA,
        )
        mocks["inscripcion"].delete.assert_called_once_with()
        mocks["usuarios"].filter.assert_called_once_with(pk="participante-id")
        mocks["usuarios"].filter.return_value.update.assert_called_once()
        mocks["siguiente"].save.assert_called_once_with(update_fields=["estado"])
        self.assertEqual(mocks["siguiente"].estado, Inscripcion.Estado.CONFIRMADA)
        self.assertTrue(resultado.promovido)
        self.assertEqual(resultado.cancelaciones_consecutivas, 1)
        self.assertFalse(resultado.cuenta_bloqueada)

    def test_cancelar_espera_no_promueve_a_otra_persona(self):
        resultado, mocks = self.ejecutar(estado=Inscripcion.Estado.EN_ESPERA)

        mocks["inscripciones"].filter.return_value.order_by.assert_not_called()
        self.assertFalse(resultado.promovido)
        self.assertEqual(
            mocks["cancelaciones"].create.call_args.kwargs["estado_anterior"],
            Inscripcion.Estado.EN_ESPERA,
        )

    def test_tercera_cancelacion_bloquea_y_abre_episodio_automatico(self):
        resultado, mocks = self.ejecutar(cancelaciones=2)

        self.assertEqual(resultado.cancelaciones_consecutivas, 3)
        self.assertTrue(resultado.cuenta_bloqueada)
        mocks["bloqueos"].create.assert_called_once()
        kwargs = mocks["bloqueos"].create.call_args.kwargs
        self.assertEqual(kwargs["motivo"], Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS)
        self.assertIsNone(kwargs["bloqueado_por"])
        self.assertTrue(kwargs["participante"].bloqueado)
        self.assertIn(
            call(bloqueado=True),
            mocks["usuarios"].filter.return_value.update.call_args_list,
        )

    def test_no_permite_cancelar_si_el_taller_ya_inicio(self):
        with self.assertRaises(servicios.PlazoCancelacionVencidoError):
            self.ejecutar(inicio=self.ahora)
        with self.assertRaises(servicios.PlazoCancelacionVencidoError):
            self.ejecutar(inicio=self.ahora - timedelta(minutes=1))

    def test_no_permite_cancelar_sin_inscripcion_activa(self):
        with self.assertRaises(servicios.InscripcionNoEncontradaError):
            self.ejecutar(activa=False)

    def test_errores_de_participante_y_taller_no_escriben(self):
        usuarios = Mock()
        usuarios.get.side_effect = Usuario.DoesNotExist
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects", usuarios), \
             patch.object(servicios.Cancelacion, "objects") as cancelaciones:
            with self.assertRaises(servicios.ParticipanteNoEncontradoError):
                servicios.cancelar_inscripcion("000", "T-001")
        cancelaciones.create.assert_not_called()

        talleres = Mock()
        talleres.get.side_effect = Taller.DoesNotExist
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects") as usuarios, \
             patch.object(servicios.Taller, "objects", talleres), \
             patch.object(servicios.Cancelacion, "objects") as cancelaciones:
            usuarios.get.return_value = SimpleNamespace(cancelaciones_consecutivas=0)
            with self.assertRaises(servicios.TallerNoEncontradoError):
                servicios.cancelar_inscripcion("123", "T-999")
        cancelaciones.create.assert_not_called()


class BloqueoInscripcionTests(SimpleTestCase):
    def test_cuenta_bloqueada_no_consulta_taller_ni_crea_inscripcion(self):
        participante = SimpleNamespace(
            pk="participante-id", cancelaciones_consecutivas=3,
        )
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects") as usuarios, \
             patch.object(servicios.Taller, "objects") as talleres, \
             patch.object(servicios.Inscripcion, "objects") as inscripciones:
            usuarios.get.return_value = participante
            with self.assertRaises(servicios.CuentaBloqueadaError):
                servicios.inscribir_participante("123", "T-001")
        talleres.get.assert_not_called()
        inscripciones.create.assert_not_called()

    def test_bloqueo_manual_impide_inscripcion_aunque_el_contador_sea_cero(self):
        participante = SimpleNamespace(
            pk="participante-id", cancelaciones_consecutivas=0, bloqueado=True,
        )
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects") as usuarios, \
             patch.object(servicios.Taller, "objects") as talleres:
            usuarios.get.return_value = participante
            with self.assertRaises(servicios.CuentaBloqueadaError):
                servicios.solicitar_espera("123", "T-001")
        talleres.get.assert_not_called()


class ApiCancelacionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.perfil = SimpleNamespace(
            rol=Usuario.Rol.PARTICIPANTE, ci="12345678",
            cancelaciones_consecutivas=0,
        )
        self.user = SimpleNamespace(
            is_authenticated=True, is_active=True, perfil=self.perfil,
        )

    def solicitar(self, datos, user=None):
        request = self.factory.post(
            "/api/participantes/inscripciones/cancelar/",
            data=json.dumps(datos), content_type="application/json",
        )
        request.user = user if user is not None else self.user
        return request

    def cancelacion(self, **cambios):
        datos = dict(
            codigo_taller="T-001", nombre_taller="Taller de prueba",
            estado_anterior=Inscripcion.Estado.CONFIRMADA,
            fecha_cancelacion=datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc),
            promovido=False, cancelaciones_consecutivas=1, cuenta_bloqueada=False,
        )
        datos.update(cambios)
        return SimpleNamespace(**datos)

    def test_cancela_usando_la_identidad_de_la_sesion(self):
        with patch(
            "talleres.api_participantes.cancelar_inscripcion",
            return_value=self.cancelacion(),
        ) as servicio:
            response = cancelar_inscripcion_api(self.solicitar({"codigo_taller": "T-001"}))

        self.assertEqual(response.status_code, 200)
        servicio.assert_called_once_with("12345678", "T-001")
        datos = json.loads(response.content)
        self.assertEqual(datos["cancelacion"]["codigo"], "T-001")
        self.assertFalse(datos["promovido"])
        self.assertFalse(datos["inscripciones_bloqueadas"])

    def test_rechaza_identificador_adicional_y_cuerpo_invalido(self):
        with patch("talleres.api_participantes.cancelar_inscripcion") as servicio:
            response = cancelar_inscripcion_api(self.solicitar({
                "codigo_taller": "T-001", "ci": "otra",
            }))
        self.assertEqual(response.status_code, 400)
        servicio.assert_not_called()
        self.assertEqual(cancelar_inscripcion_api(self.solicitar({})).status_code, 400)

    def test_mapea_errores_de_negocio(self):
        casos = (
            (servicios.InscripcionNoEncontradaError("sin inscripción"), 404),
            (servicios.PlazoCancelacionVencidoError("taller iniciado"), 409),
        )
        for error, estado in casos:
            with self.subTest(error=error), patch(
                "talleres.api_participantes.cancelar_inscripcion",
                side_effect=error,
            ):
                response = cancelar_inscripcion_api(
                    self.solicitar({"codigo_taller": "T-001"})
                )
                self.assertEqual(response.status_code, estado)

    def test_post_exige_csrf(self):
        request = self.factory.post(
            "/api/participantes/inscripciones/cancelar/",
            data=json.dumps({"codigo_taller": "T-001"}),
            content_type="application/json",
        )
        request.user = self.user
        middleware = CsrfViewMiddleware(lambda req: None)
        middleware.process_request(request)
        response = middleware.process_view(
            request, cancelar_inscripcion_api, (), {}
        )
        self.assertEqual(response.status_code, 403)

    def test_exige_sesion_y_rol_participante(self):
        self.assertEqual(
            cancelar_inscripcion_api(
                self.solicitar({"codigo_taller": "T-001"}, AnonymousUser())
            ).status_code,
            401,
        )
        instructor = SimpleNamespace(
            is_authenticated=True, is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR, ci="12345678"),
        )
        self.assertEqual(
            cancelar_inscripcion_api(
                self.solicitar({"codigo_taller": "T-001"}, instructor)
            ).status_code,
            403,
        )


class ApiHistorialCancelacionesTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.perfil = SimpleNamespace(
            rol=Usuario.Rol.PARTICIPANTE, ci="12345678",
            cancelaciones_consecutivas=3,
        )
        self.user = SimpleNamespace(
            is_authenticated=True, is_active=True, perfil=self.perfil,
        )

    def test_lista_historial_y_expone_bloqueo(self):
        cancelacion = SimpleNamespace(
            codigo_taller="T-001", nombre_taller="Taller cancelado",
            estado_anterior=Inscripcion.Estado.CONFIRMADA,
            fecha_cancelacion=datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc),
        )
        request = self.factory.get("/api/participantes/inscripciones/")
        request.user = self.user
        with patch(
            "talleres.api_participantes.listar_inscripciones_participante",
            return_value=[],
        ), patch(
            "talleres.api_participantes.listar_cancelaciones_participante",
            return_value=[cancelacion],
        ):
            response = inscripcion_participante_api(request)

        self.assertEqual(response.status_code, 200)
        datos = json.loads(response.content)
        self.assertEqual(datos["cancelaciones"], [{
            "codigo": "T-001", "nombre": "Taller cancelado",
            "estado_anterior": "confirmada",
            "fecha_cancelacion": "2030-10-15T09:00:00Z",
        }])
        self.assertEqual(datos["cancelaciones_consecutivas"], 3)
        self.assertTrue(datos["inscripciones_bloqueadas"])
