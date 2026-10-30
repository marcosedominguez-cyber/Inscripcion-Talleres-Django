"""Pruebas de los mensajes legibles de auditoría del Django Admin."""

import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
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

    def test_campo_de_texto_registra_valor_anterior_y_nuevo(self):
        formulario = FormularioFalso(
            Taller,
            {"nombre": "Introducción a Linux"},
            {"nombre": "Linux básico"},
            ["nombre"],
        )

        mensaje = self.admin.construct_change_message(None, formulario, None)

        self.assertEqual(
            mensaje,
            [{
                "changed": {
                    "fields": ["Nombre: Introducción a Linux → Linux básico"],
                }
            }],
        )

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

    def test_fechas_se_muestran_en_formato_local_legible(self):
        anterior = datetime(
            2026, 10, 15, 7, 0, tzinfo=dt_timezone(timedelta(hours=-4)),
        )
        nuevo = datetime(
            2026, 10, 16, 5, 0, tzinfo=dt_timezone(timedelta(hours=-4)),
        )
        formulario = FormularioFalso(
            Taller,
            {"fecha_fin": anterior},
            {"fecha_fin": nuevo},
            ["fecha_fin"],
        )

        mensaje = self.admin.construct_change_message(None, formulario, None)

        self.assertEqual(
            mensaje[0]["changed"]["fields"],
            ["Fecha fin: 15/10/2026 07:00 → 16/10/2026 05:00"],
        )

    def test_log_change_serializa_unicode_sin_escapar(self):
        request = SimpleNamespace(user=SimpleNamespace(pk="admin-id"))
        objeto = crear_taller()
        mensaje = [{
            "changed": {
                "fields": ["Descripción: ó → á"],
            }
        }]

        with patch.object(
            ContentType.objects, "get_for_model",
            return_value=SimpleNamespace(id=1),
        ), patch.object(LogEntry, "save", autospec=True) as guardar:
            self.admin.log_change(request, objeto, mensaje)

        serializado = guardar.call_args.args[0].change_message
        self.assertIsInstance(serializado, str)
        self.assertIn("Descripción: ó → á", serializado)
        self.assertNotIn("\\u00f3", serializado)
        self.assertNotIn("\\u2192", serializado)
        self.assertEqual(json.loads(serializado), mensaje)
        self.assertIn(
            "Descripción: ó → á",
            LogEntry(change_message=serializado).get_change_message(),
        )

    def test_booleanos_se_muestran_como_si_o_no(self):
        admin = UsuarioAdmin(Usuario, admin_site)
        formulario = FormularioFalso(
            Usuario,
            {"bloqueado": False},
            {"bloqueado": True},
            ["bloqueado"],
        )

        mensaje = admin.construct_change_message(None, formulario, None)

        self.assertEqual(
            mensaje[0]["changed"]["fields"],
            ["Bloqueado: no → sí"],
        )

    def test_campos_sin_cambios_no_generan_entradas(self):
        formulario = FormularioFalso(Taller, {}, {}, [])

        mensaje = self.admin.construct_change_message(None, formulario, None)

        self.assertEqual(mensaje, [])

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

    def test_textos_extensos_se_truncan(self):
        valor_largo = "x" * 300
        formulario = FormularioFalso(
            Taller,
            {"descripcion": "corta"},
            {"descripcion": valor_largo},
            ["descripcion"],
        )

        mensaje = self.admin.construct_change_message(None, formulario, None)
        resumen = mensaje[0]["changed"]["fields"][0]

        self.assertIn("…", resumen)
        self.assertNotIn(valor_largo, resumen)
        self.assertLess(len(resumen), 120)

    def test_altas_conservan_el_formato_estandar(self):
        formulario = FormularioFalso(
            Taller,
            {},
            {"nombre": "Taller nuevo"},
            ["nombre"],
        )

        mensaje = self.admin.construct_change_message(
            None, formulario, None, add=True,
        )

        self.assertEqual(mensaje, [{"added": {}}])

    def test_registros_historicos_siguen_siendo_legibles(self):
        entrada = LogEntry(
            change_message='[{"changed": {"fields": ["Estado aprobacion"]}}]'
        )

        self.assertIn("Estado aprobacion", entrada.get_change_message())

    def test_registros_historicos_escapados_siguen_siendo_legibles(self):
        entrada = LogEntry(
            change_message=(
                '[{"changed": {"fields": '
                '["Estado: pendiente \\u2192 aprobado"]}}]'
            )
        )

        self.assertIn(
            "Estado: pendiente → aprobado",
            entrada.get_change_message(),
        )


class AuditoriaAccionesTests(SimpleTestCase):
    def setUp(self):
        self.admin = TallerAdmin(Taller, admin_site)
        self.request = SimpleNamespace(user=SimpleNamespace(pk="admin-id"))
        from contextlib import nullcontext
        self.salida_notificacion = self.enterContext(patch("talleres.admin._notificar_edicion_taller"))
        self.enterContext(patch("talleres.servicios.atomic", return_value=nullcontext()))

    def test_aprobar_registra_solo_el_cambio_real(self):
        pendiente = crear_taller()
        ya_aprobado = crear_taller(Taller.Aprobacion.APROBADO)
        queryset = QuerysetFalso([pendiente, ya_aprobado], [1])

        with patch.object(self.admin, "log_change") as log_change, \
                patch.object(self.admin, "message_user"):
            self.admin.aprobar_seleccionados(self.request, queryset)

        self.assertEqual(pendiente.estado_aprobacion, Taller.Aprobacion.APROBADO)
        self.assertEqual(ya_aprobado.estado_aprobacion, Taller.Aprobacion.APROBADO)
        log_change.assert_called_once()
        _, objeto, mensaje = log_change.call_args.args
        self.assertIs(objeto, pendiente)
        self.assertEqual(
            mensaje,
            [{
                "changed": {
                    "fields": ["Estado de aprobación: pendiente → aprobado"],
                }
            }],
        )
        self.assertEqual(
            queryset.actualizaciones,
            [{"estado_aprobacion": Taller.Aprobacion.APROBADO}],
        )
        entrada = LogEntry(change_message=json.dumps(mensaje, ensure_ascii=False))
        self.assertIn("pendiente → aprobado", entrada.get_change_message())

    def test_rechazar_registra_solo_el_cambio_real(self):
        pendiente = crear_taller()
        queryset = QuerysetFalso([pendiente], [1])

        with patch.object(self.admin, "log_change") as log_change, \
                patch.object(self.admin, "message_user"):
            self.admin.rechazar_seleccionados(self.request, queryset)

        self.assertEqual(
            pendiente.estado_aprobacion, Taller.Aprobacion.RECHAZADO,
        )
        log_change.assert_called_once()
        self.assertEqual(
            log_change.call_args.args[2],
            [{
                "changed": {
                    "fields": ["Estado de aprobación: pendiente → rechazado"],
                }
            }],
        )

    def test_estado_legado_nulo_se_interpreta_como_pendiente(self):
        pendiente = crear_taller(None)
        queryset = QuerysetFalso([pendiente], [1])

        with patch.object(self.admin, "log_change") as log_change, \
                patch.object(self.admin, "message_user"):
            self.admin.aprobar_seleccionados(self.request, queryset)

        self.assertEqual(
            log_change.call_args.args[2][0]["changed"]["fields"],
            ["Estado de aprobación: pendiente → aprobado"],
        )

    def test_actualizacion_sin_efecto_no_genera_auditoria(self):
        pendiente = crear_taller()
        queryset = QuerysetFalso([pendiente], [0])

        with patch.object(self.admin, "log_change") as log_change, \
                patch.object(self.admin, "message_user"):
            self.admin.aprobar_seleccionados(self.request, queryset)

        self.assertEqual(
            pendiente.estado_aprobacion, Taller.Aprobacion.PENDIENTE,
        )
        log_change.assert_not_called()
        self.assertEqual(
            queryset.actualizaciones,
            [{"estado_aprobacion": Taller.Aprobacion.APROBADO}],
        )

    def test_taller_fuera_de_pendiente_no_se_consulta_ni_audita(self):
        aprobado = crear_taller(Taller.Aprobacion.APROBADO)
        rechazado = crear_taller(Taller.Aprobacion.RECHAZADO)
        queryset = QuerysetFalso([aprobado, rechazado], [])

        with patch.object(self.admin, "log_change") as log_change, \
                patch.object(self.admin, "message_user"):
            self.admin.rechazar_seleccionados(self.request, queryset)

        log_change.assert_not_called()
        self.assertEqual(queryset.filtros, [])
        self.assertEqual(queryset.actualizaciones, [])


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
        with patch("talleres.servicios.atomic", return_value=nullcontext()), \
             patch("talleres.admin._notificar_edicion_taller") as enviar, \
             patch.object(modelo_admin, "log_change"), \
             patch.object(modelo_admin, "message_user"):
            modelo_admin.aprobar_seleccionados(None, queryset)
        enviar.assert_called_once_with(pendiente, {"estado_aprobacion": ("pendiente", "aprobado")})
