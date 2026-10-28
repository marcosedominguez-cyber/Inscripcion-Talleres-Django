"""Pruebas del límite de compatibilidad entre el menú CLI y los servicios web."""

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from talleres.servicios import CupoAgotadoError


class CompatibilidadMenuCliTests(SimpleTestCase):
    def test_menu_registra_participante_con_ci_sin_codigo(self):
        from proyecto import main

        salida = StringIO()
        with patch("builtins.input", side_effect=["1", "12345678", "Ana", "7"]), \
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
        with patch("builtins.input", side_effect=["4", "11111111", "T-001", "7"]), \
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
