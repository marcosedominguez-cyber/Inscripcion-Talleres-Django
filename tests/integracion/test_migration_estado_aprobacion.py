"""Integración de 0003 en una base MongoDB exclusiva de pruebas."""

from datetime import timedelta
from importlib import import_module

import pytest
from bson import ObjectId
from django.db import connection
from django.utils import timezone
from django.db.migrations.executor import MigrationExecutor

@pytest.mark.django_db(transaction=True)
def test_migracion_rellena_solo_ausentes_es_repetible_y_filtra_catalogo(migrar_desde_base_limpia):
    # Segunda barrera: incluso con settings equivocados, abortar antes de tocar datos.
    settings = connection.settings_dict
    assert settings["NAME"].startswith("test_talleres_")

    destino_previo = [("talleres", "0002_usuario_cuentas")]
    migrar_desde_base_limpia(destino_previo)

    ahora = timezone.now()
    collection = connection.get_collection("talleres")
    ids = {estado: ObjectId() for estado in ("ausente", "aprobado", "rechazado")}
    documentos = []
    for estado, object_id in ids.items():
        documento = {
            "_id": object_id,
            "codigo": f"K1-MIG-{object_id}",
            "nombre": "Taller de prueba de migración",
            "descripcion": "Documento sintético local",
            "cupos": 4,
            "fecha_inicio": ahora + timedelta(days=2),
            "fecha_fin": ahora + timedelta(days=2, hours=2),
            "instructor_id": None,
        }
        if estado != "ausente":
            documento["estado_aprobacion"] = estado
        documentos.append(documento)
    collection.insert_many(documentos)
    filtro_fixtures = {"_id": {"$in": list(ids.values())}}
    assert collection.count_documents(filtro_fixtures) == 3
    assert collection.count_documents({
        **filtro_fixtures,
        "estado_aprobacion": {"$exists": False},
    }) == 1

    executor = MigrationExecutor(connection)
    executor.migrate([("talleres", "0003_taller_estado_aprobacion")])
    assert collection.count_documents(filtro_fixtures) == 3
    assert collection.count_documents({
        **filtro_fixtures,
        "estado_aprobacion": {"$exists": False},
    }) == 0

    resultados = {
        estado: collection.find_one({"_id": object_id})["estado_aprobacion"]
        for estado, object_id in ids.items()
    }
    assert resultados == {
        "ausente": "pendiente",
        "aprobado": "aprobado",
        "rechazado": "rechazado",
    }

    migracion = import_module("talleres.migrations.0003_taller_estado_aprobacion")
    apps = executor.loader.project_state([
        ("talleres", "0003_taller_estado_aprobacion"),
    ]).apps
    with connection.schema_editor() as schema_editor:
        migracion.completar_estado_aprobacion_ausente(
            apps, schema_editor
        )

    resultados_repetidos = {
        estado: collection.find_one({"_id": object_id})["estado_aprobacion"]
        for estado, object_id in ids.items()
    }
    assert collection.count_documents(filtro_fixtures) == 3
    assert collection.count_documents({
        **filtro_fixtures,
        "estado_aprobacion": {"$exists": False},
    }) == 0
    assert resultados_repetidos == resultados

    from talleres.consultas import listar_talleres_proximos

    publicados = {
        taller.codigo for taller in listar_talleres_proximos()
    }
    codigos = {
        estado: documento["codigo"]
        for estado, documento in zip(ids, documentos)
    }
    assert codigos["aprobado"] in publicados
    assert codigos["ausente"] not in publicados
    assert codigos["rechazado"] not in publicados
