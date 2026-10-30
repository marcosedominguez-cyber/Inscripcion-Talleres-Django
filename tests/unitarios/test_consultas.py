"""Pruebas de la capa de lectura compartida, sin base de datos."""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from talleres.consultas import listar_cancelaciones_participante, listar_inscripciones_participante
from talleres.models import Cancelacion, Inscripcion


class ConsultaEsperaTests(SimpleTestCase):
    def test_ordena_por_fecha_y_id_y_filtra_taller_y_estado(self):
        from talleres.consultas import consultar_espera
        with patch.object(Inscripcion, "objects") as manager:
            manager.filter.return_value.order_by.return_value = ["primero", "segundo"]
            self.assertEqual(consultar_espera("t"), ["primero", "segundo"])
            manager.filter.assert_called_once_with(taller="t", estado=Inscripcion.Estado.EN_ESPERA)
            manager.filter.return_value.order_by.assert_called_once_with("fecha_solicitud", "id")


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
