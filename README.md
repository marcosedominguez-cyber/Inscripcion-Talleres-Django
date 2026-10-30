# Sistema de inscripción a talleres

Aplicación para publicar talleres con cupos limitados, revisar propuestas de instructores e inscribir participantes. El repositorio conserva dos formas de uso: una interfaz web React servida por Django y un menú de terminal anterior implementado en `proyecto/main.py`.

### Implementado en el código

- Registro de cuentas de participante o instructor con nombre de usuario, CI numérica y contraseña; inicio de sesión con CI y contraseña; y cierre de sesión con sesión Django.
- El registro público no permite asignar rol administrador ni privilegios de `staff`.
- Catálogo web de talleres aprobados, futuros y con plazas disponibles, visible a participantes autenticados.
- Inscripción del participante autenticado. El servidor comprueba rol, taller aprobado, fecha límite (un minuto antes del inicio, incluido ese instante), duplicados, bloqueo de la cuenta, superposición de horarios y plazas disponibles. La transacción serializa solicitudes de la misma persona y del mismo taller.
- Cancelación de inscripciones confirmadas o en espera antes del inicio. La plaza liberada se asigna a la primera persona habilitada de la lista de espera, verificando plazo, bloqueo y superposición; las solicitudes incompatibles permanecen en espera. El antecedente queda en un historial inmutable con el taller, el estado anterior y la fecha.
- Bloqueo para nuevas inscripciones al acumular tres cancelaciones consecutivas. El contador no se reinicia automáticamente al volver a inscribirse; un administrador puede rehabilitar la cuenta desde Django Admin.
- Reglas de taller: cupo entre 4 y 40 personas y duración entre 24 horas y 7 días; las fechas se almacenan en UTC y se interpretan/muestran en `America/La_Paz`.
- Panel de instructor para proponer talleres, ver sus propuestas y plazas, y editar una propuesta propia. Al editar, vuelve a estado pendiente de aprobación.
- Django Admin (`/admin/`) para personal autorizado con rol administrador. Permite consultar registros y usar acciones para aprobar o rechazar talleres pendientes. Las inscripciones y cancelaciones se consultan sin altas, ediciones o borrados directos: esas operaciones usan los servicios compartidos mediante la aplicación o el menú.
- En la aplicación de terminal hay registro de participantes y talleres, listado de ambos, consulta de inscripciones y alta de inscripción. Las inscripciones del menú también requieren taller aprobado.
- Persistencia MongoDB mediante el backend Django para MongoDB. Los datos de negocio usan las colecciones `participantes`, `talleres`, `inscripciones`, `cancelaciones` y `contadores`; este último mantiene la secuencia de códigos de talleres.

### No implementado en el estado inspeccionado

- Notificaciones a las personas promovidas desde la lista de espera.
- Penalizaciones por cancelaciones tardías o inasistencias.

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
| `SECRET_KEY` | Clave secreta de Django; usa un valor aleatorio y no la publiques. |
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

El menú solicita participantes, talleres, inscripciones y listados; sus fechas se interpretan en la zona horaria `America/La_Paz`. Este flujo usa la configuración principal y la misma base persistente. Las propuestas creadas por el menú también quedan pendientes hasta su aprobación en Admin antes de permitir nuevas inscripciones.

## Pruebas y validación

La configuración de Python usa **pytest y pytest-django** (`pytest.ini`). Por defecto, `config/settings_test_api_participantes.py` configura SQLite en memoria, sin cargar `.env` ni conectar a Atlas. El workflow de CI instala `requirements.txt` y ejecuta la suite completa de backend y frontend; las pruebas con MongoDB local y el script de Atlas no forman parte de esa ejecución.

Comandos disponibles según la configuración:

```bash
# Backend (selección predeterminada de pytest.ini)
source .venv/bin/activate
python -m pytest

# Frontend (Vitest, configuración en frontend/vite.config.js)
cd frontend
npm test
```

Existe además `config/settings_test_mongodb_local.py`, que apunta a `mongodb://127.0.0.1:27017` y a una base de pruebas local fija; `tests/mongodb/test_migration_estado_aprobacion.py` corresponde a ese nivel. Úsalo únicamente con una instancia local desechable tras revisar qué datos altera. `scripts/verificar_atlas.py` requiere Atlas y, según el README anterior, crea y elimina una base temporal `test_cli_*`; no forma parte de la configuración pytest predeterminada.

## Estructura principal

| Ruta | Contenido |
| --- | --- |
| `config/` | Configuración Django, URLs, WSGI/ASGI, settings de pruebas y vista del shell SPA (`vistas.py`). |
| `cuentas/` | Formularios, servicios, backend CI/contraseña, vistas y rutas de registro/sesión. |
| `talleres/models.py` | Modelos de usuarios/perfiles, talleres, inscripciones y contadores. |
| `talleres/reglas.py`, `servicios.py` | Reglas compartidas, casos de uso persistentes, transacciones reintentables y errores web. |
| `talleres/consultas.py` | Consultas de lectura de catálogo, disponibilidad, talleres del instructor y confirmadas. |
| `talleres/api_participantes.py`, `api_gestion.py`, `api_comun.py` | Endpoints de participantes y gestión, más autorización compartida. |
| `talleres/urls.py`, `formularios_gestion.py` | Rutas HTTP y formularios de validación de gestión. |
| `talleres/admin.py`, `admin_site.py` | Administración de registros y acciones de aprobación/rechazo. |
| `talleres/migrations/`, `mongo_migrations/` | Migraciones de los modelos y de apps Django adaptadas al backend MongoDB. |
| `frontend/src/cuentas/`, `gestion/`, `participantes/` | Cliente API y componentes React separados por área funcional; `api.js` contiene el transporte HTTP común. |
| `proyecto/main.py`, `proyecto/reglas*.py` | Menú de terminal y reglas de dominio en memoria; programa independiente. |
| `scripts/` | Verificación manual destructiva contra una base temporal de Atlas; no es una prueba automática. |
| `tests/` | Pruebas web, reglas CLI y pruebas de migración MongoDB local. |
| `docs/` | Requisitos, modelos, planificación y notas de arquitectura del proyecto. |


## Solución de problemas

- **`ModuleNotFoundError` o dependencias Python faltantes:** activa `.venv` y ejecuta `python -m pip install -r requirements.txt` desde la raíz.
- **`npm run dev` dice que falta `package.json`:** entra primero a `frontend/` y ejecuta `npm ci`; después vuelve a ejecutar `npm run dev` allí.
- **Vite no puede enlazar el puerto:** el puerto 5173 es estricto. Cierra el proceso que ya lo ocupa o libera ese puerto; la configuración actual no selecciona otro automáticamente.
- **Django no puede enlazar el puerto 8000:** detén el proceso que lo ocupa. Si configuras otro puerto, actualiza también `server.proxy` en `frontend/vite.config.js`; el proxy actual apunta al 8000.
- **Error por variables ausentes:** confirma que existe `.env` en la raíz y que contiene `SECRET_KEY`, `MONGODB_URI` y `MONGODB_DATABASE`. Django los lee al importar `config/settings.py`; no pegues sus valores en reportes.
- **Atlas no conecta o agota el tiempo:** verifica URI, usuario/contraseña del usuario de base de datos, nombre de base, acceso de red/IP permitida y estado del clúster. Si falla una inscripción, revisa también que el clúster admita transacciones.
- **Error CSRF al enviar formularios:** comprueba que `DJANGO_CSRF_TRUSTED_ORIGINS` incluya exactamente el origen local usado (esquema y puerto) y recarga la página para obtener un token nuevo.
- **Admin muestra acceso denegado:** se requiere usuario activo, `is_staff=True` y perfil de aplicación con rol `administrador`; una cuenta registrada desde la interfaz no cumple esos requisitos automáticamente.
- **La página raíz responde que falta `index.html`:** compila React con `npm run build` desde `frontend/`, o usa el servidor de desarrollo Vite en otra terminal. La compilación no se ejecutó como parte de esta tarea.



### Lista de espera web

El catálogo incluye talleres aprobados con inscripción abierta aunque estén llenos.
El participante puede solicitar espera y consultar su posición al recargar el catálogo.
El instructor consulta la lista ordenada únicamente de sus propios talleres.

- Capacidad: `cupos // 5` (20 % redondeado hacia abajo; cupo 4 admite cero).
- Prioridad: `fecha_solicitud` UTC y ObjectId ascendente para desempatar.
  El desempate es determinista; no promete precedencia temporal entre solicitudes simultáneas.
- Una inscripción por participante y taller, confirmada o en espera.
- Solo se admite espera si no hay plazas; se conserva el cierre un minuto antes del inicio.
- Rechazos no modifican inscripciones. Las solicitudes concurrentes comparten una
  escritura real del taller dentro de una transacción MongoDB con reintentos.
- No se permite reducir cupos por debajo de confirmadas ni de la capacidad
  necesaria para conservar la espera. La promoción se ejecuta dentro de la
  cancelación de una inscripción confirmada; no hay un proceso periódico aparte.

API: `POST /api/participantes/espera/` con `codigo_taller`, identidad desde la sesión;
`GET /api/gestion/talleres/<codigo>/espera/` exclusivo del instructor propietario.
El catálogo devuelve `mi_estado`, `posicion_espera`, `limite_espera` y `lugares_espera`.

### Cancelaciones, historial y bloqueo

- Una inscripción activa (confirmada o en espera) puede cancelarse mientras el taller no haya comenzado.
- La cancelación elimina la inscripción activa y conserva un registro en la colección `cancelaciones` con `codigo_taller`, `nombre_taller`, `estado_anterior` y `fecha_cancelacion`. La re-inscripción posterior crea una solicitud nueva y no borra el antecedente.
- Si se cancela una inscripción confirmada, la primera persona en espera pasa a confirmada respetando `fecha_solicitud` e `id`; no se crea otro registro ni se altera el cupo total.
- Cada cancelación incrementa `Usuario.cancelaciones_consecutivas`. Al llegar a tres se abre un episodio automático en `bloqueos` y la cuenta no puede crear nuevas inscripciones ni solicitudes de espera.
- El panel administrativo permite bloquear participantes con un motivo controlado y rehabilitarlos desde la ficha individual o mediante las acciones masivas. La rehabilitación registra fecha y administrador en el mismo episodio, conserva el historial y solo reinicia el contador cuando este alcanzó el límite, para iniciar un ciclo disciplinario nuevo.
- API: `POST /api/participantes/inscripciones/cancelar/` con `codigo_taller` e identidad desde la sesión. `GET /api/participantes/inscripciones/` devuelve también `cancelaciones`, `cancelaciones_consecutivas`, `limite_cancelaciones` e `inscripciones_bloqueadas`.
- La migración `0007_usuario_cancelaciones_consecutivas_cancelacion.py` agrega el contador y la colección de historial. La migración `0008_usuario_bloqueado_bloqueo.py` agrega `Usuario.bloqueado`, crea `bloqueos` e inicializa el estado de bloqueo de los participantes existentes sin crear historial sintético ni alterar cancelaciones.
- La migración se aplica con `python manage.py migrate` únicamente después de verificar la conexión y las transacciones del entorno. Las pruebas de integración de MongoDB se omiten salvo que se use `--ds=config.settings_test_mongodb_local` contra una instancia local desechable.

Pruebas: `python -m pytest -q`, `npm test` desde frontend, y
`python scripts/verificar_atlas.py` para verificación real en una base temporal.
Las pruebas de cancelación, historial y bloqueo están en `tests/test_cancelaciones.py`.
En entornos Windows restringidos, Vite admite `--configLoader runner`.

La migración `0007` agrega el contador y la colección de historial sin alterar
migraciones históricas. `makemigrations --check` no detecta cambios pendientes.


### Integración de diseño con cancelaciones (PR #61)

La interfaz de join.a.workshop conserva la home, el acceso, el panel del instructor
y el logo de anillos entrelazados. El catálogo incluye las vistas de explorar y
Mis inscripciones, el diálogo de cancelación y los avisos de bloqueo del PR #61.
El enlace de marca vuelve al catálogo desde Mis inscripciones.

Después de actualizar, ejecutar `python manage.py migrate` con el entorno y `.env`
configurados: el PR incorpora `0007_usuario_cancelaciones_consecutivas_cancelacion`.
No es necesario crear otra migración para integrar el diseño.

La suite React comprueba navegación, creación/edición, espera y cancelaciones.
`scripts/verificar_atlas.py` también comprueba en una base temporal la promoción de
la primera persona en espera, la salida de la espera sin liberar plaza confirmada,
el estado de Mis inscripciones y el bloqueo tras tres cancelaciones.
Si Atlas rechaza la conexión TLS o no responde, esa comprobación real no se puede
considerar aprobada; las pruebas unitarias no sustituyen esa verificación.


### Notificaciones al participante (CU #25)

La campana del catálogo y de Mis inscripciones presenta tres categorías:

- Cambios de talleres: avisa a las inscripciones activas, confirmadas o en espera,
  al editar desde React o Django Admin; incluye cambios de aprobación masivos.
- Promoción: avisa solo a la persona que realmente pasa de espera a confirmada.
- Bloqueo: informa el motivo de un nuevo bloqueo administrativo o automático
  por cancelaciones. Reutilizar un bloqueo vigente no vuelve a enviar el aviso.

Las notificaciones se guardan en la colección `notificaciones`, dentro de la
misma transacción que la operación. Una falla revierte también la operación de
negocio; no se anuncia una promoción que no se guardó. Una clave de evento por
participante evita duplicados. Editar sin cambios no crea otro aviso.

La bandeja consulta novedades cada 15 segundos mientras la pestaña está visible,
y al volver a ella. Un aviso emergente aparece durante 10 segundos al llegar
una novedad; después sigue disponible en la campana. No usa correo, permisos
del navegador ni servicios externos.
Los avisos permanecen disponibles después de cerrar sesión y pueden marcarse
individualmente como leídos. Los anteriores se consultan por páginas de 20.

API autenticada: `GET /api/participantes/notificaciones/?antes=<id>` y
`POST /api/participantes/notificaciones/<id>/leer/` (con CSRF).
Cada consulta y actualización se limita al participante de la sesión.

Al actualizar, aplicar `python manage.py migrate`: la migración `0009_notificacion`
crea la colección, el índice de bandeja y la unicidad del evento por participante.
Las notificaciones se generan desde la instalación; no reconstruyen eventos pasados.

Pruebas: `python -m pytest -q`, `npm test -- --configLoader runner` desde frontend,
y `python scripts/verificar_atlas.py`. Esta última utiliza una base temporal y
comprueba los tres tipos, lectura persistente, idempotencia y rollback real ante
una entrega fallida simulada; elimina únicamente su base temporal al terminar.
