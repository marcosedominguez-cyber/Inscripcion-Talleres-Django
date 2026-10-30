# Validación de horarios y plazos — CU #4

## Alcance y base

Entrega completa de las tareas #13–#17 sobre `main` en `c5f2083`.
Incluye la primera entrega fusionada en el PR #62 y se integra con las
cancelaciones del PR #61 y el diseño join.a.workshop del PR #63.

| Tarea | Comportamiento comprobado |
| --- | --- |
| #13 | Inicio y fin obligatorios, conservación de fecha/hora y duración válida. |
| #14 | Catálogo, inscripción, espera y promoción comparten el mismo límite. |
| #15 | Se rechaza una solicitud que se cruza con otra confirmación de la persona. |
| #16 | API, catálogo y menú muestran el motivo de plazo o superposición. |
| #17 | Pruebas de límites, rechazos sin cambios, promociones y concurrencia real. |

## Fechas y horas (#13)

Se mantienen los campos existentes `fecha_inicio` y `fecha_fin`, las fechas en
UTC y su presentación en `America/La_Paz`. El modelo, el formulario y el servicio
aplican `error_duracion`: fin posterior al inicio, entre 24 horas y 7 días,
incluidos los dos límites. Un dato inválido se rechaza antes de consumir un
código de taller. No se agrega ni modifica ningún campo o migración.

## Plazo (#14)

`inscripcion_abierta` mantiene el criterio de aceptación de #4 y TAL-RT-01
en `docs/sesion_06_requisitos.md`: se permite el instante de un minuto antes.
El reloj es el del servidor y los segundos no se redondean.

| Solicitud para inicio a las 12:00 | Resultado del plazo |
| --- | --- |
| 11:58:59 | Puede continuar |
| 11:59:00 | Puede continuar: límite incluido |
| 11:59:01 | Fuera de plazo |
| 12:00:00 o después | Fuera de plazo |

La aceptación también requiere cumplir las demás reglas. El catálogo usa
la misma función que el servicio. La promoción se comprueba en el momento de
intentar confirmar; una solicitud previa en espera no permite saltar el cierre.
Una cancelación sigue permitida hasta el inicio, según la regla existente,
aunque ya no se pueda promover a alguien durante el último minuto.

## Superposición (#15)

La regla pura `horarios_superpuestos` compara fechas completas:
`inicio_a < fin_b` y `inicio_b < fin_a`. Detecta cruce parcial, contención y
horarios idénticos, también entre días y zonas horarias distintas.

Se adopta el criterio de intervalos adyacentes sin tiempo compartido: un taller
que termina exactamente cuando comienza el otro no se solapa. La entrevista
dejaba pendiente ese extremo; no se añade un margen de traslado no definido.
Si el cliente exige otro criterio, se cambia esta función y sus pruebas.

`buscar_superposicion` consulta solo confirmaciones de la misma persona y
excluye el taller solicitado. Una espera no equivale a una confirmación.
Las cancelaciones permanecen en el historial, pero no bloquean nuevas
inscripciones por horarios. La solicitud incompatible se rechaza antes de
crear registros, modificar plazas o cambiar el contador del participante.

La inscripción normal, la solicitud de espera y la promoción usan la misma
validación. La promoción recorre el orden de fecha e ID de la espera y confirma
a la primera persona que cumpla plazo, aprobación, bloqueo y horarios.
Las incompatibles permanecen en espera, sin cancelarlas ni penalizarlas.
Este criterio conserva FIFO entre solicitudes habilitadas; si no hay ninguna,
la plaza queda libre y la cancelación informa el motivo sin revelar la identidad
de otras personas.

El Admin mantiene la consulta de inscripciones; no permite altas, cambios de
estado o borrados directos que evadan el servicio o el historial de cancelación.
Las operaciones se realizan desde la aplicación o el menú mediante los servicios.

## Mensajes (#16)

- Plazo: indica que está vencido, el instante límite y la zona horaria.
- Superposición: identifica el taller confirmado que impide la solicitud y
  muestra su intervalo y zona horaria.
- La API conserva el formato `detail` con estado HTTP 409.
- El catálogo muestra el motivo incluso si falla su actualización posterior.
- El menú captura el mismo error de negocio sin mostrar un traceback.

Se preservan las validaciones de sesión, perfil, CSRF, aprobación, duplicados,
plazas y bloqueos. Las comprobaciones en memoria de `proyecto/reglas_*.py`
siguen siendo una referencia histórica; el menú operativo usa el servicio Django.

## Transacciones y concurrencia (#17)

La comprobación y la escritura ocurren dentro de la transacción con reintentos
existente. Además del taller, se escribe el documento del participante para
que dos solicitudes suyas a talleres distintos generen conflicto de escritura.
Se sigue el patrón existente de dos escrituras reales con valores opuestos,
utilizando el contador de cancelaciones: su valor final no cambia al inscribirse.
Una cancelación sí mantiene su incremento de negocio habitual.

Ante un conflicto transitorio se vuelve a consultar y validar. Esto impide que
dos lecturas simultáneas sin confirmaciones permitan después dos horarios
incompatibles. La promoción también serializa la escritura de su participante.

En respuesta a `sospechoso.pdf`, las comprobaciones de persistencia y concurrencia
se ejecutan con MongoDB real en `tests/integracion/test_flujos.py`. Incluyen el
cierre exacto, rechazo sin cambios, promoción de personas habilitadas y solicitudes
simultáneas. Los recorridos de `tests/e2e/test_recorridos.py` verifican además
React, Django y MongoDB juntos, sin simular sus respuestas.

## Comprobación reproducible

La reorganización general mantiene 90 casos en todo el proyecto. El inventario,
la distribución y la preparación de MongoDB se documentan en [pruebas.md](pruebas.md).
Desde la raíz, con las dependencias y Chromium instalados:

```bash
python scripts/ejecutar_pruebas.py --completa
```

La ejecución completa utiliza un replica set MongoDB local temporal por defecto.
Atlas se admite mediante `MONGODB_TEST_URI` de un entorno de pruebas y una base
nueva generada por el ejecutor. El `.env` de la aplicación no se carga. Las pruebas
unitarias por sí solas no acreditan persistencia, concurrencia ni conexión a Atlas.
