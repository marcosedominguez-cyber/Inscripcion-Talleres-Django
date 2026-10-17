"""Configuración aislada: los tests no consultan ni modifican Atlas.

No se importa config.settings, por lo que no requiere archivo .env.
No usar este módulo para ejecutar la aplicación con datos reales.
"""

SECRET_KEY = "solo-pruebas-locales-participantes"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "talleres.apps.TalleresConfig",
]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
ROOT_URLCONF = "config.urls_test_api_participantes"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
    ]},
}]
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/cuentas/login/"
USE_TZ = True
TIME_ZONE = "America/La_Paz"
LANGUAGE_CODE = "es"
