# Sistema de inscripción a talleres

Aplicación para publicar talleres con cupos limitados, revisar propuestas de instructores e inscribir participantes. El repositorio conserva dos formas de uso: una interfaz web React servida por Django y un menú de terminal anterior implementado en `proyecto/main.py`.

### Implementado en el código

- Registro de cuentas de participante o instructor con nombre de usuario, CI numérica y contraseña; inicio de sesión con CI y contraseña; y cierre de sesión con sesión Django.
- El registro público no permite asignar rol administrador ni privilegios de `staff`.
- Catálogo web de talleres aprobados, futuros y con plazas disponibles, visible a participantes autenticados.
- Inscripción del participante autenticado. El servidor comprueba rol, taller aprobado, fecha límite (un minuto antes del inicio), duplicados y plazas disponibles. La capacidad se controla dentro de una transacción.
- Panel de instructor para proponer talleres, ver sus propuestas y plazas, y editar una propuesta propia. Al editar, vuelve a estado pendiente de aprobación.
- Django Admin (`/admin/`) para personal autorizado con rol administrador. Permite consultar registros y usar acciones para aprobar o rechazar talleres pendientes.
- En la aplicación de terminal hay registro de participantes y talleres, listado de ambos, consulta de inscripciones y alta de inscripción. Las inscripciones del menú también requieren taller aprobado.
- Persistencia MongoDB mediante el backend Django para MongoDB. Los datos de negocio usan las colecciones `participantes`, `talleres`, `inscripciones` y `contadores`.

### No implementado en el estado inspeccionado

- Lista de espera, cancelación de inscripción, promoción automática de participantes y notificaciones.
- Restricciones de superposición de horarios entre talleres.
- Historial web de inscripciones del participante.

## Arquitectura y tecnologías

- **Backend:** Python y Django 6, con rutas JSON para cuentas, catálogo/inscripción de participantes y gestión del instructor. Django también sirve el `index.html` compilado de React y expone Django Admin.
- **Frontend:** React 19 y Vite 7. Durante desarrollo, Vite sirve la interfaz en el puerto 5173 y reenvía `/api` a Django en `127.0.0.1:8000`. En modo compilado, Django busca archivos en `frontend/dist`.
- **Base de datos:** MongoDB con `django-mongodb-backend`. La configuración principal lee una URI y el nombre de la base desde `.env`. Atlas debe permitir conexiones desde la IP del desarrollador y usar un usuario de base de datos válido.
- **Menú de terminal:** `proyecto/main.py` utiliza los modelos y servicios Django para acceder a la misma persistencia. La implementación de reglas en memoria de `proyecto/reglas*.py` se conserva para pruebas y referencia.

Rutas principales: `api/cuentas/`, `api/participantes/`, `api/gestion/` y `admin/` (ver [config/urls.py](config/urls.py)).

## Requisitos previos

- **Python 3.12 o posterior.** El flujo de CI usa Python 3.12 y las dependencias fijan Django 6.0, que requiere Python 3.12 o posterior.
- **Node.js y npm:** necesarios para instalar y servir/compilar React. El repositorio no fija versiones exactas en `package.json`; usa una versión de Node.js compatible con Vite 7 y npm compatible con el lockfile `frontend/package-lock.json`.
- **MongoDB Atlas** (o una instancia MongoDB compatible con el backend). La aplicación requiere acceso a una base y credenciales propias. Para operaciones transaccionales, el servidor debe admitir transacciones; configura un clúster Atlas compatible.
- **Git** para clonar el repositorio.
- Linux se usa en los comandos de esta guía. En macOS los comandos de entorno virtual son iguales. En Windows PowerShell, la activación es `.venv\Scripts\Activate.ps1` y la copia de plantilla es `Copy-Item .env.example .env`.

## Instalación desde cero

Los archivos de dependencias confirmados son [requirements.txt](requirements.txt), [requirements-ci.txt](requirements-ci.txt) y [frontend/package.json](frontend/package.json). Para la aplicación web instala `requirements.txt` y las dependencias npm desde `frontend/`.

```bash
git clone <URL_DEL_REPOSITORIO>
cd Inscripcion-Talleres-Django

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env

cd frontend
npm ci
cd ..
```

Reemplaza `<URL_DEL_REPOSITORIO>` con la URL de clonación proporcionada para este repositorio. Si ya tienes un `.env` configurado, no lo reemplaces con la plantilla.

## Variables de entorno y MongoDB

`config/settings.py` carga `.env` desde la raíz mediante `python-dotenv`. La plantilla existente es [.env.example](.env.example); copia esa plantilla y configura valores de tu propia instancia. 

| Variable | Uso |
| --- | --- |
| `MONGODB_URI` | URI de conexión de tu clúster/servidor MongoDB. Incluye el usuario y la clave del usuario de base de datos en el formato entregado por Atlas. |
| `MONGODB_DATABASE` | Nombre de la base que usará la aplicación. |
| `DJANGO_DEBUG` | Activa el modo de depuración solo para desarrollo local (`True`/`False`). |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos por Django, separados por comas. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Orígenes confiables para CSRF, separados por comas; para desarrollo se incluyen los orígenes locales del frontend. |

En Atlas, crea un usuario de base de datos con permisos apropiados sobre la base, permite la IP de salida de tu equipo en Network Access y usa la URI correspondiente a tu clúster. Comprueba que el clúster y el backend admiten las transacciones que usa el servicio de inscripción. 

## Ejecución

### 1. Preparar la base

Con `.env` configurado y la base propia accesible, aplica las migraciones del proyecto desde la raíz:

```bash
source .venv/bin/activate
python manage.py migrate
```

Este comando realiza escrituras en la base configurada. Verifica `MONGODB_DATABASE` y `MONGODB_URI` antes de ejecutarlo. Esta documentación no lo ejecutó.

### 2. Backend Django

En una terminal, desde la raíz del repositorio y con el entorno virtual activado:

```bash
python manage.py runserver 127.0.0.1:8000
```

Django queda disponible en `http://127.0.0.1:8000/`; el puerto predeterminado de `runserver` es 8000. La raíz sirve la compilación de React si existe; sin ella, Django indica que se debe compilar o iniciar Vite.

### 3. Frontend React/Vite

En otra terminal, desde la carpeta `frontend/`:

```bash
npm run dev
```

Vite está configurado en `127.0.0.1:5173` y usa `strictPort`; abre `http://127.0.0.1:5173/`. Su proxy `/api` apunta a Django en el puerto 8000. Para que las funciones web trabajen juntas, deja ambos procesos activos y configura los orígenes CSRF de `.env` para el origen de Vite. Ejecutar `npm run dev` desde la raíz falla porque el `package.json` está en `frontend/`.

### Interfaz web y administración

- La interfaz React se abre en `http://127.0.0.1:5173/` durante el desarrollo (o en la raíz de Django después de compilar React).
- Django Admin es un acceso separado en `http://127.0.0.1:8000/admin/`. Sirve para administrar registros y aprobar/rechazar propuestas; no es la interfaz de participantes ni de instructores.
- Las cuentas del registro público no pueden entrar en Admin. El código requiere una cuenta activa, `is_staff=True` y perfil con rol `administrador`. No se encontró en el repositorio un comando o procedimiento de bootstrap seguro y completo para crear esa asociación; `createsuperuser` por sí solo no garantiza el perfil requerido. No se incluye un procedimiento inventado.

### Menú de terminal conservado

Con el mismo entorno y `.env`, desde la raíz:

```bash
python -m proyecto.main
```

El menú solicita participantes, talleres, inscripciones y listados; sus fechas se interpretan en UTC. Este flujo usa la configuración principal y la misma base persistente. Las propuestas creadas por el menú también quedan pendientes hasta su aprobación en Admin antes de permitir nuevas inscripciones.

## Pruebas y validación

La configuración de Python usa **pytest y pytest-django** (`pytest.ini`). Por defecto, `config/settings_test_api_participantes.py` configura SQLite en memoria, sin cargar `.env` ni conectar a Atlas. El workflow de CI instala `requirements-ci.txt` y ejecuta tres casos de `tests/test_reglas.py`; eso no representa una ejecución realizada al redactar este README.

Comandos disponibles según la configuración:

```bash
# Backend (selección predeterminada de pytest.ini)
source .venv/bin/activate
python -m pytest

# Frontend (Vitest, configuración en frontend/vite.config.js)
cd frontend
npm test
```

Existe además `config/settings_test_mongodb_local.py`, que apunta a `mongodb://127.0.0.1:27017` y a una base de pruebas local fija; `tests/mongodb/test_migration_estado_aprobacion.py` corresponde a ese nivel. Úsalo únicamente con una instancia local desechable tras revisar qué datos altera. `tests/verificar_atlas.py` requiere Atlas y, según el README anterior, crea y elimina una base temporal `test_cli_*`; no forma parte de la configuración pytest predeterminada.

## Estructura principal

| Ruta | Contenido |
| --- | --- |
| `config/` | Configuración Django, URLs, WSGI/ASGI y settings específicos de pruebas. |
| `cuentas/` | Formularios, servicios, backend CI/contraseña, vistas y rutas de registro/sesión. |
| `talleres/models.py` | Modelos de usuarios/perfiles, talleres, inscripciones y contadores. |
| `talleres/services.py` | Operaciones persistentes, cupos, creación y validaciones de inscripción. |
| `talleres/api_participantes.py`, `consultas_participantes.py` | Catálogo e inscripción API para participantes. |
| `talleres/api_gestion.py`, `urls_gestion.py`, `forms_gestion.py` | Gestión API de propuestas por instructores. |
| `talleres/admin.py`, `admin_site.py` | Administración de registros y acciones de aprobación/rechazo. |
| `talleres/migrations/`, `mongo_migrations/` | Migraciones de los modelos y de apps Django adaptadas al backend MongoDB. |
| `frontend/src/` | Aplicación React, catálogo, panel de instructor, cliente API y pruebas Vitest. |
| `proyecto/main.py`, `proyecto/reglas*.py` | Menú de terminal y reglas de dominio en memoria. |
| `tests/`, `talleres/tests_api_participantes.py` | Pruebas de reglas, cuentas, gestión, API y migraciones. |
| `docs/` | Requisitos, modelos, planificación y notas de arquitectura del proyecto. |


## Solución de problemas

- **`ModuleNotFoundError` o dependencias Python faltantes:** activa `.venv` y ejecuta `python -m pip install -r requirements.txt` desde la raíz.
- **`npm run dev` dice que falta `package.json`:** entra primero a `frontend/` y ejecuta `npm ci`; después vuelve a ejecutar `npm run dev` allí.
- **Vite no puede enlazar el puerto:** el puerto 5173 es estricto. Cierra el proceso que ya lo ocupa o libera ese puerto; la configuración actual no selecciona otro automáticamente.
- **Django no puede enlazar el puerto 8000:** detén el proceso que lo ocupa. Si configuras otro puerto, actualiza también `server.proxy` en `frontend/vite.config.js`; el proxy actual apunta al 8000.
- **Error por variables ausentes:** confirma que existe `.env` en la raíz y que contiene `MONGODB_URI` y `MONGODB_DATABASE`. Django los lee al importar `config/settings.py`; no pegues sus valores en reportes.
- **Atlas no conecta o agota el tiempo:** verifica URI, usuario/contraseña del usuario de base de datos, nombre de base, acceso de red/IP permitida y estado del clúster. Si falla una inscripción, revisa también que el clúster admita transacciones.
- **Error CSRF al enviar formularios:** comprueba que `DJANGO_CSRF_TRUSTED_ORIGINS` incluya exactamente el origen local usado (esquema y puerto) y recarga la página para obtener un token nuevo.
- **Admin muestra acceso denegado:** se requiere usuario activo, `is_staff=True` y perfil de aplicación con rol `administrador`; una cuenta registrada desde la interfaz no cumple esos requisitos automáticamente.
- **La página raíz responde que falta `index.html`:** compila React con `npm run build` desde `frontend/`, o usa el servidor de desarrollo Vite en otra terminal. La compilación no se ejecutó como parte de esta tarea.

