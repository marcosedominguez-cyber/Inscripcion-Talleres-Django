"""Pruebas de la capa de lectura compartida, sin base de datos."""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from talleres.consultas import (
    buscar_taller_instructor,
    contar_confirmadas,
    listar_cancelaciones_participante,
    listar_inscripciones_participante,
    listar_talleres_instructor,
)
from talleres.models import Cancelacion, Inscripcion, Taller


class ConsultasInstructorTests(SimpleTestCase):
    def test_listar_y_buscar_filtran_por_instructor_y_codigo(self):
        manager = Mock()
        manager.filter.return_value.first.return_value = "taller"
        with patch.object(Taller, "objects", manager):
            listado = listar_talleres_instructor("instructor")
            encontrado = buscar_taller_instructor("instructor", "T-001")

        self.assertIs(listado, manager.filter.return_value)
        self.assertEqual(encontrado, "taller")
        self.assertEqual(manager.filter.call_args_list, [
            call(instructor="instructor"),
            call(instructor="instructor", codigo="T-001"),
        ])

    def test_contar_confirmadas_solo_consulta_el_estado_confirmado(self):
        manager = Mock()
        manager.filter.return_value.values_list.return_value = ["i-1", "i-2"]
        with patch.object(Inscripcion, "objects", manager):
            self.assertEqual(contar_confirmadas("taller"), 2)

        manager.filter.assert_called_once_with(
            taller="taller", estado=Inscripcion.Estado.CONFIRMADA
        )
        manager.filter.return_value.values_list.assert_called_once_with(
            "pk", flat=True
        )


class ConsultaEsperaTests(SimpleTestCase):
    def test_ordena_por_fecha_y_id_y_filtra_taller_y_estado(self):
        from talleres.consultas import consultar_espera
        with patch.object(Inscripcion, "objects") as manager:
            manager.filter.return_value.order_by.return_value = ["primero", "segundo"]
            self.assertEqual(consultar_espera("t"), ["primero", "segundo"])
            manager.filter.assert_called_once_with(taller="t", estado=Inscripcion.Estado.EN_ESPERA)
            manager.filter.return_value.order_by.assert_called_once_with("fecha_solicitud", "id")

    def test_posicion_y_disponibilidad_personales(self):
        from types import SimpleNamespace
        from talleres.consultas import resumen_espera
        taller = SimpleNamespace(cupos=10)
        participante = SimpleNamespace(pk="p2")
        solicitudes = [SimpleNamespace(participante_id="p1"), SimpleNamespace(participante_id="p2")]
        with patch("talleres.consultas.consultar_espera", return_value=solicitudes), \
             patch.object(Inscripcion, "objects") as manager:
            manager.filter.return_value.first.return_value = SimpleNamespace(estado="en_espera")
            datos = resumen_espera(taller, participante)
        self.assertEqual(datos, {"limite_espera": 2, "lugares_espera": 0,
                                "mi_estado": "en_espera", "posicion_espera": 2})


class ConsultaMisInscripcionesTests(SimpleTestCase):
    ahora = datetime(2030, 10, 15, 12, 0, tzinfo=dt_timezone.utc)

    def registro(self, *, estado=Inscripcion.Estado.CONFIRMADA, fin=None):
        return SimpleNamespace(
            estado=estado,
            taller=SimpleNamespace(fecha_fin=fin or self.ahora + timedelta(hours=1)),
        )

    def listar(self, registros, *, ahora=None):
        manager = Mock()
        manager.filter.return_value.select_related.return_value = registros
        with patch.object(Inscripcion, "objects", manager), patch(
            "talleres.consultas.timezone.now", return_value=ahora or self.ahora
        ):
            return listar_inscripciones_participante("p"), manager

    def test_filtra_por_participante_estados_y_carga_relaciones(self):
        futura = self.registro(fin=self.ahora + timedelta(days=1))
        resultado, manager = self.listar([futura])

        self.assertEqual(resultado, [futura])
        manager.filter.assert_called_once_with(
            participante="p",
            estado__in=(Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.EN_ESPERA),
        )
        manager.filter.return_value.select_related.assert_called_once_with(
            "taller", "taller__instructor"
        )

    def test_incluye_talleres_futuros_y_en_curso_de_ambos_estados(self):
        futura_confirmada = self.registro(fin=self.ahora + timedelta(days=1))
        en_curso_en_espera = self.registro(
            estado=Inscripcion.Estado.EN_ESPERA,
            fin=self.ahora + timedelta(minutes=1),
        )
        resultado, _ = self.listar([futura_confirmada, en_curso_en_espera])

        self.assertEqual(resultado, [futura_confirmada, en_curso_en_espera])

    def test_excluye_finalizados_y_el_instante_exacto_en_ambos_estados(self):
        futura = self.registro(fin=self.ahora + timedelta(seconds=1))
        finalizada_confirmada = self.registro(fin=self.ahora - timedelta(seconds=1))
        finalizada_en_espera = self.registro(
            estado=Inscripcion.Estado.EN_ESPERA,
            fin=self.ahora - timedelta(days=1),
        )
        exacta_confirmada = self.registro(fin=self.ahora)
        exacta_en_espera = self.registro(
            estado=Inscripcion.Estado.EN_ESPERA,
            fin=self.ahora,
        )
        resultado, _ = self.listar([
            finalizada_confirmada,
            finalizada_en_espera,
            exacta_confirmada,
            exacta_en_espera,
            futura,
        ])

        self.assertEqual(resultado, [futura])


class ConsultaCancelacionesTests(SimpleTestCase):
    def test_lista_historial_del_participante_mas_reciente_primero(self):
        with patch.object(Cancelacion, "objects") as manager:
            manager.filter.return_value.order_by.return_value = ["c1", "c2"]
            resultado = listar_cancelaciones_participante("participante")

        self.assertEqual(resultado, ["c1", "c2"])
        manager.filter.assert_called_once_with(participante="participante")
        manager.filter.return_value.order_by.assert_called_once_with(
            "-fecha_cancelacion", "-id"
        )
