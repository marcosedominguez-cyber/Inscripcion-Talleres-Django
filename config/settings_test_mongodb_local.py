"""Settings para pruebas MongoDB en una instancia local desechable.

No carga .env ni acepta una URI configurable. El host queda fijado a loopback
y el test runner usa una base de datos separada con prefijo ``test_``.
"""

SECRET_KEY = "solo-pruebas-locales-mongodb"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "config.apps.MongoAdminConfig",
    "config.apps.MongoAuthConfig",
    "config.apps.MongoContentTypesConfig",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_mongodb_backend",
    "talleres.apps.TalleresConfig",
    "cuentas.apps.CuentasConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django_mongodb_backend",
        "HOST": "mongodb://127.0.0.1:27017",
        "NAME": "k1_migration_isolated",
        "OPTIONS": {
            "serverSelectionTimeoutMS": 1000,
            "connectTimeoutMS": 1000,
        },
        "TEST": {"NAME": "k1_migration_isolated"},
    }
}
DATABASE_ROUTERS = ["django_mongodb_backend.routers.MongoRouter"]
MIGRATION_MODULES = {
    "admin": "mongo_migrations.admin",
    "auth": "mongo_migrations.auth",
    "contenttypes": "mongo_migrations.contenttypes",
}

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django_mongodb_backend.fields.ObjectIdAutoField"
LOGIN_URL = "/cuentas/login/"
AUTHENTICATION_BACKENDS = [
    "cuentas.backends.CIBackend",
    "django.contrib.auth.backends.ModelBackend",
]
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "es"
