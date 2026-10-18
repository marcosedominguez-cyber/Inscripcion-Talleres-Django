"""Pruebas unitarias de K1: no crean modelos ni acceden a una base de datos."""

import json
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from cuentas import views as cuentas_views
from talleres import api_gestion
from talleres import services as taller_services
from talleres.admin import TallerAdmin
from talleres.admin_site import admin_site
from talleres.api_participantes import catalogo_talleres_api
from talleres.consultas_participantes import listar_talleres_proximos
from talleres.models import Inscripcion, Taller, Usuario


class GestionInstructorTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.instructor = SimpleNamespace(pk="instructor-id", rol=Usuario.Rol.INSTRUCTOR)
        self.user = SimpleNamespace(is_authenticated=True, perfil=self.instructor)
        self.datos = {
            "nombre": "Taller de prueba",
            "descripcion": "Descripción",
            "cupos": 3,
            "fecha_inicio": "2030-10-15T10:00",
            "fecha_fin": "2030-10-15T12:00",
        }

    def solicitud(self, method, path, datos=None, user=None):
        request = getattr(self.factory, method.lower())(
            path,
            data=json.dumps(datos) if datos is not None else None,
            content_type="application/json" if datos is not None else None,
        )
        request.user = self.user if user is None else user
        return request

    def test_creacion_deriva_propietario_de_sesion_y_fija_pendiente(self):
        request = self.solicitud("post", "/api/gestion/talleres/", self.datos)
        taller = SimpleNamespace(codigo="T-321")
        with patch.object(api_gestion, "proponer_taller", return_value=taller) as crear, \
             patch.object(api_gestion, "_serializar", return_value={"codigo": "T-321"}):
            response = api_gestion.talleres_instructor(request)
        self.assertEqual(response.status_code, 201)
        kwargs = crear.call_args.kwargs
        self.assertIs(kwargs["instructor"], self.instructor)
        self.assertEqual(kwargs["cupos"], 3)
        self.assertNotIn("instructor_id", kwargs)

    def test_payload_no_puede_asignar_propietario_ni_estado(self):
        request = self.solicitud("post", "/api/gestion/talleres/", {
            **self.datos, "instructor_id": "otro", "estado_aprobacion": "aprobado",
        })
        with patch.object(api_gestion, "proponer_taller") as crear:
            response = api_gestion.talleres_instructor(request)
        self.assertEqual(response.status_code, 400)
        crear.assert_not_called()

    def test_listado_filtra_por_perfil_y_calcula_datos_por_taller(self):
        taller = SimpleNamespace(codigo="T-001")
        manager = Mock()
        manager.filter.return_value = [taller]
        with patch.object(Taller, "objects", manager), \
             patch.object(api_gestion, "_serializar", return_value={"codigo": "T-001"}):
            response = api_gestion.talleres_instructor(
                self.solicitud("get", "/api/gestion/talleres/")
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["talleres"], [{"codigo": "T-001"}])
        manager.filter.assert_called_once_with(instructor=self.instructor)

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

    def test_edicion_propia_revalida_y_reenvia_a_aprobacion(self):
        taller = SimpleNamespace(
            codigo="T-OWN", nombre="Anterior", descripcion="", cupos=3,
            fecha_inicio=datetime(2030, 10, 15, 10, tzinfo=dt_timezone.utc),
            fecha_fin=datetime(2030, 10, 15, 12, tzinfo=dt_timezone.utc),
            estado_aprobacion=Taller.Aprobacion.APROBADO,
            full_clean=Mock(), save=Mock(),
        )
        manager = Mock()
        manager.filter.return_value.first.return_value = taller
        request = self.solicitud("patch", "/api/gestion/talleres/T-OWN/", {"nombre": "Nuevo"})
        with patch.object(Taller, "objects", manager), \
             patch.object(api_gestion, "_serializar", return_value={"codigo": "T-OWN"}):
            response = api_gestion.taller_instructor(request, "T-OWN")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(taller.nombre, "Nuevo")
        self.assertEqual(taller.estado_aprobacion, Taller.Aprobacion.PENDIENTE)
        taller.full_clean.assert_called_once_with()
        taller.save.assert_called_once_with()

    def test_anónimo_y_rol_incorrecto_no_acceden(self):
        anonymous = self.solicitud("get", "/api/gestion/talleres/", user=AnonymousUser())
        response = api_gestion.talleres_instructor(anonymous)
        self.assertEqual(response.status_code, 401)
        participante = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE),
        )
        response = api_gestion.talleres_instructor(
            self.solicitud("get", "/api/gestion/talleres/", user=participante)
        )
        self.assertEqual(response.status_code, 403)

    def test_datos_incompletos_o_con_fecha_invertida_se_rechazan(self):
        incompleto = self.solicitud("post", "/api/gestion/talleres/", {"nombre": "x"})
        invertido = self.solicitud("post", "/api/gestion/talleres/", {
            **self.datos, "fecha_inicio": "2030-10-16T10:00",
        })
        with patch.object(api_gestion, "proponer_taller") as crear:
            self.assertEqual(api_gestion.talleres_instructor(incompleto).status_code, 400)
            self.assertEqual(api_gestion.talleres_instructor(invertido).status_code, 400)
        crear.assert_not_called()

    def test_csrf_middleware_rechaza_post_sin_token(self):
        request = self.factory.post(
            "/api/gestion/talleres/", data=json.dumps(self.datos),
            content_type="application/json",
        )
        request.user = self.user
        middleware = CsrfViewMiddleware(lambda req: None)
        middleware.process_request(request)
        response = middleware.process_view(
            request, api_gestion.talleres_instructor, (), {}
        )
        self.assertEqual(response.status_code, 403)


class AprobacionYCatalogoTests(SimpleTestCase):
    def test_servicio_asigna_pendiente_a_toda_alta_sin_publicacion_automatica(self):
        instructor = SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR)
        modelo = Mock()
        modelo.Aprobacion = Taller.Aprobacion
        instancia = Mock()
        modelo.return_value = instancia
        with patch.object(taller_services, "Taller", modelo), \
             patch.object(taller_services, "_preparar_contador"), \
             patch.object(taller_services, "_crear_taller", return_value="guardado"):
            propuesta = taller_services.proponer_taller(
                instructor, "Propuesta", 2,
                datetime(2030, 10, 15, 10), datetime(2030, 10, 15, 12),
            )
            self.assertEqual(propuesta, "guardado")
            self.assertEqual(
                modelo.call_args.kwargs["estado_aprobacion"],
                Taller.Aprobacion.PENDIENTE,
            )
            modelo.reset_mock()
            taller_services.registrar_taller(
                "CLI", 2, datetime(2030, 10, 15, 10), datetime(2030, 10, 15, 12)
            )
            self.assertEqual(
                modelo.call_args.kwargs["estado_aprobacion"],
                Taller.Aprobacion.PENDIENTE,
            )

    def test_servicio_de_propuesta_rechaza_perfil_no_instructor(self):
        participante = SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE)
        with patch.object(taller_services, "registrar_taller") as registrar:
            with self.assertRaises(ValidationError):
                taller_services.proponer_taller(
                    participante, "Inválido", 1,
                    datetime(2030, 10, 15, 10), datetime(2030, 10, 15, 12),
                )
        registrar.assert_not_called()

    def test_catalogo_consulta_solo_aprobados_futuros_y_con_cupo(self):
        aprobado = SimpleNamespace(codigo="T-OK")
        manager = Mock()
        manager.filter.return_value = [aprobado, SimpleNamespace(codigo="T-FULL")]
        with patch.object(Taller, "objects", manager), \
             patch("talleres.consultas_participantes.cupos_disponibles", side_effect=[2, 0]):
            resultado = listar_talleres_proximos()
        self.assertEqual(resultado, [aprobado])
        filtros = manager.filter.call_args.kwargs
        self.assertEqual(filtros["estado_aprobacion"], Taller.Aprobacion.APROBADO)
        self.assertIn("fecha_inicio__gt", filtros)

    def test_catalogo_api_rechaza_anónimo_y_rol_incorrecto(self):
        factory = RequestFactory()
        anonymous = factory.get("/api/participantes/talleres/")
        anonymous.user = AnonymousUser()
        self.assertEqual(catalogo_talleres_api(anonymous).status_code, 401)
        instructor = factory.get("/api/participantes/talleres/")
        instructor.user = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR),
        )
        self.assertEqual(catalogo_talleres_api(instructor).status_code, 403)

    def test_catalogo_participante_solo_serializa_resultados_de_consulta(self):
        factory = RequestFactory()
        participante = factory.get("/api/participantes/talleres/")
        participante.user = SimpleNamespace(
            is_authenticated=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE),
            get_full_name=lambda: "",
            get_username=lambda: "persona",
        )
        taller = SimpleNamespace(
            codigo="T-OK", nombre="Aprobado", descripcion="", cupos=2,
            fecha_inicio="2030-10-15T10:00Z", fecha_fin="2030-10-15T12:00Z",
        )
        with patch("talleres.api_participantes.listar_talleres_proximos", return_value=[taller]), \
             patch("talleres.api_participantes.cupos_disponibles", return_value=1):
            response = catalogo_talleres_api(participante)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["talleres"][0]["codigo"], "T-OK")

    def test_django_admin_exige_staff_activo_y_rol_administrador(self):
        factory = RequestFactory()
        for active, staff, role, esperado in [
            (True, True, Usuario.Rol.ADMINISTRADOR, True),
            (True, False, Usuario.Rol.ADMINISTRADOR, False),
            (True, True, Usuario.Rol.INSTRUCTOR, False),
            (False, True, Usuario.Rol.ADMINISTRADOR, False),
        ]:
            request = factory.get("/admin/")
            request.user = SimpleNamespace(
                is_active=active, is_staff=staff,
                perfil=SimpleNamespace(rol=role),
            )
            self.assertEqual(admin_site.has_permission(request), esperado)

    def test_solo_propuestas_pendientes_se_aprueban_o_rechazan(self):
        admin = TallerAdmin(Taller, admin_site)
        queryset = Mock()
        pendientes = Mock()
        queryset.filter.return_value = pendientes
        request = SimpleNamespace()
        with patch.object(admin, "message_user"):
            admin.aprobar_seleccionados(request, queryset)
            queryset.filter.assert_called_once()
            pendientes.update.assert_called_once_with(
                estado_aprobacion=Taller.Aprobacion.APROBADO
            )
            queryset.filter.reset_mock()
            pendientes.update.reset_mock()
            admin.rechazar_seleccionados(request, queryset)
        pendientes.update.assert_called_once_with(
            estado_aprobacion=Taller.Aprobacion.RECHAZADO
        )


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
        with patch.object(cuentas_views, "registrar_cuenta") as registrar:
            response = cuentas_views.registro(request)
        self.assertEqual(response.status_code, 400)
        registrar.assert_not_called()

    def test_formulario_publico_no_ofrece_rol_administrador(self):
        from cuentas.forms import RegistroForm

        valores = {valor for valor, _ in RegistroForm.base_fields["rol"].choices}
        self.assertNotIn(Usuario.Rol.ADMINISTRADOR, valores)
