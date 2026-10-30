"""Prepara pruebas de migraciones sin revertir migraciones irreversibles."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.fixture
def migrar_desde_base_limpia(transactional_db):
    # Solo se elimina el esquema de la base exclusiva de esta ejecución de estas pruebas.
    assert connection.vendor == "mongodb"
    from django.conf import settings
    assert settings.SETTINGS_MODULE == "config.settings_test_mongodb"
    assert connection.settings_dict["NAME"].startswith("test_talleres_")
    destinos_actuales = MigrationExecutor(connection).loader.graph.leaf_nodes()

    def preparar(destino):
        base = connection.get_database()
        for nombre in base.list_collection_names():
            if not nombre.startswith("system."):
                base.drop_collection(nombre)
        MigrationExecutor(connection).migrate(destino)

    try:
        yield preparar
    finally:
        # Las pruebas siguientes reciben de nuevo el esquema actual.
        MigrationExecutor(connection).migrate(destinos_actuales)
