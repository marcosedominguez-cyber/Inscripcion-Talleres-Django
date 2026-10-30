"""Pruebas de los mensajes legibles de auditoría del Django Admin."""

import json
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from django.test import SimpleTestCase

from talleres.admin import TallerAdmin, UsuarioAdmin
from talleres.admin_site import admin_site
from talleres.models import Taller, Usuario


class FormularioFalso:
    def __init__(self, modelo, initial, cleaned_data, changed_data):
        self._meta = SimpleNamespace(model=modelo)
        self.initial = initial
        self.cleaned_data = cleaned_data
        self.changed_data = changed_data
        self.fields = {}


class ConsultaFiltradaFalsa:
    def __init__(self, propietario, resultado):
        self.propietario = propietario
        self.resultado = resultado

    def update(self, **cambios):
        self.propietario.actualizaciones.append(cambios)
        return self.resultado


class QuerysetFalso:
    def __init__(self, objetos, resultados=None):
        self.objetos = list(objetos)
        self.resultados = list(
            resultados if resultados is not None else [1] * len(self.objetos)
        )
        self.filtros = []
        self.actualizaciones = []

    def __iter__(self):
        return iter(self.objetos)

    def filter(self, *args, **kwargs):
        self.filtros.append((args, kwargs))
        resultado = self.resultados.pop(0) if self.resultados else 0
        return ConsultaFiltradaFalsa(self, resultado)


def crear_taller(estado=Taller.Aprobacion.PENDIENTE):
    return SimpleNamespace(
        pk=ObjectId(),
        codigo="T-001",
        nombre="Taller de prueba",
        estado_aprobacion=estado,
    )


class AuditoriaFormulariosTests(SimpleTestCase):
    def setUp(self):
        self.admin = TallerAdmin(Taller, admin_site)


    def test_campos_sensibles_no_exponen_sus_valores(self):
        admin = UsuarioAdmin(Usuario, admin_site)
        formulario = FormularioFalso(
            Usuario,
            {"ci": "123456", "cuenta": "cuenta-anterior"},
            {"ci": "654321", "cuenta": "cuenta-nueva"},
            ["ci", "cuenta"],
        )

        mensaje = admin.construct_change_message(None, formulario, None)
        resumenes = mensaje[0]["changed"]["fields"]
        serializado = json.dumps(mensaje, ensure_ascii=False)

        self.assertEqual(
            resumenes,
            [
                "Ci: valor sensible modificado",
                "Cuenta: valor sensible modificado",
            ],
        )
        self.assertNotIn("123456", serializado)
        self.assertNotIn("654321", serializado)
        self.assertNotIn("cuenta-anterior", serializado)
        self.assertNotIn("cuenta-nueva", serializado)

    def test_varios_campos_y_tipos_se_resumen_por_separado(self):
        instructor_anterior = ObjectId()
        instructor_nuevo = Usuario(
            pk=ObjectId(), nombre="Nuevo instructor", ci="456",
            rol=Usuario.Rol.INSTRUCTOR,
        )
        fecha_anterior = datetime(2030, 10, 15, 10, 0, tzinfo=dt_timezone.utc)
        fecha_nueva = datetime(2030, 10, 16, 10, 0, tzinfo=dt_timezone.utc)
        formulario = FormularioFalso(
            Taller,
            {
                "cupos": 10,
                "descripcion": None,
                "fecha_inicio": fecha_anterior,
                "instructor": instructor_anterior,
                "estado_aprobacion": Taller.Aprobacion.PENDIENTE,
            },
            {
                "cupos": 12,
                "descripcion": "Nueva descripción",
                "fecha_inicio": fecha_nueva,
                "instructor": instructor_nuevo,
                "estado_aprobacion": Taller.Aprobacion.APROBADO,
            },
            [
                "cupos", "descripcion", "fecha_inicio", "instructor",
                "estado_aprobacion",
            ],
        )

        mensaje = self.admin.construct_change_message(None, formulario, None)
        resumenes = mensaje[0]["changed"]["fields"]

        self.assertIn("Cupos: 10 → 12", resumenes)
        self.assertIn("Descripcion: vacío → Nueva descripción", resumenes)
        self.assertIn(
            f"Instructor: {instructor_anterior} → {instructor_nuevo.pk}",
            resumenes,
        )
        self.assertIn(
            "Estado de aprobación: pendiente → aprobado",
            resumenes,
        )
        self.assertIn(
            "Fecha inicio: 15/10/2030 06:00 → 16/10/2030 06:00",
            resumenes,
        )
        self.assertEqual(len(resumenes), 5)


class NotificacionesAdminTests(SimpleTestCase):
    def test_editar_desde_admin_utiliza_servicio_sin_reenviar_revision(self):
        from types import SimpleNamespace
        modelo_admin = TallerAdmin(Taller, admin_site)
        taller = crear_taller()
        formulario = SimpleNamespace(changed_data=["nombre"])
        taller.nombre = "Nuevo título"
        anterior = crear_taller()
        with patch.object(Taller, "objects") as gestor, \
             patch("talleres.admin.actualizar_taller") as actualizar:
            gestor.get.return_value = anterior
            modelo_admin.save_model(None, taller, formulario, True)
        actualizar.assert_called_once_with(anterior, {"nombre": "Nuevo título"}, reenviar_revision=False)

    def test_aprobacion_masiva_notifica_solo_el_cambio_real(self):
        from contextlib import nullcontext
        modelo_admin = TallerAdmin(Taller, admin_site)
        pendiente = crear_taller()
        aprobado = crear_taller(Taller.Aprobacion.APROBADO)
        queryset = QuerysetFalso([pendiente, aprobado], [1])
        with patch.object(Taller, "objects", queryset), \
             patch("talleres.servicios.atomic", return_value=nullcontext()), \
             patch("talleres.admin._notificar_edicion_taller") as enviar, \
             patch.object(modelo_admin, "log_change"), \
             patch.object(modelo_admin, "message_user"):
            modelo_admin.aprobar_seleccionados(None, queryset)
        enviar.assert_called_once_with(pendiente, {"estado_aprobacion": ("pendiente", "aprobado")})
