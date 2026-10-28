"""Pruebas de la capa de lectura compartida, sin base de datos."""

from unittest.mock import Mock, call, patch

from django.test import SimpleTestCase

from talleres.consultas import (
    buscar_taller_instructor,
    contar_confirmadas,
    listar_talleres_instructor,
)
from talleres.models import Inscripcion, Taller


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
