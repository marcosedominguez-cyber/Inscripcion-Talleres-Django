"""Pruebas unitarias de K1: no crean modelos ni acceden a una base de datos."""

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from talleres import api_gestion
from talleres import servicios as taller_services
from talleres.admin import TallerAdmin
from talleres.admin_site import admin_site
from talleres.api_participantes import catalogo_talleres_api
from talleres.consultas import listar_talleres_proximos
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

    def test_creacion_deriva_propietario_de_sesion_y_fija_pendiente(self):
        request = self.solicitud("post", "/api/gestion/talleres/", self.datos)
        taller = SimpleNamespace(codigo="T-321")
        with patch.object(api_gestion, "proponer_taller", return_value=taller) as crear, \
             patch.object(api_gestion, "_serializar", return_value={"codigo": "T-321"}):
            response = api_gestion.talleres_instructor(request)
        self.assertEqual(response.status_code, 201)
        kwargs = crear.call_args.kwargs
        self.assertIs(kwargs["instructor"], self.instructor)
        self.assertEqual(kwargs["cupos"], 4)
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
            pk="taller-id", codigo="T-OWN", nombre="Anterior", descripcion="", cupos=4,
            fecha_inicio=datetime(2030, 10, 15, 10, tzinfo=dt_timezone.utc),
            fecha_fin=datetime(2030, 10, 16, 10, tzinfo=dt_timezone.utc),
            estado_aprobacion=Taller.Aprobacion.APROBADO,
            full_clean=Mock(), save=Mock(),
        )
        manager = Mock()
        manager.filter.return_value.first.return_value = taller
        inscripciones = Mock()
        inscripciones.filter.return_value.order_by.return_value = []
        inscripciones.filter.return_value.values_list.return_value = ["inscripcion-1"]
        request = self.solicitud("patch", "/api/gestion/talleres/T-OWN/", {"nombre": "Nuevo"})
        with patch.object(Taller, "objects", manager), \
             patch.object(taller_services.Inscripcion, "objects", inscripciones), \
             patch("talleres.servicios._notificar_edicion_taller"), \
             patch("talleres.servicios.atomic", return_value=nullcontext()), \
             patch.object(api_gestion, "_serializar", return_value={"codigo": "T-OWN"}):
            response = api_gestion.taller_instructor(request, "T-OWN")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(taller.nombre, "Nuevo")
        self.assertEqual(taller.estado_aprobacion, Taller.Aprobacion.PENDIENTE)
        taller.full_clean.assert_called_once_with()
        taller.save.assert_called_once_with()

    def test_edicion_rechaza_cupo_menor_a_las_inscripciones_confirmadas(self):
        taller = SimpleNamespace(
            pk="taller-id", codigo="T-OWN", nombre="Anterior", descripcion="", cupos=4,
            fecha_inicio=datetime(2030, 10, 15, 10, tzinfo=dt_timezone.utc),
            fecha_fin=datetime(2030, 10, 16, 10, tzinfo=dt_timezone.utc),
            estado_aprobacion=Taller.Aprobacion.APROBADO,
            full_clean=Mock(), save=Mock(),
        )
        manager = Mock()
        manager.filter.return_value.first.return_value = taller
        inscripciones = Mock()
        inscripciones.filter.return_value.order_by.return_value = []
        inscripciones.filter.return_value.values_list.return_value = [
            "i-1", "i-2", "i-3", "i-4", "i-5",
        ]
        request = self.solicitud(
            "patch", "/api/gestion/talleres/T-OWN/", {"cupos": 4}
        )
        with patch.object(Taller, "objects", manager), \
             patch.object(taller_services.Inscripcion, "objects", inscripciones), \
             patch("talleres.servicios.atomic", return_value=nullcontext()):
            response = api_gestion.taller_instructor(request, "T-OWN")
        self.assertEqual(response.status_code, 400)
        self.assertIn("cupos", json.loads(response.content)["errores"])
        taller.save.assert_not_called()

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

    def test_datos_incompletos_o_con_fecha_invertida_se_rechazan(self):
        incompleto = self.solicitud("post", "/api/gestion/talleres/", {"nombre": "x"})
        invertido = self.solicitud("post", "/api/gestion/talleres/", {
            **self.datos, "fecha_inicio": "2030-10-16T10:00",
        })
        with patch.object(api_gestion, "proponer_taller") as crear:
            self.assertEqual(api_gestion.talleres_instructor(incompleto).status_code, 400)
            self.assertEqual(api_gestion.talleres_instructor(invertido).status_code, 400)
        crear.assert_not_called()

    def test_cupo_y_duracion_fuera_de_rango_se_rechazan(self):
        casos = (
            {"cupos": 3},
            {"cupos": 41},
            {"fecha_fin": "2030-10-15T11:00"},
            {"fecha_fin": "2030-10-23T10:00"},
        )
        with patch.object(api_gestion, "proponer_taller") as crear:
            for cambio in casos:
                with self.subTest(cambio=cambio):
                    request = self.solicitud(
                        "post", "/api/gestion/talleres/", {**self.datos, **cambio}
                    )
                    self.assertEqual(
                        api_gestion.talleres_instructor(request).status_code, 400
                    )
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
                instructor, "Propuesta", 4,
                datetime(2030, 10, 15, 10), datetime(2030, 10, 16, 10),
            )
            self.assertEqual(propuesta, "guardado")
            self.assertEqual(
                modelo.call_args.kwargs["estado_aprobacion"],
                Taller.Aprobacion.PENDIENTE,
            )
            modelo.reset_mock()
            taller_services.registrar_taller(
                "CLI", 4, datetime(2030, 10, 15, 10), datetime(2030, 10, 16, 10)
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
                    participante, "Inválido", 4,
                    datetime(2030, 10, 15, 10), datetime(2030, 10, 16, 10),
                )
        registrar.assert_not_called()

    def test_catalogo_consulta_aprobados_futuros_y_conserva_talleres_sin_cupo(self):
        inicio = datetime(2030, 10, 15, 10, tzinfo=dt_timezone.utc)
        aprobado = SimpleNamespace(codigo="T-OK", fecha_inicio=inicio)
        manager = Mock()
        manager.filter.return_value = [
            aprobado, SimpleNamespace(codigo="T-FULL", fecha_inicio=inicio),
        ]
        with patch.object(Taller, "objects", manager), \
             patch("talleres.consultas.timezone.now", return_value=inicio - timedelta(days=1)), \
             patch("talleres.consultas.cupos_disponibles", side_effect=[2, 0]):
            resultado = listar_talleres_proximos()
        self.assertEqual([t.codigo for t in resultado], ["T-OK", "T-FULL"])
        filtros = manager.filter.call_args.kwargs
        self.assertEqual(filtros["estado_aprobacion"], Taller.Aprobacion.APROBADO)
        self.assertIn("fecha_inicio__gt", filtros)

    def test_catalogo_cierra_inscripciones_un_minuto_antes_del_inicio(self):
        inicio = datetime(2030, 10, 15, 10, tzinfo=dt_timezone.utc)
        ahora = inicio - timedelta(seconds=30)
        manager = Mock()
        manager.filter.return_value = [SimpleNamespace(fecha_inicio=inicio)]
        with patch.object(Taller, "objects", manager), \
             patch("talleres.consultas.timezone.now", return_value=ahora):
            resultado = listar_talleres_proximos()
        self.assertEqual(resultado, [])
        self.assertEqual(
            manager.filter.call_args.kwargs["fecha_inicio__gt"],
            ahora,
        )

    def test_catalogo_api_rechaza_anónimo_y_rol_incorrecto(self):
        factory = RequestFactory()
        anonymous = factory.get("/api/participantes/talleres/")
        anonymous.user = AnonymousUser()
        self.assertEqual(catalogo_talleres_api(anonymous).status_code, 401)
        instructor = factory.get("/api/participantes/talleres/")
        instructor.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.INSTRUCTOR),
        )
        self.assertEqual(catalogo_talleres_api(instructor).status_code, 403)

    def test_catalogo_participante_solo_serializa_resultados_de_consulta(self):
        factory = RequestFactory()
        participante = factory.get("/api/participantes/talleres/")
        participante.user = SimpleNamespace(
            is_authenticated=True,
            is_active=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE),
            get_full_name=lambda: "",
            get_username=lambda: "persona",
        )
        taller = SimpleNamespace(
            codigo="T-OK", nombre="Aprobado", descripcion="", cupos=2,
            fecha_inicio="2030-10-15T10:00Z", fecha_fin="2030-10-15T12:00Z",
        )
        with patch("talleres.api_participantes.listar_talleres_proximos", return_value=[taller]), \
             patch("talleres.api_participantes.cupos_disponibles", return_value=1), \
             patch("talleres.api_participantes.resumen_espera", return_value={}):
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

    def test_acciones_de_talleres_delegan_en_el_cambio_auditado(self):
        admin = TallerAdmin(Taller, admin_site)
        queryset = Mock()
        request = SimpleNamespace()
        with patch.object(admin, "_cambiar_estado_talleres") as cambiar:
            admin.aprobar_seleccionados(request, queryset)
            cambiar.assert_called_once_with(
                request, queryset, Taller.Aprobacion.APROBADO, "aprobados",
            )
            cambiar.reset_mock()
            admin.rechazar_seleccionados(request, queryset)
            cambiar.assert_called_once_with(
                request, queryset, Taller.Aprobacion.RECHAZADO, "rechazados",
            )


class ConsultaGestionEsperaTests(SimpleTestCase):
    setUp = GestionInstructorTests.setUp
    solicitud = GestionInstructorTests.solicitud

    def test_espera_no_expone_taller_ajeno(self):
        with patch.object(api_gestion, "buscar_taller_instructor", return_value=None) as buscar:
            response = api_gestion.espera_instructor(self.solicitud("get", "/"), "AJENO")
        self.assertEqual(response.status_code, 404)
        buscar.assert_called_once_with(self.instructor, "AJENO")

    def test_lista_autorizada_con_posiciones(self):
        solicitud = SimpleNamespace(participante_id="p", fecha_solicitud="2030-01-01T00:00:00Z")
        with patch.object(api_gestion, "buscar_taller_instructor", return_value="t"), \
             patch("talleres.consultas.consultar_espera", return_value=[solicitud]), \
             patch.object(Usuario, "objects") as personas:
            personas.filter.return_value = [SimpleNamespace(pk="p", nombre="Ana")]
            response = api_gestion.espera_instructor(self.solicitud("get", "/"), "T-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["solicitudes"][0]["nombre"], "Ana")

    def test_consulta_espera_exige_sesion_y_rol_instructor(self):
        for user, esperado in [(AnonymousUser(), 401),
            (SimpleNamespace(is_authenticated=True, is_active=True,
                perfil=SimpleNamespace(rol=Usuario.Rol.PARTICIPANTE)), 403)]:
            response = api_gestion.espera_instructor(self.solicitud("get", "/", user=user), "T-1")
            self.assertEqual(response.status_code, esperado)


class AdminSinEliminacionesTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.request.user = SimpleNamespace(
            is_active=True, is_staff=True, is_superuser=True,
            perfil=SimpleNamespace(rol=Usuario.Rol.ADMINISTRADOR),
        )

    def test_ni_superusuario_puede_eliminar_y_se_conserva_edicion(self):
        for modelo in (Usuario, Taller, Inscripcion):
            with self.subTest(modelo=modelo.__name__):
                administrador = admin_site._registry[modelo]
                self.assertFalse(administrador.has_delete_permission(self.request))
                self.assertFalse(administrador.has_delete_permission(self.request, modelo()))
                self.assertTrue(administrador.has_view_permission(self.request))
                self.assertEqual(administrador.has_change_permission(self.request), modelo is not Inscripcion)

    def test_acciones_masivas_excluyen_borrado_y_conservan_las_del_negocio(self):
        for modelo in (Usuario, Taller, Inscripcion):
            with self.subTest(modelo=modelo.__name__):
                acciones = admin_site._registry[modelo].get_actions(self.request)
                self.assertNotIn('delete_selected', acciones)
        self.assertIn('rehabilitar_participantes', admin_site._registry[Usuario].get_actions(self.request))
        self.assertIn('aprobar_seleccionados', admin_site._registry[Taller].get_actions(self.request))
        self.assertIn('rechazar_seleccionados', admin_site._registry[Taller].get_actions(self.request))

    def test_url_de_eliminacion_rechaza_get_y_post_sin_borrar(self):
        from django.core.exceptions import PermissionDenied
        for modelo in (Usuario, Taller, Inscripcion):
            administrador = admin_site._registry[modelo]
            for metodo in ('get', 'post'):
                with self.subTest(modelo=modelo.__name__, metodo=metodo):
                    request = getattr(RequestFactory(), metodo)('/admin/talleres/objeto/1/delete/')
                    request.user = self.request.user
                    objeto = Mock()
                    with patch.object(administrador, 'get_object', return_value=objeto), \
                         patch.object(administrador, 'delete_model') as borrar:
                        with self.assertRaises(PermissionDenied):
                            administrador._delete_view(request, '1', None)
                    borrar.assert_not_called()
                    objeto.delete.assert_not_called()
