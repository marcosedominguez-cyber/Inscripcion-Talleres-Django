"""Clasificación de la pirámide y datos sintéticos compartidos."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from cuentas.servicios import registrar_cuenta
from talleres import servicios
from talleres.models import Taller, Usuario


def pytest_collection_modifyitems(items):
    for item in items:
        partes = item.path.parts
        grupo = next((g for g in ("unitarios", "integracion", "e2e") if g in partes), None)
        if grupo:
            item.add_marker(getattr(pytest.mark, grupo))
        if grupo in ("integracion", "e2e") and settings.SETTINGS_MODULE != "config.settings_test_mongodb":
            item.add_marker(pytest.mark.skip(reason="Requiere la suite completa y MongoDB de pruebas."))


@pytest.fixture
def fabrica(transactional_db):
    numero = 0
    inicio = (timezone.now() + timedelta(days=10)).replace(microsecond=0)
    clave = "Talleres!seguro.742"

    def persona(*, cuenta=False, rol=Usuario.Rol.PARTICIPANTE):
        nonlocal numero
        numero += 1
        ci = str(80000000 + numero)
        if cuenta:
            return registrar_cuenta(nombre_usuario=f"persona_{numero}", ci=ci, contrasena=clave, rol=rol)
        return servicios.registrar_participante(f"Persona {numero}", ci)

    def taller(nombre="Taller de prueba", *, fecha=None, cupos=5, instructor=None, aprobado=True):
        fecha = fecha or inicio
        t = servicios.registrar_taller(nombre, cupos, fecha, fecha + timedelta(days=2), instructor=instructor)
        if aprobado:
            Taller.objects.filter(pk=t.pk).update(estado_aprobacion=Taller.Aprobacion.APROBADO)
            t.refresh_from_db()
        return t

    def administrador():
        cuenta = get_user_model().objects.create_superuser("administracion", password=clave)
        Usuario.objects.create(cuenta=cuenta, ci="99999999", nombre="Administración", rol=Usuario.Rol.ADMINISTRADOR)
        return cuenta

    def cliente(perfil):
        c = Client(enforce_csrf_checks=True)
        token = c.get("/api/cuentas/sesion/").json()["csrfToken"]
        respuesta = c.post("/api/cuentas/login/", {"ci": perfil.ci, "contrasena": clave, "rol": perfil.rol},
                           content_type="application/json", HTTP_X_CSRFTOKEN=token)
        assert respuesta.status_code == 200, respuesta.content
        c.defaults["HTTP_X_CSRFTOKEN"] = respuesta.json()["csrfToken"]
        return c

    return SimpleNamespace(inicio=inicio, clave=clave, persona=persona, taller=taller,
                           administrador=administrador, cliente=cliente)
