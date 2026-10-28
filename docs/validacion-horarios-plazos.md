# Validación de horarios y plazos — primera entrega

## Alcance

Revisión de las tareas #13 y #14 del caso de uso #4. La segunda entrega
queda reservada para superposición (#15), mensajes de rechazo (#16) y
las pruebas completas de plazo y superposición (#17).

## Inicio y fin del taller (#13)

Los campos `fecha_inicio` y `fecha_fin` ya existen como fechas con hora.
No se agregan columnas ni migraciones. Se verifica que el formulario de
gestión y el modelo conserven ambas fechas y horas en `America/La_Paz`.

Se mantienen las reglas existentes compartidas en `talleres/reglas.py`:

- Fin posterior al inicio.
- Duración mínima de 24 horas y máxima de 7 días, incluidos ambos límites.
- Inicio y fin obligatorios.
- Un horario inválido se rechaza antes de consumir un código o guardar el taller.

## Plazo de inscripción (#14)

El criterio de aceptación del caso de uso #4 y TAL-RT-01 en
`docs/sesion_06_requisitos.md` permiten la solicitud a las 11:59 para un
taller de las 12:00. Se conserva el cierre un minuto antes, incluyendo
el instante límite. Esto corrige el rechazo previo de las 11:59 exactas.

| Hora de solicitud, con inicio a las 12:00 | Resultado del plazo |
| --- | --- |
| 11:58:59 | Puede continuar |
| 11:59:00 | Puede continuar: límite incluido |
| 11:59:01 | Fuera de plazo |
| 12:00:00 o después | Fuera de plazo |

La aceptación final también requiere cumplir las otras reglas de inscripción.
El límite es un instante preciso; no se redondean los segundos al minuto.

`inscripcion_abierta` es la regla temporal compartida por el catálogo y el
servicio persistente. La consulta primero obtiene talleres aprobados que
todavía no comenzaron y aplica esa misma función con un único valor de
`ahora`. Así evita mantener otra comparación de cierre en la consulta.

La inscripción normal y la lista de espera utilizan `_registrar_solicitud`,
que ya llama a esa regla. El menú de terminal llama al mismo servicio.
El servidor determina la hora; el cliente no puede enviarla para ampliar el plazo.

## Revisión de sospechoso.pdf

El informe pide compartir la regla de cierre entre consulta y servicio.
Se atiende ese hallazgo dentro del alcance de #14. El criterio de límite
incluido se fundamenta en los requisitos del proyecto, porque el informe
solicita aclararlo y no fija por sí mismo ese criterio.

El informe también advierte que las pruebas con mocks no acreditan consultas
ni transacciones reales en MongoDB. Las comprobaciones de esta entrega son
unitarias, de validación y de API con dependencias simuladas; no prueban
concurrencia ni persistencia real. No se ejecutan contra Atlas.

Los demás hallazgos del informe quedan fuera de estas dos tareas.

## Comprobación

Desde la raíz del repositorio, con las dependencias de `requirements.txt`:

```bash
python -m pytest -q
git diff --check
```

Pruebas específicas añadidas:

- `tests/test_horarios_taller.py`: obligatoriedad, conservación de fecha/hora,
  límites de duración y rechazos consistentes en modelo, formulario y servicio.
- `tests/test_plazo_catalogo.py`: catálogo y regla comparten el límite y comparan
  instantes equivalentes en distintas zonas horarias.
- `tests/test_plazo_inscripciones.py`: inscripción, espera y sus APIs respetan
  el mismo plazo; los rechazos no crean inscripciones ni actualizan el taller.

Se ajustan las pruebas anteriores que esperaban rechazar el límite exacto.
No se marca el caso de uso #4 ni la tarea #17 como completos en esta entrega.
