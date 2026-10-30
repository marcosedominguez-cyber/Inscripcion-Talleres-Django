# Suite de pruebas del proyecto

## Alcance y distribución

La base de esta reorganización es `main` en `687bb90`: incluye horarios y plazos
del PR #64, bloqueos y administración del PR #70, y notificaciones del PR #71.
En esa versión se recogían 240 casos de Python (13 requerían MongoDB) y 30 de
React: 270 casos entre ambos ejecutores.

La suite actual recoge 108 casos reales. No se conservan pruebas antiguas fuera
del recolector para aparentar la reducción. Se retiraron duplicados de las
mismas reglas, comprobaciones repetidas de estructura y pruebas del prototipo
en memoria cuyo flujo actual utiliza los servicios Django. Los recorridos de
registro, inscripción y cancelación pasan a probarse con persistencia real.

| Nivel | Ubicación | Casos | Proporción |
| --- | --- | ---: | ---: |
| Unitarias Python | `tests/unitarios/` | 69 | 63,89 % |
| Unitarias React | `frontend/src/**/*.test.jsx` | 12 | 11,11 % |
| Integración MongoDB | `tests/integracion/` | 23 | 21,30 % |
| End to end | `tests/e2e/` | 4 | 3,70 % |
| Total | Ambos ejecutores | 108 | 100 % |

Las 81 unitarias suman el 75 %. La integración aporta 23 casos y los recorridos
end to end, 4. Cada fila parametrizada es
un caso independiente, con su propio nombre y resultado. El ejecutor verifica
los cuatro conteos en los informes JUnit y rechaza resultados con omisiones.

## Matriz de reglas y recorridos

| Regla o comportamiento | Comprobación principal |
| --- | --- |
| Cupos 4–40 y duración 24 h–7 días; fechas obligatorias | Unitarias de horarios y gestión; creación desde navegador |
| Cierre inclusivo a 60 s del inicio | Tres casos reales antes, en y después del límite; catálogo, inscripción, espera y promoción |
| Superposición, contención, adyacencia y zonas horarias | Unitarias de reglas; API real rechaza sin ocupar plaza ni modificar la inscripción anterior |
| Última plaza, duplicados y espera del 20 % | Integración con capacidad completa, rechazos y orden conservado |
| FIFO entre personas habilitadas | Promoción real conserva bloqueados e incompatibles en espera y confirma a la siguiente persona |
| Cancelaciones, historial y bloqueo por tercera cancelación | Integración de todo el ciclo; cancelación sin promoción si ya venció el plazo |
| Bloqueo manual y rehabilitación | Regla unitaria, integración y recorrido administrativo en navegador |
| Identidad desde sesión, propiedad del instructor y CSRF | Unitarias de API y cliente Django con cookies y validación CSRF reales |
| Roles públicos y ausencia de privilegios administrativos | Registro real; unitarias de formularios y privilegios inyectados |
| Borrados administrativos prohibidos | Seis casos independientes: GET/POST de usuario, taller e inscripción |
| Auditoría y cambios de aprobación | Unitarias de mensajes y notificación; aprobación administrativa real desde navegador |
| Transacción individual de talleres en Admin | Nueve pruebas de integración: edición, alta, CSRF, permisos, formulario inválido, sin cambios, rollback por auditoría y anidamiento |
| Avisos de promoción, edición y bloqueo | Servicios reales con persistencia; lectura, idempotencia, privacidad y paginación |
| Recuperación de errores del catálogo y de la bandeja | Componentes React con dependencias aisladas y mensajes del servidor conservados |
| Solicitudes simultáneas | Dos casos de concurrencia real: última plaza y horarios cruzados de la misma persona |
| Migraciones 0003 y 0008 | Preparación desde esquema vacío y comprobación de conservación de datos e índices |
| Compatibilidad del menú CLI actual | Registro con CI y cancelación/historial a través de los servicios Django |

Los cuatro recorridos completos son:

1. Registro público, sesión persistente, bloqueo manual, rehabilitación y logout.
2. Inscripción y rechazo visible de un horario superpuesto.
3. Lista de espera, cancelación de un titular, promoción y lectura de su aviso.
4. Propuesta del instructor, aprobación desde Admin y publicación en el catálogo.

Estos recorridos utilizan Chromium, la interfaz React compilada, peticiones HTTP
reales, sesiones Django y MongoDB. Los servicios, respuestas HTTP y persistencia
no se sustituyen por mocks. Las pruebas de límites solo fijan el reloj para
poder reproducir el instante exacto.

## Preparación

Se utiliza Python compatible con las dependencias del proyecto y Node 22 o
posterior. La aplicación conserva sus dependencias y su configuración normales;
Playwright se agrega a `requirements-ci.txt` para las pruebas de desarrollo.

```bash
python -m pip install -r requirements-ci.txt
npm --prefix frontend ci
python -m playwright install chromium
```

En Linux puede ser necesario `python -m playwright install --with-deps chromium`.

### Ejecución rápida, sin base de datos

```bash
python scripts/ejecutar_pruebas.py
```

Ejecuta las 69 unitarias Python y las 12 de React. Informa **81**, nunca 108.
Para una comprobación individual se pueden usar `python -m pytest
tests/unitarios -q` y `npm --prefix frontend test`.

### Las 108 con MongoDB local

Con `mongod` instalado en PATH:

```bash
python scripts/ejecutar_pruebas.py --completa
```

Si el binario está en otra ubicación:

```bash
python scripts/ejecutar_pruebas.py --completa --mongod /ruta/a/mongod
```

El ejecutor inicia su propio replica set en loopback, en un puerto libre y con
datos temporales. Al terminar elimina la base generada, detiene el proceso que
inició y retira sus archivos temporales. No necesita Docker ni una conexión a
la base del equipo. En macOS, MongoDB Community puede instalarse con Homebrew:

```bash
brew tap mongodb/brew
brew install mongodb-community@8.0
```

No hace falta iniciarlo como servicio; el ejecutor lo prepara para esta ejecución.

### Las 108 contra un entorno de pruebas en Atlas

Se proporciona `MONGODB_TEST_URI` como variable de entorno, usando una cuenta
autorizada para bases de pruebas y una IP admitida por ese clúster. Después se
ejecuta el mismo comando `--completa`. La URI no se escribe en código ni se sube
a Git. No se usan `MONGODB_URI`, `MONGODB_DATABASE` ni el `.env` de la aplicación.

Cada ejecución genera `test_talleres_<identificador>`, verifica que esté vacía,
aplica migraciones y al final elimina esa base. Las pruebas de migración eliminan
colecciones dentro de esa base exclusiva para reconstruir esquemas anteriores.
Por eso la cuenta debe permitir esas operaciones en el entorno de pruebas.
Tener la página web de Atlas abierta no interviene en la conexión.

La validación de esta entrega se realizó con MongoDB local; ejecutar en Atlas
requiere verificar allí permisos, conectividad y compatibilidad de transacciones.

## Corrección detectada con el recorrido real

El listado del Admin trae relaciones del instructor mediante `select_related`.
Reutilizar ese queryset para `update()` provocaba `NotSupportedError` en MongoDB
al aprobar una propuesta. La actualización ahora usa `Taller.objects.filter()`
por cada taller seleccionado, conserva el filtro de estado pendiente y mantiene
la transacción, auditoría y notificaciones existentes. El cuarto recorrido
completo prueba la regresión sin simular la base.

## Evidencias y límites

El ejecutor escribe cuatro informes JUnit y `evidencias/resumen-pruebas.json`,
que contiene los nombres de todos los casos ejecutados y sus cantidades. Si
un recorrido de navegador falla, se guarda captura y traza en `evidencias/e2e/`.
Esos archivos de ejecución están ignorados por Git y CI los conserva como artefactos.

`python -m pytest -q` con la configuración predeterminada ejecuta solo 69 casos
Python y omite los 27 que necesitan otro entorno. No cuenta las 12 pruebas React
ni acredita la ejecución completa. CI ejecuta `--completa` con MongoDB local y
Chromium, y detiene el trabajo ante un fallo, una omisión o un conteo diferente.

La reducción prioriza las reglas y recorridos de la matriz; no promete cubrir
todas las ramas del código, cada variante visual ni todas las condiciones de
infraestructura de Atlas. Cuando cambien requisitos, deben revisarse los casos
y acordarse de nuevo su distribución, conservando una cobertura útil.
