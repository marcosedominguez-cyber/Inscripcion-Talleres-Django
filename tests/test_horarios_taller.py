"""Revisión de inicio y fin compartidos por modelos, formularios y servicios."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from talleres import servicios
from talleres.formularios_gestion import TallerGestionForm
from talleres.models import Taller


INICIO = datetime(2030, 10, 15, 10, 30, tzinfo=ZoneInfo("America/La_Paz"))


def datos_taller(fin):
    return {
        "nombre": "Taller de horarios",
        "cupos": 4,
        "fecha_inicio": INICIO,
        "fecha_fin": fin,
    }


@pytest.mark.parametrize("duracion", [timedelta(days=1), timedelta(days=7)])
def test_modelo_y_formulario_aceptan_limites_y_conservan_fecha_y_hora(duracion):
    datos = datos_taller(INICIO + duracion)
    taller = Taller(codigo="T-001", **datos)
    taller.full_clean(validate_unique=False, validate_constraints=False)

    with timezone.override("America/La_Paz"):
        formulario = TallerGestionForm(data={
            **datos,
            "fecha_inicio": datos["fecha_inicio"].strftime("%Y-%m-%dT%H:%M"),
            "fecha_fin": datos["fecha_fin"].strftime("%Y-%m-%dT%H:%M"),
        })
        assert formulario.is_valid(), formulario.errors

    assert taller.fecha_inicio == formulario.cleaned_data["fecha_inicio"] == INICIO
    assert taller.fecha_fin == formulario.cleaned_data["fecha_fin"] == INICIO + duracion
    assert formulario.cleaned_data["fecha_inicio"].hour == 10
    assert formulario.cleaned_data["fecha_inicio"].minute == 30


@pytest.mark.parametrize("duracion, mensaje", [
    (timedelta(minutes=-1), "El fin debe ser posterior al inicio del taller."),
    (timedelta(0), "El fin debe ser posterior al inicio del taller."),
    (timedelta(hours=23, minutes=59), "La duración mínima del taller es de 24 horas."),
    (timedelta(days=7, minutes=1), "La duración máxima del taller es de 7 días."),
])
def test_modelo_formulario_y_servicio_rechazan_los_mismos_horarios(duracion, mensaje):
    datos = datos_taller(INICIO + duracion)
    taller = Taller(codigo="T-001", **datos)
    with pytest.raises(ValidationError) as error_modelo:
        taller.full_clean(validate_unique=False, validate_constraints=False)
    assert error_modelo.value.message_dict["fecha_fin"] == [mensaje]

    formulario = TallerGestionForm(data=datos)
    assert not formulario.is_valid()
    assert formulario.errors["fecha_fin"] == [mensaje]

    with patch.object(servicios, "_preparar_contador") as contador, \
         patch.object(servicios, "_crear_taller") as guardar:
        with pytest.raises(ValidationError) as error_servicio:
            servicios.registrar_taller(**datos)
    assert error_servicio.value.message_dict["fecha_fin"] == [mensaje]
    contador.assert_not_called()
    guardar.assert_not_called()


@pytest.mark.parametrize("campo", ["fecha_inicio", "fecha_fin"])
def test_inicio_y_fin_son_obligatorios_en_modelo_y_formulario(campo):
    datos = datos_taller(INICIO + timedelta(days=1))
    datos[campo] = None
    taller = Taller(codigo="T-001", **datos)
    with pytest.raises(ValidationError) as error:
        taller.full_clean(validate_unique=False, validate_constraints=False)
    assert campo in error.value.message_dict

    formulario = TallerGestionForm(data=datos)
    assert not formulario.is_valid()
    assert campo in formulario.errors
