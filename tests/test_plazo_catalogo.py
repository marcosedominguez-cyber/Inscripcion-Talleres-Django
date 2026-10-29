"""El catálogo y la regla de inscripción coinciden en el minuto de cierre."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from talleres.consultas import listar_talleres_proximos
from talleres.models import Taller
from talleres.reglas import inscripcion_abierta


INICIO = datetime(2030, 10, 15, 12, 0, tzinfo=ZoneInfo("America/La_Paz"))


@pytest.mark.parametrize("segundos_antes, permitido", [
    (61, True),
    (60, True),
    (59, False),
    (0, False),
    (-1, False),
])
def test_catalogo_y_regla_coinciden_antes_en_y_despues_del_limite(segundos_antes, permitido):
    ahora = INICIO - timedelta(seconds=segundos_antes)
    taller = SimpleNamespace(codigo="T-001", fecha_inicio=INICIO)
    manager = Mock()
    manager.filter.return_value = [taller]
    with patch.object(Taller, "objects", manager), \
         patch("talleres.consultas.timezone.now", return_value=ahora):
        resultado = listar_talleres_proximos()

    assert inscripcion_abierta(INICIO, ahora) is permitido
    assert resultado == ([taller] if permitido else [])
    manager.filter.assert_called_once_with(
        estado_aprobacion=Taller.Aprobacion.APROBADO,
        fecha_inicio__gt=ahora,
    )


def test_el_limite_compara_instantes_y_no_la_hora_escrita_de_cada_zona():
    limite_local = datetime(2030, 10, 15, 11, 59, tzinfo=ZoneInfo("America/La_Paz"))
    inicio_utc = INICIO.astimezone(ZoneInfo("UTC"))

    assert inscripcion_abierta(inicio_utc, limite_local)
    assert not inscripcion_abierta(inicio_utc, limite_local + timedelta(microseconds=1))
