"""Comprobaciones de esquema Django que no usan MongoDB."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone
from django_mongodb_backend.fields import ObjectIdAutoField

from talleres import servicios
from talleres.models import Cancelacion, Contador, Inscripcion, Taller, Usuario


def test_modelos_de_negocio_usan_objectid_interno_y_referencias_objectid():
    for modelo in (Usuario, Taller, Inscripcion, Contador):
        pk = modelo._meta.pk
        assert isinstance(pk, ObjectIdAutoField)
        assert pk.db_column == "_id"
        assert pk.db_type(connection) == "objectId"

    participante = Inscripcion._meta.get_field("participante")
    taller = Inscripcion._meta.get_field("taller")
    instructor = Taller._meta.get_field("instructor")
    assert participante.db_type(connection) == "objectId"
    assert taller.db_type(connection) == "objectId"
    assert instructor.db_type(connection) == "objectId"


def test_ci_es_requerida_y_unica_y_usuario_no_tiene_codigo():
    ci = Usuario._meta.get_field("ci")
    assert ci.unique is True
    assert ci.null is False
    assert ci.blank is False
    assert "codigo" not in {field.name for field in Usuario._meta.fields}
    assert "revision" not in {field.name for field in Taller._meta.fields}


def test_taller_mantiene_codigo_unico_estado_de_aprobacion_y_cupo_valido():
    assert Taller._meta.get_field("codigo").unique is True
    assert [estado for estado, _ in Taller.Aprobacion.choices] == [
        "pendiente", "aprobado", "rechazado",
    ]
    assert Taller._meta.get_field("estado_aprobacion").default == Taller.Aprobacion.PENDIENTE
    ahora = timezone.now()
    for cupos in (3, 41):
        taller = Taller(
            codigo="T-001", nombre="Prueba", cupos=cupos,
            fecha_inicio=ahora, fecha_fin=ahora + timedelta(days=2),
        )
        try:
            taller.full_clean(validate_unique=False, validate_constraints=False)
        except ValidationError as error:
            assert "cupos" in error.message_dict
        else:
            raise AssertionError(f"Se aceptó un taller con {cupos} cupos.")


def test_taller_exige_duracion_entre_24_horas_y_7_dias():
    ahora = timezone.now()
    for duracion, campo in (
        (timedelta(hours=23), "fecha_fin"),
        (timedelta(days=8), "fecha_fin"),
        (timedelta(hours=-1), "fecha_fin"),
    ):
        taller = Taller(
            codigo="T-002", nombre="Duración", cupos=4,
            fecha_inicio=ahora, fecha_fin=ahora + duracion,
        )
        try:
            taller.full_clean(validate_unique=False, validate_constraints=False)
        except ValidationError as error:
            assert campo in error.message_dict
        else:
            raise AssertionError(f"Se aceptó una duración de {duracion}.")

    taller = Taller(
        codigo="T-003", nombre="Duración válida", cupos=4,
        fecha_inicio=ahora, fecha_fin=ahora + timedelta(days=7),
    )
    taller.full_clean(validate_unique=False, validate_constraints=False)


def test_inscripcion_conserva_unicidad_por_referencias_internas():
    constraint, = Inscripcion._meta.constraints
    assert constraint.fields == ("participante", "taller")
    assert constraint.name == "inscripcion_participante_taller_unica"


def test_codigos_de_taller_se_generan_secuencialmente_desde_el_contador():
    manager = Mock()
    manager.get.side_effect = [
        SimpleNamespace(valor=1),
        SimpleNamespace(valor=2),
        SimpleNamespace(valor=3),
    ]
    with patch.object(Contador, "objects", manager):
        codigos = [servicios._siguiente_codigo("talleres", "T") for _ in range(3)]

    assert codigos == ["T-001", "T-002", "T-003"]
    assert len(set(codigos)) == 3
    assert manager.filter.call_args_list == [call(nombre="talleres")] * 3
    assert manager.filter.return_value.update.call_count == 3


def test_espera_reutiliza_campos_y_estados_sin_nuevas_referencias():
    assert Inscripcion.Estado.EN_ESPERA == "en_espera"
    assert "en_espera" in dict(Inscripcion._meta.get_field("estado").choices)
    assert Inscripcion._meta.get_field("fecha_solicitud").auto_now_add


def test_cancelacion_conserva_antecedente_y_bloqueo_derivado_del_contador():
    assert Usuario._meta.get_field("cancelaciones_consecutivas").default == 0
    assert Cancelacion._meta.db_table == "cancelaciones"
    campos = {campo.name for campo in Cancelacion._meta.fields}
    assert {
        "participante", "taller", "codigo_taller", "nombre_taller",
        "estado_anterior", "fecha_cancelacion",
    } <= campos
    assert Cancelacion._meta.ordering == ["-fecha_cancelacion", "-id"]
    assert Cancelacion._meta.get_field("fecha_cancelacion").auto_now_add
