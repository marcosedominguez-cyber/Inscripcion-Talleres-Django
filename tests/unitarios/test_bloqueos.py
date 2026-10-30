"""Pruebas aisladas del bloqueo manual, la rehabilitación y su historial."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bson import ObjectId
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase

from talleres import servicios
from talleres.admin import UsuarioAdmin
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


class ServicioBloqueoTests(SimpleTestCase):
    def ejecutar_bloqueo(self, participante, motivo, admin):
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = None
        creado = SimpleNamespace(pk=ObjectId(), motivo=motivo)
        bloqueos.create.return_value = creado
        usuarios = Mock()
        with (
            patch.object(servicios, "_notificar"),
            patch.object(servicios, "_cancelar_inscripciones_por_bloqueo"),
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects", usuarios),
        ):
            resultado = servicios.bloquear_participante(
                participante, motivo, administrador=admin,
            )
        return resultado, bloqueos, usuarios


    def test_motivo_debe_ser_manual_cuando_lo_ejecuta_un_administrador(self):
        with self.assertRaises(servicios.MotivoBloqueoInvalidoError):
            servicios.bloquear_participante(
                participante(),
                Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS,
                administrador=administrador(),
            )


    def test_rehabilitacion_manual_no_borra_un_contador_inferior_al_limite(self):
        persona = participante(bloqueado=True, cancelaciones_consecutivas=1)
        abierto = SimpleNamespace(save=Mock())
        bloqueos = Mock()
        bloqueos.filter.return_value.order_by.return_value.first.return_value = abierto
        usuarios = Mock()
        with (
            patch.object(servicios, "_notificar"),
            patch.object(servicios, "atomic", return_value=nullcontext()),
            patch.object(servicios.Bloqueo, "objects", bloqueos),
            patch.object(servicios.Usuario, "objects", usuarios),
        ):
            servicios.rehabilitar_participante(persona, administrador())
        usuarios.filter.return_value.update.assert_called_once_with(bloqueado=False)
        self.assertEqual(persona.cancelaciones_consecutivas, 1)


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


    def test_usuario_no_autorizado_no_puede_bloquear_ni_rehabilitar(self):
        request = self.solicitud({}, user=AnonymousUser())
        with patch("talleres.admin.bloquear_participante") as bloquear, \
             patch("talleres.admin.rehabilitar_participante") as rehabilitar, \
             patch.object(self.admin, "message_user"):
            self.admin.bloquear_participantes(request, [self.persona])
            self.admin.rehabilitar_participantes(request, [self.persona])
        bloquear.assert_not_called()
        rehabilitar.assert_not_called()
