"""Pruebas del límite de compatibilidad entre el menú CLI y los servicios web."""

from contextlib import redirect_stdout
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from talleres.servicios import CupoAgotadoError


class CompatibilidadMenuCliTests(SimpleTestCase):
    def test_menu_registra_participante_con_ci_sin_codigo(self):
        from proyecto import main

        salida = StringIO()
        with patch("builtins.input", side_effect=["1", "12345678", "Ana", "9"]), \
             patch.object(
                 main.servicios,
                 "registrar_participante",
                 return_value=SimpleNamespace(ci="12345678"),
             ) as registrar, \
             redirect_stdout(salida):
            main.ejecutar()

        registrar.assert_called_once_with("Ana", "12345678")
        self.assertIn("CI: 12345678", salida.getvalue())
        self.assertNotIn("P-", salida.getvalue())

    def test_menu_captura_error_de_inscripcion_emitido_por_servicio_web(self):
        from proyecto import main

        salida = StringIO()
        with patch("builtins.input", side_effect=["4", "11111111", "T-001", "9"]), \
             patch.object(
                 main.servicios,
                 "inscribir_participante",
                 side_effect=CupoAgotadoError("El taller no tiene cupos disponibles."),
             ), \
             redirect_stdout(salida):
            main.ejecutar()

        self.assertIn(
            "No se pudo realizar la operación: El taller no tiene cupos disponibles.",
            salida.getvalue(),
        )
        self.assertNotIn("Traceback", salida.getvalue())


    def test_menu_cancela_y_muestra_el_historial(self):
        from proyecto import main

        salida = StringIO()
        cancelacion = SimpleNamespace(
            nombre_taller="Taller de prueba", codigo_taller="T-001",
            estado_anterior="confirmada", promovido=True, cuenta_bloqueada=False,
        )
        historial = [SimpleNamespace(
            codigo_taller="T-001", nombre_taller="Taller de prueba",
            estado_anterior="confirmada",
            fecha_cancelacion=datetime(2030, 10, 15, 12, 0, tzinfo=dt_timezone.utc),
        )]
        participante = SimpleNamespace(cancelaciones_consecutivas=1)
        with patch("builtins.input", side_effect=[
            "7", "12345678", "T-001",
            "8", "12345678",
            "9",
        ]), patch.object(
            main.servicios, "cancelar_inscripcion", return_value=cancelacion,
        ) as cancelar, patch.object(
            main, "listar_cancelaciones_participante", return_value=historial,
        ), patch.object(
            main.Usuario, "objects",
        ) as usuarios, redirect_stdout(salida):
            usuarios.get.return_value = participante
            main.ejecutar()

        cancelar.assert_called_once_with("12345678", "T-001")
        texto = salida.getvalue()
        self.assertIn("Cancelación registrada", texto)
        self.assertIn("Se promovió", texto)
        self.assertIn("[T-001] Taller de prueba", texto)
        self.assertIn("Cancelaciones consecutivas: 1", texto)
