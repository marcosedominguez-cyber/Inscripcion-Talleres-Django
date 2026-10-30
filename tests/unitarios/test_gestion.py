"""Pruebas unitarias de K1: no crean modelos ni acceden a una base de datos."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.contrib.auth.models import AnonymousUser
import pytest

from django.test import RequestFactory, SimpleTestCase

from talleres import api_gestion
from talleres.admin_site import admin_site
from talleres.models import Inscripcion, Taller, Usuario


class GestionInstructorTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.instructor = SimpleNamespace(pk="instructor-id", rol=Usuario.Rol.INSTRUCTOR)
        self.user = SimpleNamespace(is_authenticated=True, is_active=True, perfil=self.instructor)
        self.datos = {
            "nombre": "Taller de prueba",
            "descripcion": "Descripción",
            "cupos": 4,
            "fecha_inicio": "2030-10-15T10:00",
            "fecha_fin": "2030-10-16T10:00",
        }

    def solicitud(self, method, path, datos=None, user=None):
        request = getattr(self.factory, method.lower())(
            path,
            data=json.dumps(datos) if datos is not None else None,
            content_type="application/json" if datos is not None else None,
        )
        request.user = self.user if user is None else user
        return request


    def test_payload_no_puede_asignar_propietario_ni_estado(self):
        request = self.solicitud("post", "/api/gestion/talleres/", {
            **self.datos, "instructor_id": "otro", "estado_aprobacion": "aprobado",
        })
        with patch.object(api_gestion, "proponer_taller") as crear:
            response = api_gestion.talleres_instructor(request)
        self.assertEqual(response.status_code, 400)
        crear.assert_not_called()


    def test_detalle_y_edicion_de_taller_ajeno_devuelven_404(self):
        manager = Mock()
        manager.filter.return_value.first.return_value = None
        with patch.object(Taller, "objects", manager):
            get_response = api_gestion.taller_instructor(
                self.solicitud("get", "/api/gestion/talleres/T-AJENO/"), "T-AJENO"
            )
            patch_response = api_gestion.taller_instructor(
                self.solicitud("patch", "/api/gestion/talleres/T-AJENO/", {"nombre": "Cambio"}),
                "T-AJENO",
            )
        self.assertEqual(get_response.status_code, 404)
        self.assertEqual(patch_response.status_code, 404)
        self.assertEqual(manager.filter.call_args_list, [
            call(instructor=self.instructor, codigo="T-AJENO"),
            call(instructor=self.instructor, codigo="T-AJENO"),
        ])


    def test_anónimo_y_rol_incorrecto_no_acceden(self):
        anonymous = self.solicitud("get", "/api/gestion/talleres/", user=AnonymousUser())
        response = api_gestion.talleres_instructor(anonymous)
        self.assertEqual(response.status_code, 401)
        participante = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE),
        )
        response = api_gestion.talleres_instructor(
            self.solicitud("get", "/api/gestion/talleres/", user=participante)
        )
        self.assertEqual(response.status_code, 403)
        inactivo = SimpleNamespace(
            is_authenticated=True, is_active=False, perfil=self.instructor,
        )
        response = api_gestion.talleres_instructor(
            self.solicitud("get", "/api/gestion/talleres/", user=inactivo)
        )
        self.assertEqual(response.status_code, 403)


@pytest.mark.parametrize("cambio", [
    {"cupos": 3}, {"cupos": 41},
    {"fecha_fin": "2030-10-15T11:00"}, {"fecha_fin": "2030-10-23T10:00"},
], ids=["cupo-minimo", "cupo-maximo", "duracion-minima", "duracion-maxima"])
def test_gestion_rechaza_cupo_y_duracion_fuera_de_rango(cambio):
    datos = {"nombre": "Prueba", "descripcion": "", "cupos": 4,
             "fecha_inicio": "2030-10-15T10:00", "fecha_fin": "2030-10-16T10:00", **cambio}
    request = RequestFactory().post("/api/gestion/talleres/", datos, content_type="application/json")
    request.user = SimpleNamespace(is_authenticated=True, is_active=True,
                                  perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR))
    with patch.object(api_gestion, "proponer_taller") as crear:
        assert api_gestion.talleres_instructor(request).status_code == 400
    crear.assert_not_called()


@pytest.mark.parametrize("modelo", [Usuario, Taller, Inscripcion], ids=["usuario", "taller", "inscripcion"])
@pytest.mark.parametrize("metodo", ["get", "post"])
def test_admin_rechaza_borrado_directo_sin_alterar_datos(modelo, metodo):
    from django.core.exceptions import PermissionDenied
    administrador = admin_site._registry[modelo]
    request = getattr(RequestFactory(), metodo)("/admin/talleres/objeto/1/delete/")
    request.user = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True,
        perfil=SimpleNamespace(rol=Usuario.Rol.ADMINISTRADOR))
    objeto = Mock()
    with patch.object(administrador, "get_object", return_value=objeto), \
         patch.object(administrador, "delete_model") as borrar:
        with pytest.raises(PermissionDenied):
            administrador._delete_view(request, "1", None)
    borrar.assert_not_called()
    objeto.delete.assert_not_called()
