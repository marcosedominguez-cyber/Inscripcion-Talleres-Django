"""Integración de 0008 contra MongoDB local; nunca usar con Atlas."""

from datetime import datetime, timezone as dt_timezone

import pytest
from bson import ObjectId
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from pymongo.errors import DuplicateKeyError

_HOSTS_MONGODB_LOCAL = {
    "mongodb://127.0.0.1:27017",
    "mongodb://localhost:27017",
}
_NOMBRES_DB_LOCAL = {
    "k1_migration_isolated",
}
_CONFIGURACION_LOCAL_SEGURA = (
    connection.vendor == "mongodb"
    and connection.settings_dict.get("HOST") in _HOSTS_MONGODB_LOCAL
    and connection.settings_dict.get("NAME") in _NOMBRES_DB_LOCAL
)

pytestmark = pytest.mark.skipif(
    not _CONFIGURACION_LOCAL_SEGURA,
    reason=(
        "Requiere --ds=config.settings_test_mongodb_local; se omite antes del "
        "setup de pytest-django si host/base no son estrictamente locales."
    ),
)


@pytest.mark.django_db(transaction=True)
def test_migracion_inicializa_estado_sin_inventar_historial_ni_tocar_cancelaciones(migrar_desde_base_limpia):
    settings = connection.settings_dict
    assert settings.get("HOST") in _HOSTS_MONGODB_LOCAL
    assert settings["NAME"] in _NOMBRES_DB_LOCAL

    migrar_desde_base_limpia([
        ("talleres", "0007_usuario_cancelaciones_consecutivas_cancelacion"),
    ])

    ahora = datetime(2030, 10, 15, 9, 0, tzinfo=dt_timezone.utc)
    participantes = connection.get_collection("participantes")
    cancelaciones = connection.get_collection("cancelaciones")
    ids = {
        nombre: ObjectId()
        for nombre in (
            "cero", "dos", "tres", "cinco", "preservado", "ya_bloqueado",
            "sin_contador",
        )
    }

    documentos = [
        {
            "_id": ids["cero"], "nombre": "Cero", "ci": "10000000",
            "rol": "participante", "cancelaciones_consecutivas": 0,
        },
        {
            "_id": ids["dos"], "nombre": "Dos", "ci": "10000002",
            "rol": "participante", "cancelaciones_consecutivas": 2,
        },
        {
            "_id": ids["tres"], "nombre": "Tres", "ci": "10000003",
            "rol": "participante", "cancelaciones_consecutivas": 3,
        },
        {
            "_id": ids["cinco"], "nombre": "Cinco", "ci": "10000005",
            "rol": "participante", "cancelaciones_consecutivas": 5,
        },
        {
            "_id": ids["preservado"], "nombre": "Preservado", "ci": "10000006",
            "rol": "participante", "cancelaciones_consecutivas": 5,
            "bloqueado": False,
        },
        {
            "_id": ids["ya_bloqueado"], "nombre": "Ya bloqueado", "ci": "10000007",
            "rol": "participante", "cancelaciones_consecutivas": 4,
            "bloqueado": True,
        },
        {
            "_id": ids["sin_contador"], "nombre": "Sin contador", "ci": "10000008",
            "rol": "participante",
        },
    ]
    participantes.insert_many(documentos)

    cancelacion = {
        "_id": ObjectId(),
        "participante_id": ids["tres"],
        "taller_id": ObjectId(),
        "codigo_taller": "T-001",
        "nombre_taller": "Taller de prueba",
        "estado_anterior": "confirmada",
        "fecha_cancelacion": ahora,
    }
    cancelaciones.insert_one(cancelacion)
    antecedente = cancelaciones.find_one({"_id": cancelacion["_id"]})
    total_cancelaciones = cancelaciones.count_documents({})

    executor = MigrationExecutor(connection)
    executor.migrate([("talleres", "0008_usuario_bloqueado_bloqueo")])

    estado = {
        nombre: participantes.find_one({"_id": object_id})["bloqueado"]
        for nombre, object_id in ids.items()
    }
    assert estado == {
        "cero": False,
        "dos": False,
        "tres": True,
        "cinco": True,
        "preservado": False,
        "ya_bloqueado": True,
        "sin_contador": False,
    }
    assert cancelaciones.count_documents({}) == total_cancelaciones
    assert cancelaciones.find_one({"_id": cancelacion["_id"]}) == antecedente

    bloqueos = connection.get_collection("bloqueos")
    assert bloqueos.count_documents({}) == 0

    indices = bloqueos.index_information()
    assert indices["bloqueo_abierto_unico"]["unique"] is True
    assert list(indices["bloqueo_abierto_unico"]["key"]) == [
        ("participante_id", 1), ("fecha_desbloqueo", 1),
    ]
    assert "bloqueos_participante_fecha" in indices

    bloqueos.insert_one({
        "_id": ObjectId(),
        "participante_id": ids["tres"],
        "motivo": "cancelaciones_consecutivas",
        "fecha_bloqueo": ahora,
        "bloqueado_por": None,
        "fecha_desbloqueo": None,
        "desbloqueado_por": None,
    })
    with pytest.raises(DuplicateKeyError):
        bloqueos.insert_one({
            "_id": ObjectId(),
            "participante_id": ids["tres"],
            "motivo": "manual",
            "fecha_bloqueo": ahora,
            "bloqueado_por": None,
            "fecha_desbloqueo": None,
            "desbloqueado_por": None,
        })
    assert participantes.find_one({"_id": ids["preservado"]})["bloqueado"] is False
