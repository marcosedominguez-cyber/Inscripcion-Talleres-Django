"""Pruebas aisladas de cancelación, historial y bloqueo por reincidencia."""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from talleres import servicios
from talleres.models import Inscripcion, Taller, Usuario


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
                pk="espera-id", estado=Inscripcion.Estado.EN_ESPERA, save=Mock(),
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
            patch.object(servicios, "_notificar"),
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


    def test_cancelar_espera_no_promueve_a_otra_persona(self):
        resultado, mocks = self.ejecutar(estado=Inscripcion.Estado.EN_ESPERA)

        mocks["inscripciones"].filter.return_value.order_by.assert_not_called()
        self.assertFalse(resultado.promovido)
        self.assertEqual(
            mocks["cancelaciones"].create.call_args.kwargs["estado_anterior"],
            Inscripcion.Estado.EN_ESPERA,
        )


    def test_no_permite_cancelar_si_el_taller_ya_inicio(self):
        with self.assertRaises(servicios.PlazoCancelacionVencidoError):
            self.ejecutar(inicio=self.ahora)
        with self.assertRaises(servicios.PlazoCancelacionVencidoError):
            self.ejecutar(inicio=self.ahora - timedelta(minutes=1))


class NotificacionesTests(SimpleTestCase):
    """Entrega simulada, aislamiento del destinatario y contratos de la bandeja."""
    def setUp(self):
        from bson import ObjectId
        self.persona = Usuario(pk=ObjectId(), nombre="Ana", ci="123", rol=Usuario.Rol.PARTICIPANTE)
        self.taller = Taller(pk=ObjectId(), codigo="T-001", nombre="Cerámica", cupos=10,
            fecha_inicio=ServicioCancelacionTests.ahora + timedelta(days=1),
            fecha_fin=ServicioCancelacionTests.ahora + timedelta(days=3),
            estado_aprobacion=Taller.Aprobacion.APROBADO)
        self.factory = RequestFactory()

    def request(self, method="get", **kw):
        request = getattr(self.factory, method)("/api/participantes/notificaciones/", **kw)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, perfil=self.persona)
        return request

    def test_reintento_de_edicion_conserva_el_antes_y_el_aviso(self):
        from django.db import DatabaseError
        class Conflicto(Exception):
            def has_error_label(self, etiqueta):
                return etiqueta == "TransientTransactionError"
        intentos = []
        class AtomicSimulado:
            def __enter__(self):
                return self
            def __exit__(self, tipo, valor, tb):
                intentos.append(1)
                if len(intentos) == 1:
                    raise DatabaseError("Reintentar commit") from Conflicto()
        self.taller.full_clean = Mock()
        self.taller.save = Mock()
        with patch.object(servicios, "atomic", return_value=AtomicSimulado()), \
             patch.object(servicios.time, "sleep"), \
             patch.object(servicios, "consultar_espera", return_value=[]), \
             patch.object(Taller, "objects"), \
             patch.object(Inscripcion, "objects") as inscripciones, \
             patch.object(servicios, "_notificar_edicion_taller") as enviar:
            inscripciones.filter.return_value.values_list.return_value = []
            servicios.actualizar_taller(self.taller, {"nombre": "Nuevo nombre"})
        self.assertEqual(len(intentos), 2)
        self.assertEqual(enviar.call_count, 2)
        for llamada in enviar.call_args_list:
            self.assertEqual(llamada.args[1]["nombre"], ("Cerámica", "Nuevo nombre"))

    def test_edicion_envia_a_confirmados_y_espera_una_vez_por_persona(self):
        from bson import ObjectId
        otro = ObjectId()
        with patch.object(Inscripcion, "objects") as gestor, patch.object(servicios, "_notificar") as enviar:
            gestor.filter.return_value.values_list.return_value = [self.persona.pk, otro, self.persona.pk]
            servicios._notificar_edicion_taller(self.taller, {"cupos": (8, 10)})
        self.assertEqual(enviar.call_count, 2)
        self.assertEqual({c.args[0].pk for c in enviar.call_args_list}, {self.persona.pk, otro})
        self.assertEqual(len({c.args[4] for c in enviar.call_args_list}), 1)
        self.assertIn("8 → 10", enviar.call_args.args[3])
        self.assertEqual(gestor.filter.call_args.kwargs["estado__in"], ["confirmada", "en_espera"])


    def test_no_puede_marcar_avisos_ajenos(self):
        from talleres.api_participantes import leer_notificacion_api
        from talleres.models import Notificacion
        with patch.object(Notificacion, "objects") as gestor:
            gestor.filter.return_value.exists.return_value = False
            response = leer_notificacion_api(self.request("post"), str(self.persona.pk))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(gestor.filter.call_args.kwargs["participante"], self.persona)
        gestor.filter.return_value.filter.return_value.update.assert_not_called()


    def test_exige_sesion_y_no_acepta_cursor_invalido(self):
        from talleres.api_participantes import notificaciones_api, leer_notificacion_api
        request = self.request()
        request.user = AnonymousUser()
        self.assertEqual(notificaciones_api(request).status_code, 401)
        self.assertEqual(notificaciones_api(self.request(data={"antes": "invalido"})).status_code, 400)
        self.assertEqual(leer_notificacion_api(self.request("post"), "invalido").status_code, 404)

    def test_lectura_requiere_csrf(self):
        from talleres.api_participantes import leer_notificacion_api
        request = self.request("post")
        middleware = CsrfViewMiddleware(lambda req: None)
        middleware.process_request(request)
        self.assertEqual(middleware.process_view(request, leer_notificacion_api, (),
            {"identificador": str(self.persona.pk)}).status_code, 403)
