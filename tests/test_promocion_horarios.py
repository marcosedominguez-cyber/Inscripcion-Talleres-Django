"""La promoción respeta plazo, aprobación, bloqueo, FIFO y superposición."""

from contextlib import nullcontext
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest

from talleres import servicios
from talleres.models import Inscripcion, Taller


INICIO = datetime(2030, 10, 15, 12, tzinfo=ZoneInfo("America/La_Paz"))


def solicitud(nombre, *, bloqueada=False):
    return SimpleNamespace(
        pk=nombre, estado=Inscripcion.Estado.EN_ESPERA, save=Mock(),
        participante=SimpleNamespace(pk=nombre, cancelaciones_consecutivas=3 if bloqueada else 0),
    )


@pytest.mark.parametrize("segundos_antes, permitido", [(60, True), (59, False), (0, False)])
def test_promocion_usa_el_mismo_instante_limite_que_la_inscripcion(segundos_antes, permitido):
    taller = SimpleNamespace(nombre="Taller de prueba", fecha_inicio=INICIO, estado_aprobacion=Taller.Aprobacion.APROBADO)
    siguiente = solicitud("primero")
    with patch.object(servicios.timezone, "now", return_value=INICIO - timedelta(seconds=segundos_antes)), \
         patch.object(servicios, "consultar_espera", return_value=[siguiente]), \
         patch.object(servicios, "buscar_superposicion", return_value=None), \
         patch.object(servicios, "_serializar_inscripciones") as serializar, \
         patch.object(servicios, "_notificar") as notificar:
        promovido, motivo = servicios._promover_desde_espera(taller)
    if permitido:
        assert promovido is siguiente and motivo is None
        notificar.assert_called_once()
        assert siguiente.estado == Inscripcion.Estado.CONFIRMADA
        siguiente.save.assert_called_once_with(update_fields=["estado"])
        serializar.assert_called_once_with(siguiente.participante)
    else:
        assert promovido is None and "Fuera de plazo" in motivo
        notificar.assert_not_called()
        assert siguiente.estado == Inscripcion.Estado.EN_ESPERA
        siguiente.save.assert_not_called()
        serializar.assert_not_called()


@pytest.mark.parametrize("bloqueo_manual", [False, True])
def test_promueve_primero_habilitado_y_conserva_en_espera_los_incompatibles(bloqueo_manual):
    taller = SimpleNamespace(nombre="Taller de prueba", fecha_inicio=INICIO, estado_aprobacion=Taller.Aprobacion.APROBADO)
    bloqueado, incompatible, habilitado, ultimo = [solicitud(n) for n in ("b", "i", "h", "u")]
    bloqueado.participante.bloqueado = bloqueo_manual
    bloqueado.participante.cancelaciones_consecutivas = 0 if bloqueo_manual else 3
    otro = SimpleNamespace(codigo="T-ANT", nombre="Anterior", fecha_inicio=INICIO, fecha_fin=INICIO + timedelta(days=1))
    with patch.object(servicios.timezone, "now", return_value=INICIO - timedelta(days=1)), \
         patch.object(servicios, "consultar_espera", return_value=[bloqueado, incompatible, habilitado, ultimo]), \
         patch.object(servicios, "buscar_superposicion", side_effect=[otro, None]) as buscar, \
         patch.object(servicios, "_serializar_inscripciones") as serializar, \
         patch.object(servicios, "_notificar") as notificar:
        promovido, motivo = servicios._promover_desde_espera(taller)
    assert promovido is habilitado and motivo is None
    assert buscar.call_count == 2
    serializar.assert_called_once_with(habilitado.participante)
    habilitado.save.assert_called_once()
    for pendiente in (bloqueado, incompatible, ultimo):
        assert pendiente.estado == Inscripcion.Estado.EN_ESPERA
        pendiente.save.assert_not_called()


@pytest.mark.parametrize("aprobacion", [Taller.Aprobacion.PENDIENTE, Taller.Aprobacion.RECHAZADO])
def test_no_promueve_un_taller_sin_aprobacion(aprobacion):
    with patch.object(servicios, "consultar_espera") as cola:
        promovido, motivo = servicios._promover_desde_espera(SimpleNamespace(estado_aprobacion=aprobacion))
    assert promovido is None and "no está aprobado" in motivo
    cola.assert_not_called()


def test_cancelacion_se_conserva_aunque_la_promocion_ya_este_fuera_de_plazo():
    participante = SimpleNamespace(pk="p", cancelaciones_consecutivas=0)
    taller = SimpleNamespace(
        pk="t", codigo="T-001", nombre="Prueba", fecha_inicio=INICIO,
        estado_aprobacion=Taller.Aprobacion.APROBADO,
    )
    activa = SimpleNamespace(estado=Inscripcion.Estado.CONFIRMADA, delete=Mock())
    cancelacion = SimpleNamespace()
    with patch.object(servicios, "atomic", return_value=nullcontext()), \
         patch.object(servicios.Usuario, "objects") as usuarios, \
         patch.object(servicios.Taller, "objects") as talleres, \
         patch.object(servicios.Inscripcion, "objects") as inscripciones, \
         patch.object(servicios.Cancelacion, "objects") as cancelaciones, \
         patch.object(servicios.timezone, "now", return_value=INICIO - timedelta(seconds=30)), \
         patch.object(servicios, "consultar_espera") as cola:
        usuarios.get.return_value = participante
        talleres.get.return_value = taller
        inscripciones.filter.return_value.first.return_value = activa
        cancelaciones.create.return_value = cancelacion
        resultado = servicios.cancelar_inscripcion("123", "T-001")
    assert resultado is cancelacion and not resultado.promovido
    assert "Fuera de plazo" in resultado.motivo_sin_promocion
    activa.delete.assert_called_once()
    cancelaciones.create.assert_called_once()
    cola.assert_not_called()
