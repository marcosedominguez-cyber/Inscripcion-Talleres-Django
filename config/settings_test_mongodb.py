"""MongoDB exclusivo de pruebas: no importa settings ni carga el .env del equipo."""

import os
import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .settings_test_mongodb_local import *  # noqa: F403

BASE_DIR = Path(__file__).resolve().parent.parent
nombre = os.getenv("MONGODB_TEST_DATABASE", "test_talleres_piramide")
if not re.fullmatch(r"test_talleres_[a-zA-Z0-9_]+", nombre):
    raise ImproperlyConfigured("La base de pruebas debe llamarse test_talleres_<identificador>.")
if os.getenv("EJECUTAR_PRUEBAS_MONGODB") != "1":
    raise ImproperlyConfigured("Ejecuta la suite con scripts/ejecutar_pruebas.py --completa.")

DATABASES["default"].update(  # noqa: F405
    HOST=os.getenv("MONGODB_TEST_URI", "mongodb://127.0.0.1:27017"),
    NAME=nombre,
    TEST={"NAME": nombre},
    OPTIONS={"serverSelectionTimeoutMS": 5000, "connectTimeoutMS": 5000},
)
TEMPLATES[0]["DIRS"] = [BASE_DIR / "frontend" / "dist"]  # noqa: F405
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist"]
CSRF_FAILURE_VIEW = "config.vistas.csrf_error"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
