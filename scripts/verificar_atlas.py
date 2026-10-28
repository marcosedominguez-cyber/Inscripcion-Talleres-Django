"""Prueba real en una base temporal. Ejecutar desde la raíz con python scripts/verificar_atlas.py."""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
nombre_prueba = "test_cli_" + uuid4().hex[:16]
os.environ["MONGODB_DATABASE"] = nombre_prueba
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import connection, connections, IntegrityError
from django.utils import timezone
from talleres.servicios import (
    CupoAgotadoError, InscripcionDuplicadaError,
    DatosParticipanteInvalidosError, ParticipanteNoEncontradoError,
    TallerNoEncontradoError,
)
from talleres import servicios
from talleres.models import Taller, Inscripcion


def esperar_error(tipo, funcion, *args, **kwargs):
    try:
        funcion(*args, **kwargs)
    except tipo:
        return
    raise AssertionError(f"No se rechazó la operación con {tipo.__name__}")


def menu(entrada):
    result = subprocess.run(
        [sys.executable, "-m", "proyecto.main"], input=entrada,
        text=True, capture_output=True, timeout=60,
        encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stderr
    assert "No se pudo completar" not in result.stdout, result.stdout
    return result.stdout


try:
    assert connection.settings_dict["NAME"] == nombre_prueba
    # Reproducir las tres colecciones vacías creadas manualmente en Atlas.
    for coleccion in ("participantes", "talleres", "inscripciones"):
        connection.database.create_collection(coleccion)
    call_command("migrate", "talleres", verbosity=0, interactive=False)
    esperar_error(DatosParticipanteInvalidosError, servicios.registrar_participante, "   ", "11111111")
    ana = servicios.registrar_participante("Ana prueba", "11111111")
    bruno = servicios.registrar_participante("Bruno prueba", "22222222")
    carla = servicios.registrar_participante("Carla prueba", "33333333")
    diego = servicios.registrar_participante("Diego prueba", "44444444")
    elena = servicios.registrar_participante("Elena prueba", "55555555")
    assert ana.ci == "11111111" and bruno.ci == "22222222"
    inicio = timezone.now() + timedelta(days=1)
    esperar_error(ValidationError, servicios.registrar_taller, "Inválido", 0, inicio, inicio)
    taller = servicios.registrar_taller("Taller prueba", 4, inicio, inicio + timedelta(days=2))
    assert taller.codigo == "T-001"
    taller.estado_aprobacion = Taller.Aprobacion.APROBADO
    taller.save(update_fields=["estado_aprobacion"])
    esperar_error(ParticipanteNoEncontradoError, servicios.inscribir_participante, "99999999", taller.codigo)
    esperar_error(TallerNoEncontradoError, servicios.inscribir_participante, ana.ci, "T-999")
    servicios.inscribir_participante(ana.ci, taller.codigo)
    esperar_error(InscripcionDuplicadaError, servicios.inscribir_participante, ana.ci, taller.codigo)
    for participante in (bruno, carla, diego):
        servicios.inscribir_participante(participante.ci, taller.codigo)
    esperar_error(CupoAgotadoError, servicios.inscribir_participante, elena.ci, taller.codigo)
    assert Inscripcion.objects.count() == 4 and servicios.cupos_disponibles(taller) == 0
    esperar_error(IntegrityError, Inscripcion.objects.create, participante=ana, taller=taller)
    # Procesos distintos: registrar, cerrar y volver a consultar desde el menú.
    assert "CI: 66666666" in menu("1\n66666666\nPersistencia CLI\n7\n")
    salida = menu("6\n3\n5\n7\n")
    assert "Persistencia CLI" in salida and "Taller prueba" in salida and "confirmada" in salida
    print("OK: colecciones existentes, validaciones, duplicados, cupos y persistencia entre procesos.")
finally:
    if connection.settings_dict["NAME"] != nombre_prueba or not nombre_prueba.startswith("test_cli_"):
        raise RuntimeError("Se impidió limpiar una base distinta de la temporal.")
    connection.database.client.drop_database(nombre_prueba)
    connections.close_all()
    print("Base temporal de prueba eliminada; talleres_db no recibió datos de prueba.")
