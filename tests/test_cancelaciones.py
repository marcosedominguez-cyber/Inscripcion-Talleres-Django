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
        with patch.object(servicios, "_notificar"), \
            patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Usuario, "objects", usuarios), \
             patch.object(servicios.Cancelacion, "objects") as cancelaciones:
            with self.assertRaises(servicios.ParticipanteNoEncontradoError):
                servicios.cancelar_inscripcion("000", "T-001")
        cancelaciones.create.assert_not_called()

        talleres = Mock()
        talleres.get.side_effect = Taller.DoesNotExist
        with patch.object(servicios, "_notificar"), \
            patch.object(servicios, "atomic", return_value=nullcontext()), \
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
        with patch.object(servicios, "_notificar"), \
            patch.object(servicios, "atomic", return_value=nullcontext()), \
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
        with patch.object(servicios, "_notificar"), \
            patch.object(servicios, "atomic", return_value=nullcontext()), \
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

    def test_evento_repetido_no_duplica_aviso_y_conserva_lectura(self):
        from talleres.models import Notificacion
        almacen = {}
        def entregar(**kw):
            key = (kw["participante"].pk, kw["clave_evento"])
            if key in almacen:
                return almacen[key], False
            almacen[key] = SimpleNamespace(**kw["defaults"], leida=False)
            return almacen[key], True
        with patch.object(Notificacion, "objects") as gestor:
            gestor.get_or_create.side_effect = entregar
            primero = servicios._notificar(self.persona, "promocion", "Plaza", "Texto", "evento:1")
            primero.leida = True
            segundo = servicios._notificar(self.persona, "promocion", "Plaza", "Texto", "evento:1")
        self.assertIs(primero, segundo)
        self.assertEqual(len(almacen), 1)
        self.assertTrue(segundo.leida)

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

    def test_edicion_sin_cambios_no_envia(self):
        with patch.object(servicios, "_notificar") as enviar:
            servicios._notificar_edicion_taller(self.taller, {})
        enviar.assert_not_called()

    def test_promocion_entrega_solo_a_quien_recibe_plaza(self):
        candidato = SimpleNamespace(pk="espera-1", participante=self.persona,
            estado="en_espera", save=Mock())
        with patch.object(servicios.timezone, "now", return_value=ServicioCancelacionTests.ahora), \
             patch.object(servicios, "consultar_espera", return_value=[candidato]), \
             patch.object(servicios, "_validar_superposicion"), \
             patch.object(servicios, "_serializar_inscripciones"), \
             patch.object(servicios, "_notificar") as enviar:
            elegido, _ = servicios._promover_desde_espera(self.taller)
        self.assertIs(elegido, candidato)
        self.assertEqual(candidato.estado, "confirmada")
        enviar.assert_called_once()
        self.assertIs(enviar.call_args.args[0], self.persona)
        self.assertEqual(enviar.call_args.args[1], "promocion")

    def test_fuera_de_plazo_no_generan_aviso_de_promocion(self):
        with patch.object(servicios.timezone, "now", return_value=self.taller.fecha_inicio), \
             patch.object(servicios, "_notificar") as enviar:
            elegido, _ = servicios._promover_desde_espera(self.taller)
        self.assertIsNone(elegido)
        enviar.assert_not_called()

    def test_bloqueo_informa_origen_manual_o_cancelaciones(self):
        from talleres.models import Notificacion
        for motivo in (Bloqueo.Motivo.MANUAL, Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS):
            self.persona.bloqueado = False
            with patch.object(Bloqueo, "objects") as bloqueos, \
                 patch.object(servicios, "_marcar_bloqueado"), \
                 patch.object(Notificacion, "objects") as avisos:
                bloqueos.filter.return_value.order_by.return_value.first.return_value = None
                bloqueos.create.return_value = SimpleNamespace(pk="bloqueo-1")
                avisos.get_or_create.return_value = (SimpleNamespace(), True)
                servicios._abrir_bloqueo(self.persona, motivo)
                contenido = avisos.get_or_create.call_args.kwargs
            self.assertEqual(contenido["clave_evento"], "bloqueo:bloqueo-1")
            self.assertIn(dict(Bloqueo.Motivo.choices)[motivo], contenido["defaults"]["mensaje"])

    def test_bloqueo_reutilizado_no_reenvia(self):
        with patch.object(Bloqueo, "objects") as bloqueos, \
             patch.object(servicios, "_marcar_bloqueado"), \
             patch.object(servicios, "_notificar") as enviar:
            bloqueos.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(pk="b")
            servicios._abrir_bloqueo(self.persona, Bloqueo.Motivo.MANUAL, reutilizar=True)
        enviar.assert_not_called()

    def test_bandeja_solo_consulta_al_participante_autenticado(self):
        from talleres.api_participantes import notificaciones_api
        from talleres.models import Notificacion
        aviso = SimpleNamespace(pk=self.persona.pk, tipo="bloqueo", titulo="Bloqueo",
            mensaje="Motivo", fecha=ServicioCancelacionTests.ahora, leida=False, taller_id=None)
        with patch.object(Notificacion, "objects") as gestor:
            gestor.filter.return_value.filter.return_value.count.return_value = 1
            gestor.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = [aviso]
            response = notificaciones_api(self.request())
        self.assertEqual(response.status_code, 200)
        gestor.filter.assert_called_once_with(participante=self.persona)
        self.assertEqual(json.loads(response.content)["no_leidas"], 1)

    def test_no_puede_marcar_avisos_ajenos(self):
        from talleres.api_participantes import leer_notificacion_api
        from talleres.models import Notificacion
        with patch.object(Notificacion, "objects") as gestor:
            gestor.filter.return_value.exists.return_value = False
            response = leer_notificacion_api(self.request("post"), str(self.persona.pk))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(gestor.filter.call_args.kwargs["participante"], self.persona)
        gestor.filter.return_value.filter.return_value.update.assert_not_called()

    def test_lectura_es_idempotente(self):
        from talleres.api_participantes import leer_notificacion_api
        from talleres.models import Notificacion
        with patch.object(Notificacion, "objects") as gestor:
            gestor.filter.return_value.exists.return_value = True
            response = leer_notificacion_api(self.request("post"), str(self.persona.pk))
        self.assertEqual(response.status_code, 200)
        gestor.filter.return_value.filter.assert_called_once_with(leida=False)
        gestor.filter.return_value.filter.return_value.update.assert_called_once_with(leida=True)

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
