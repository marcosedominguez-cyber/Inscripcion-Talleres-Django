"""Dos comprobaciones concretas por función; no consultan Atlas."""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.test import RequestFactory, SimpleTestCase
from cuentas.backends import CIBackend
from cuentas.forms import RegistroForm
from cuentas import vistas
from talleres.models import Usuario


class RegistroPublicoK1Tests(SimpleTestCase):
    def test_registro_rechaza_banderas_de_staff_o_superusuario_antes_de_persistir(self):
        request = RequestFactory().post(
            "/api/cuentas/registro/",
            data=json.dumps({
                "nombre_usuario": "intento", "ci": "12345", "rol": "instructor",
                "contrasena": "una-clave", "confirmar_contrasena": "una-clave",
                "is_staff": "true",
            }),
            content_type="application/json",
        )
        request.user = AnonymousUser()
        with patch.object(vistas, "registrar_cuenta") as registrar:
            response = vistas.registro(request)
        self.assertEqual(response.status_code, 400)
        registrar.assert_not_called()


def test_registro_admite_un_instructor_valido():
    datos = {"nombre_usuario": "instructor_demo", "ci": "12345678", "rol": "instructor",
             "contrasena": "Talleres!seguro.742", "confirmar_contrasena": "Talleres!seguro.742"}
    with patch.object(get_user_model().objects, "filter") as cuentas, patch.object(Usuario.objects, "filter") as perfiles:
        cuentas.return_value.exists.return_value = False
        perfiles.return_value.exists.return_value = False
        assert RegistroForm(datos).is_valid()


def test_registro_rechaza_el_rol_administrador():
    datos = {"nombre_usuario": "intruso", "ci": "12345678", "rol": "administrador",
             "contrasena": "Talleres!seguro.742", "confirmar_contrasena": "Talleres!seguro.742"}
    with patch.object(get_user_model().objects, "filter") as cuentas, patch.object(Usuario.objects, "filter") as perfiles:
        cuentas.return_value.exists.return_value = False
        perfiles.return_value.exists.return_value = False
        form = RegistroForm(datos)
        assert not form.is_valid()
        assert "rol" in form.errors


def test_registro_rechaza_una_ci_ya_asociada_a_un_perfil():
    datos = {"nombre_usuario": "otro", "ci": "12345678", "rol": "participante",
             "contrasena": "Talleres!seguro.742", "confirmar_contrasena": "Talleres!seguro.742"}
    perfiles = SimpleNamespace(objects=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: True)))
    with patch("cuentas.forms.RegistroForm.clean_nombre_usuario", return_value="otro"), \
         patch("cuentas.forms.Usuario", perfiles):
        form = RegistroForm(datos)
        assert not form.is_valid()
        assert "ci" in form.errors


@pytest.fixture
def cuenta_simulada():
    cuenta = get_user_model()(username="ana", is_active=True)
    cuenta.set_password("Talleres!seguro.742")
    perfil = SimpleNamespace(cuenta=cuenta, cuenta_id="identificador")
    with patch.object(Usuario.objects, "select_related") as consulta:
        consulta.return_value.get.return_value = perfil
        yield cuenta


def test_login_admite_ci_y_contrasena_correctas(cuenta_simulada):
    assert CIBackend().authenticate(None, ci="12345678", password="Talleres!seguro.742") is cuenta_simulada


def test_login_rechaza_contrasena_incorrecta(cuenta_simulada):
    assert CIBackend().authenticate(None, ci="12345678", password="otra") is None


def test_sesion_anonima_no_devuelve_usuario():
    request = RequestFactory().get("/api/cuentas/sesion/")
    request.user = AnonymousUser()
    assert json.loads(vistas.sesion(request).content)["usuario"] is None


def test_sesion_autenticada_devuelve_el_perfil():
    request = RequestFactory().get("/api/cuentas/sesion/")
    perfil = SimpleNamespace(pk="perfil", ci="12345678", rol="participante", get_rol_display=lambda: "Participante")
    request.user = SimpleNamespace(is_authenticated=True, is_active=True, username="ana", perfil=perfil)
    assert json.loads(vistas.sesion(request).content)["usuario"]["nombre_usuario"] == "ana"


def test_sesion_inactiva_no_devuelve_el_perfil():
    request = RequestFactory().get("/api/cuentas/sesion/")
    request.user = SimpleNamespace(is_authenticated=True, is_active=False)
    response = vistas.sesion(request)
    assert response.status_code == 403


def test_logout_vacia_la_sesion():
    request = RequestFactory().post("/api/cuentas/logout/")
    request.user = AnonymousUser()
    request.session = SessionStore()
    request.session["marca"] = "sesion_anterior"
    assert vistas.salir(request).status_code == 200
    assert "marca" not in request.session


def test_logout_no_admite_get():
    request = RequestFactory().get("/api/cuentas/logout/")
    assert vistas.salir(request).status_code == 405
