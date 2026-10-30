"""Reglas compartidas, rechazos sin cambios y mensajes del caso de uso #4."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from talleres.reglas import horarios_superpuestos


INICIO = datetime(2030, 10, 15, 10, tzinfo=ZoneInfo("America/La_Paz"))


@pytest.mark.parametrize("inicio_horas, fin_horas, esperado", [
    (2, 4, False), (1, 3, True), (0, 2, True), (0.5, 1.5, True),
])
def test_solapamiento_real_y_extremos_adyacentes(inicio_horas, fin_horas, esperado):
    otro_inicio = INICIO + timedelta(hours=inicio_horas)
    otro_fin = INICIO + timedelta(hours=fin_horas)
    assert horarios_superpuestos(INICIO, INICIO + timedelta(hours=2), otro_inicio, otro_fin) is esperado
    assert horarios_superpuestos(otro_inicio, otro_fin, INICIO, INICIO + timedelta(hours=2)) is esperado


def test_superposicion_compara_fechas_completas_y_zonas_horarias():
    medianoche = INICIO.replace(hour=23)
    siguiente = medianoche + timedelta(hours=2)
    assert horarios_superpuestos(
        medianoche, siguiente,
        (medianoche + timedelta(hours=1)).astimezone(ZoneInfo("UTC")),
        (siguiente + timedelta(hours=1)).astimezone(ZoneInfo("UTC")),
    )
    assert not horarios_superpuestos(
        INICIO, INICIO + timedelta(hours=2),
        INICIO + timedelta(days=1), INICIO + timedelta(days=1, hours=2),
    )
