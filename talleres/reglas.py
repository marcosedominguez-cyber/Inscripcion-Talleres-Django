"""Reglas de negocio compartidas por modelos, formularios, API y servicios."""

from datetime import timedelta

CUPO_MINIMO = 4
CUPO_MAXIMO = 40
DURACION_MINIMA = timedelta(hours=24)
DURACION_MAXIMA = timedelta(days=7)
MARGEN_CIERRE_INSCRIPCION = timedelta(seconds=60)


def error_duracion(fecha_inicio, fecha_fin):
    if not fecha_inicio or not fecha_fin:
        return None
    if fecha_fin <= fecha_inicio:
        return "El fin debe ser posterior al inicio del taller."
    duracion = fecha_fin - fecha_inicio
    if duracion < DURACION_MINIMA:
        return "La duración mínima del taller es de 24 horas."
    if duracion > DURACION_MAXIMA:
        return "La duración máxima del taller es de 7 días."
    return None


def limite_inscripcion(fecha_inicio):
    return fecha_inicio - MARGEN_CIERRE_INSCRIPCION


def inscripcion_abierta(fecha_inicio, ahora):
    return ahora < limite_inscripcion(fecha_inicio)


def limite_espera(cupos):
    """Máximo entero que no supera el veinte por ciento."""
    return cupos // 5
