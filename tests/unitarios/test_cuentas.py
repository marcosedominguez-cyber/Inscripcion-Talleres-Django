"""Dos comprobaciones concretas por función; no consultan Atlas."""
import json
from types import SimpleNamespace
from unittest.mock import patch


import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
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


def test_login_rechaza_contrasena_incorrecta(cuenta_simulada):
    assert CIBackend().authenticate(None, ci="12345678", password="otra") is None
    factory = RequestFactory()
    for rol in (Usuario.Rol.PARTICIPANTE, Usuario.Rol.INSTRUCTOR):
        for seleccionado in (Usuario.Rol.PARTICIPANTE, Usuario.Rol.INSTRUCTOR, "administrador", None):
            datos = {"ci": "12345678", "contrasena": "Talleres!seguro.742"}
            if seleccionado is not None:
                datos["rol"] = seleccionado
            request = factory.post("/api/cuentas/login/", datos, content_type="application/json")
            with patch.object(vistas, "authenticate", return_value=cuenta_simulada), \
                 patch.object(vistas, "perfil_json", return_value={"rol": rol}), \
                 patch.object(vistas, "login") as abrir:
                respuesta = vistas.ingresar(request)
            if seleccionado == rol:
                assert respuesta.status_code == 200
                abrir.assert_called_once_with(request, cuenta_simulada)
            else:
                assert respuesta.status_code == (403 if seleccionado in ("participante", "instructor") else 400)
                abrir.assert_not_called()
