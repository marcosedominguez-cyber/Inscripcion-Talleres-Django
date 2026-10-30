"""Pruebas aisladas del bloqueo manual, la rehabilitación y su historial."""

from contextlib import nullcontext
from datetime import datetime, timezone as dt_timezone
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bson import ObjectId
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django_mongodb_backend.fields import ObjectIdAutoField

from talleres import servicios
from talleres.admin import BloqueoAdmin, UsuarioAdmin
from talleres.admin_site import admin_site
from talleres.models import Bloqueo, Usuario


def participante(**cambios):
    datos = {
        "pk": ObjectId(),
        "rol": Usuario.Rol.PARTICIPANTE,
        "bloqueado": False,
        "cancelaciones_consecutivas": 0,
    }
    datos.update(cambios)
    return SimpleNamespace(**datos)


def administrador():
    return SimpleNamespace(pk="admin-id", is_active=True, is_staff=True)


class AdminFormVacio:
    prepopulated_fields = []

    def __iter__(self):
        return iter(())


class ModeloBloqueoTests(SimpleTestCase):
    def test_esquema_de_bloqueos_conserva_campos_y_restriccion_abierta(self):
        assert Bloqueo._meta.db_table == "bloqueos"
        assert isinstance(Bloqueo._meta.pk, ObjectIdAutoField)
        assert Bloqueo._meta.ordering == ["-fecha_bloqueo", "-id"]

        campos = {campo.name for campo in Bloqueo._meta.fields}
        assert campos == {
            "id", "participante", "motivo", "fecha_bloqueo", "bloqueado_por",
            "fecha_desbloqueo", "desbloqueado_por",
        }
        assert Bloqueo._meta.get_field("bloqueado_por").column == "bloqueado_por"
        assert Bloqueo._meta.get_field("desbloqueado_por").column == "desbloqueado_por"
        assert Bloqueo._meta.get_field("fecha_desbloqueo").null is True

        restriccion, = Bloqueo._meta.constraints
        assert restriccion.name == "bloqueo_abierto_unico"
        assert restriccion.fields == ("participante", "fecha_desbloqueo")
        assert restriccion.condition is None
        assert restriccion.nulls_distinct is False

    def test_participante_tiene_estado_persistido_y_motivos_controlados(self):
        campo = Usuario._meta.get_field("bloqueado")
        assert campo.default is False
        assert campo.null is False
        motivos = dict(Bloqueo.motivos_manuales())
        assert Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS not in motivos
        assert Bloqueo.Motivo.MANUAL in motivos


class ServicioBloqueoTests(SimpleTestCase):
    def ejecutar_bloqueo(self, participante, motivo, admin):
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = None
        creado = SimpleNamespace(pk=ObjectId(), motivo=motivo)
        bloqueos.create.return_value = creado
        usuarios = Mock()
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects", usuarios),
        ):
            resultado = servicios.bloquear_participante(
                participante, motivo, administrador=admin,
            )
        return resultado, bloqueos, usuarios

    def test_bloqueo_manual_crea_episodio_y_marca_al_participante(self):
        persona = participante()
        admin = administrador()
        resultado, bloqueos, usuarios = self.ejecutar_bloqueo(
            persona, Bloqueo.Motivo.MANUAL, admin,
        )

        self.assertEqual(resultado.motivo, Bloqueo.Motivo.MANUAL)
        bloqueos.create.assert_called_once()
        kwargs = bloqueos.create.call_args.kwargs
        self.assertIs(kwargs["participante"], persona)
        self.assertEqual(kwargs["motivo"], Bloqueo.Motivo.MANUAL)
        self.assertIs(kwargs["bloqueado_por"], admin)
        usuarios.filter.assert_called_once_with(pk=persona.pk)
        usuarios.filter.return_value.update.assert_called_once_with(bloqueado=True)
        self.assertTrue(persona.bloqueado)

    def test_no_permite_duplicar_un_bloqueo_activo(self):
        persona = participante()
        admin = administrador()
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = (
            SimpleNamespace(fecha_desbloqueo=None)
        )
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects") as usuarios,
        ):
            with self.assertRaises(servicios.ParticipanteYaBloqueadoError):
                servicios.bloquear_participante(
                    persona, Bloqueo.Motivo.MANUAL, administrador=admin,
                )
        bloqueos.create.assert_not_called()
        usuarios.filter.return_value.update.assert_not_called()

    def test_no_permite_bloquear_ya_marcado_aunque_no_consulte_historial(self):
        persona = participante(bloqueado=True)
        with patch.object(servicios.Bloqueo, "objects") as bloqueos:
            with self.assertRaises(servicios.ParticipanteYaBloqueadoError):
                servicios.bloquear_participante(
                    persona, Bloqueo.Motivo.MANUAL, administrador=administrador(),
                )
        bloqueos.filter.assert_not_called()

    def test_motivo_debe_ser_manual_cuando_lo_ejecuta_un_administrador(self):
        with self.assertRaises(servicios.MotivoBloqueoInvalidoError):
            servicios.bloquear_participante(
                participante(),
                Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS,
                administrador=administrador(),
            )

    def test_solo_sistema_puede_registrar_bloqueo_automatico(self):
        with self.assertRaises(servicios.MotivoBloqueoInvalidoError):
            servicios.bloquear_participante(
                participante(), Bloqueo.Motivo.MANUAL, administrador=None,
            )

    def test_rehabilitacion_cierra_episodio_y_reinicia_solo_el_ciclo_limite(self):
        persona = participante(bloqueado=True, cancelaciones_consecutivas=3)
        admin = administrador()
        abierto = SimpleNamespace(
            fecha_desbloqueo=None, desbloqueado_por=None, save=Mock(),
        )
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = abierto
        usuarios = Mock()
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects", usuarios),
            patch.object(servicios.timezone, "now", return_value=datetime(
                2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc,
            )),
        ):
            resultado = servicios.rehabilitar_participante(persona, admin)

        self.assertIs(resultado, abierto)
        abierto.save.assert_called_once_with(
            update_fields=["fecha_desbloqueo", "desbloqueado_por"],
        )
        self.assertEqual(
            abierto.fecha_desbloqueo,
            datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc),
        )
        self.assertIs(abierto.desbloqueado_por, admin)
        usuarios.filter.return_value.update.assert_called_once_with(
            bloqueado=False, cancelaciones_consecutivas=0,
        )
        self.assertFalse(persona.bloqueado)
        self.assertEqual(persona.cancelaciones_consecutivas, 0)

    def test_rehabilitacion_manual_no_borra_un_contador_inferior_al_limite(self):
        persona = participante(bloqueado=True, cancelaciones_consecutivas=1)
        abierto = SimpleNamespace(save=Mock())
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = abierto
        usuarios = Mock()
        with (
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects", usuarios),
        ):
            servicios.rehabilitar_participante(persona, administrador())
        usuarios.filter.return_value.update.assert_called_once_with(bloqueado=False)
        self.assertEqual(persona.cancelaciones_consecutivas, 1)

    def test_no_rehabilita_a_quien_no_esta_bloqueado(self):
        with patch.object(servicios, "atomic", return_value=nullcontext()), \
             patch.object(servicios.Bloqueo, "objects") as bloqueos, \
             patch.object(servicios.Usuario, "objects") as usuarios:
            bloqueos.filter.return_value.order_by.return_value.first.return_value = None
            with self.assertRaises(servicios.ParticipanteNoBloqueadoError):
                servicios.rehabilitar_participante(
                    participante(), administrador(),
                )
        usuarios.filter.return_value.update.assert_not_called()

    def test_estado_efectivo_combina_flag_y_contador_historico(self):
        self.assertTrue(servicios.esta_bloqueado(
            SimpleNamespace(bloqueado=True, cancelaciones_consecutivas=0)
        ))
        self.assertTrue(servicios.esta_bloqueado(
            SimpleNamespace(bloqueado=False, cancelaciones_consecutivas=3)
        ))
        self.assertFalse(servicios.esta_bloqueado(
            SimpleNamespace(bloqueado=False, cancelaciones_consecutivas=2)
        ))


class AdminBloqueoTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = UsuarioAdmin(Usuario, admin_site)
        self.persona = participante(nombre="Ana", ci="123")
        self.persona.__str__ = lambda: "123 - Ana"

    def solicitud(self, datos, user=None, *, method="post", path=None):
        path = path or "/admin/talleres/usuario/"
        if method == "get":
            request = self.factory.get(path)
        else:
            request = self.factory.post(path, datos)
        request.user = user or SimpleNamespace(
            is_active=True, is_staff=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.ADMINISTRADOR),
        )
        request.current_app = "admin"
        return request

    def url_accion(self, accion, participante=None):
        return f"/admin/talleres/usuario/{participante.pk}/{accion}/"

    def test_listado_muestra_estado_y_acciones_de_bloqueo(self):
        self.assertIn("bloqueado", self.admin.list_display)
        self.assertIn("bloquear_participantes", self.admin.actions)
        self.assertIn("rehabilitar_participantes", self.admin.actions)
        self.assertNotIn("rehabilitar_inscripciones", self.admin.actions)
        self.assertEqual(
            self.admin.change_form_template,
            "admin/talleres/usuario/change_form.html",
        )

    def test_urls_individuales_registradas(self):
        nombres = {patron.name for patron in self.admin.get_urls()}
        self.assertIn("talleres_usuario_bloquear", nombres)
        self.assertIn("talleres_usuario_rehabilitar", nombres)

    def test_ficha_individual_integra_el_boton_en_las_herramientas(self):
        persona = participante()
        html = render_to_string(
            self.admin.change_form_template,
            {
                "original": persona,
                "opts": Usuario._meta,
                "change": True,
                "add": False,
                "is_popup": False,
                "adminform": AdminFormVacio(),
                "inline_admin_formsets": [],
                "has_view_permission": True,
                "has_add_permission": True,
                "has_change_permission": True,
                "has_delete_permission": True,
                "has_editable_inline_admin_formsets": False,
                "show_save": True,
                "show_save_and_continue": True,
                "show_save_and_add_another": False,
                "show_delete_link": False,
                "save_as": False,
                "can_change": True,
            },
        )

        self.assertIn('class="object-tools"', html)
        self.assertIn("Bloquear participante", html)
        self.assertIn(
            reverse(
                "admin:talleres_usuario_bloquear",
                args=[str(persona.pk)],
            ),
            html,
        )

    def test_boton_individual_cambia_segun_el_estado(self):
        desbloqueado = participante()
        bloqueado = participante(bloqueado=True)

        html_desbloqueado = render_to_string(
            "admin/talleres/usuario/boton_accion.html",
            {"original": desbloqueado},
        )
        html_bloqueado = render_to_string(
            "admin/talleres/usuario/boton_accion.html",
            {"original": bloqueado},
        )

        self.assertIn("Bloquear participante", html_desbloqueado)
        self.assertNotIn("Rehabilitar participante", html_desbloqueado)
        self.assertIn(
            reverse(
                "admin:talleres_usuario_bloquear",
                args=[str(desbloqueado.pk)],
            ),
            html_desbloqueado,
        )
        self.assertIn("Rehabilitar participante", html_bloqueado)
        self.assertNotIn("Bloquear participante", html_bloqueado)
        self.assertIn(
            reverse(
                "admin:talleres_usuario_rehabilitar",
                args=[str(bloqueado.pk)],
            ),
            html_bloqueado,
        )

    def test_boton_individual_no_aparece_para_otros_roles(self):
        instructor = participante(rol=Usuario.Rol.INSTRUCTOR)
        html = render_to_string(
            "admin/talleres/usuario/boton_accion.html",
            {"original": instructor},
        )
        self.assertNotIn("Bloquear participante", html)
        self.assertNotIn("Rehabilitar participante", html)

    def test_vista_individual_de_bloqueo_muestra_motivos_y_confirmacion(self):
        request = self.solicitud(
            {}, method="get",
            path=self.url_accion("bloquear", self.persona),
        )
        with patch.object(self.admin, "get_object", return_value=self.persona):
            response = self.admin._vista_bloquear(
                request, str(self.persona.pk),
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bloquear participante")
        self.assertContains(response, "Confirmar bloqueo")
        self.assertContains(response, 'name="motivo"')
        self.assertContains(
            response, self.url_accion("bloquear", self.persona),
        )

    def test_vista_individual_de_bloqueo_ejecuta_el_servicio(self):
        request = self.solicitud(
            {"motivo": Bloqueo.Motivo.MANUAL},
            path=self.url_accion("bloquear", self.persona),
        )
        with patch.object(
            self.admin, "get_object", return_value=self.persona,
        ), patch(
            "talleres.admin.bloquear_participante",
            return_value=SimpleNamespace(),
        ) as bloquear, patch.object(self.admin, "message_user"):
            response = self.admin._vista_bloquear(
                request, str(self.persona.pk),
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse(
                "admin:talleres_usuario_change",
                args=[str(self.persona.pk)],
            ),
        )
        bloquear.assert_called_once_with(
            self.persona, Bloqueo.Motivo.MANUAL,
            administrador=request.user,
        )

    def test_vista_individual_de_bloqueo_rechaza_motivo_invalido(self):
        request = self.solicitud(
            {"motivo": "inventado"},
            path=self.url_accion("bloquear", self.persona),
        )
        with patch.object(
            self.admin, "get_object", return_value=self.persona,
        ), patch("talleres.admin.bloquear_participante") as bloquear, \
                patch.object(self.admin, "message_user") as mensaje:
            response = self.admin._vista_bloquear(
                request, str(self.persona.pk),
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(
            "Selecciona un motivo de bloqueo válido" in llamada.args[1]
            for llamada in mensaje.call_args_list
        ))
        bloquear.assert_not_called()

    def test_vista_individual_de_rehabilitacion_confirma_y_ejecuta(self):
        persona = participante(bloqueado=True)
        request = self.solicitud(
            {}, method="get",
            path=self.url_accion("rehabilitar", persona),
        )
        with patch.object(self.admin, "get_object", return_value=persona):
            confirmacion = self.admin._vista_rehabilitar(
                request, str(persona.pk),
            )

        self.assertEqual(confirmacion.status_code, 200)
        self.assertContains(confirmacion, "Rehabilitar participante")
        self.assertContains(confirmacion, "Confirmar rehabilitación")

        request = self.solicitud(
            {}, path=self.url_accion("rehabilitar", persona),
        )
        with patch.object(
            self.admin, "get_object", return_value=persona,
        ), patch(
            "talleres.admin.rehabilitar_participante",
            return_value=SimpleNamespace(),
        ) as rehabilitar, patch.object(self.admin, "message_user"):
            response = self.admin._vista_rehabilitar(
                request, str(persona.pk),
            )

        self.assertEqual(response.status_code, 302)
        rehabilitar.assert_called_once_with(persona, request.user)

    def test_vistas_individuales_rechazan_usuarios_no_autorizados(self):
        no_autorizados = [
            AnonymousUser(),
            SimpleNamespace(
                is_active=True, is_staff=True,
                perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE),
            ),
        ]
        for usuario in no_autorizados:
            request = self.solicitud(
                {}, user=usuario,
                path=self.url_accion("bloquear", self.persona),
            )
            with self.assertRaises(PermissionDenied):
                self.admin._vista_bloquear(
                    request, str(self.persona.pk),
                )
            with self.assertRaises(PermissionDenied):
                self.admin._vista_rehabilitar(
                    request, str(self.persona.pk),
                )

    def test_vistas_individuales_rechazan_identificadores_manipulados(self):
        request = self.solicitud(
            {}, method="get",
            path=self.url_accion("bloquear", self.persona),
        )
        with patch.object(self.admin, "get_object", return_value=None):
            with self.assertRaises(Http404):
                self.admin._vista_bloquear(
                    request, str(ObjectId()),
                )

        ajeno = participante(rol=Usuario.Rol.INSTRUCTOR)
        with patch.object(self.admin, "get_object", return_value=ajeno):
            with self.assertRaises(Http404):
                self.admin._vista_rehabilitar(
                    request, str(ajeno.pk),
                )

    def test_accion_sin_confirmar_muestra_formulario_con_motivos(self):
        request = self.solicitud({})
        response = self.admin.bloquear_participantes(request, [self.persona])

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bloquear participantes")
        self.assertContains(response, "Incumplimiento de normas")
        self.assertContains(response, 'name="motivo"')

    def test_accion_confirmada_llama_al_servicio_con_el_administrador(self):
        request = self.solicitud({
            "confirmar_bloqueo": "1",
            "motivo": Bloqueo.Motivo.INCUMPLIMIENTO_NORMAS,
        })
        with patch(
            "talleres.admin.bloquear_participante", return_value=SimpleNamespace(),
        ) as bloquear, patch.object(self.admin, "message_user"):
            self.admin.bloquear_participantes(request, [self.persona])

        bloquear.assert_called_once_with(
            self.persona, Bloqueo.Motivo.INCUMPLIMIENTO_NORMAS,
            administrador=request.user,
        )

    def test_accion_rechaza_motivo_ausente_sin_llamar_al_servicio(self):
        request = self.solicitud({"confirmar_bloqueo": "1"})
        with patch("talleres.admin.bloquear_participante") as bloquear, \
             patch.object(self.admin, "message_user") as mensaje:
            self.admin.bloquear_participantes(request, [self.persona])
        bloquear.assert_not_called()
        self.assertTrue(mensaje.called)

    def test_usuario_no_autorizado_no_puede_bloquear_ni_rehabilitar(self):
        request = self.solicitud({}, user=AnonymousUser())
        with patch("talleres.admin.bloquear_participante") as bloquear, \
             patch("talleres.admin.rehabilitar_participante") as rehabilitar, \
             patch.object(self.admin, "message_user"):
            self.admin.bloquear_participantes(request, [self.persona])
            self.admin.rehabilitar_participantes(request, [self.persona])
        bloquear.assert_not_called()
        rehabilitar.assert_not_called()

    def test_rehabilitacion_autorizada_llama_al_servicio(self):
        request = self.solicitud({})
        with patch(
            "talleres.admin.rehabilitar_participante", return_value=SimpleNamespace(),
        ) as rehabilitar, patch.object(self.admin, "message_user"):
            self.admin.rehabilitar_participantes(request, [self.persona])
        rehabilitar.assert_called_once_with(self.persona, request.user)

    def test_historial_es_solo_lectura(self):
        admin = BloqueoAdmin(Bloqueo, admin_site)
        request = self.solicitud({})
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))
        self.assertFalse(admin.has_delete_permission(request))


class FakeParticipantes:
    def __init__(self, documentos):
        self.documentos = documentos

    def find(self, consulta, proyeccion):
        assert consulta["bloqueado"] is True
        return [{"_id": documento["_id"]} for documento in self.documentos]


class FakeParticipantesInicializacion(FakeParticipantes):
    def _coincide(self, documento, consulta):
        if "$and" in consulta:
            return all(self._coincide(documento, parte) for parte in consulta["$and"])
        if "$or" in consulta:
            return any(self._coincide(documento, parte) for parte in consulta["$or"])
        for campo, condicion in consulta.items():
            existe = campo in documento
            valor = documento.get(campo)
            if isinstance(condicion, dict):
                if "$exists" in condicion:
                    if existe != condicion["$exists"]:
                        return False
                if "$gte" in condicion:
                    if not existe or valor < condicion["$gte"]:
                        return False
            elif valor != condicion:
                return False
        return True

    def update_many(self, consulta, actualizacion):
        modificados = 0
        for documento in self.documentos:
            if self._coincide(documento, consulta):
                documento.update(actualizacion["$set"])
                modificados += 1
        return SimpleNamespace(modified_count=modificados)

    def count_documents(self, consulta):
        return sum(
            self._coincide(documento, consulta) for documento in self.documentos
        )


class MigracionBloqueoTests(SimpleTestCase):
    def test_inicializa_solo_campos_ausentes_y_preserva_estado_decidido(self):
        migracion = import_module(
            "talleres.migrations.0008_usuario_bloqueado_bloqueo"
        )
        collection = FakeParticipantesInicializacion([
            {"_id": ObjectId(), "cancelaciones_consecutivas": 0},
            {"_id": ObjectId(), "cancelaciones_consecutivas": 3},
            {"_id": ObjectId(), "cancelaciones_consecutivas": 5, "bloqueado": False},
            {"_id": ObjectId(), "cancelaciones_consecutivas": 3, "bloqueado": None},
            {"_id": ObjectId(), "cancelaciones_consecutivas": 3, "bloqueado": True},
            {"_id": ObjectId()},
        ])

        migracion._inicializar_participantes(collection)
        primera_pasada = [documento["bloqueado"] for documento in collection.documentos]
        migracion._inicializar_participantes(collection)

        self.assertEqual(primera_pasada, [False, True, False, True, True, False])
        self.assertEqual(
            [documento["bloqueado"] for documento in collection.documentos],
            primera_pasada,
        )
