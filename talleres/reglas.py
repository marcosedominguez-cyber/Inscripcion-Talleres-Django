"""Reglas de negocio compartidas por modelos, formularios, API y servicios."""

from datetime import timedelta

CUPO_MINIMO = 4
CUPO_MAXIMO = 40
DURACION_MINIMA = timedelta(hours=24)
DURACION_MAXIMA = timedelta(days=7)
MARGEN_CIERRE_INSCRIPCION = timedelta(seconds=60)
LIMITE_CANCELACIONES_CONSECUTIVAS = 3


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
    # El criterio de aceptación admite las 11:59 para un inicio a las 12:00.
    return ahora <= limite_inscripcion(fecha_inicio)


def horarios_superpuestos(inicio, fin, otro_inicio, otro_fin):
    """Los extremos adyacentes no comparten tiempo de asistencia."""
    return inicio < otro_fin and otro_inicio < fin


def limite_espera(cupos):
    """Máximo entero que no supera el veinte por ciento."""
    return cupos // 5


def cuenta_bloqueada_para_inscripciones(cancelaciones_consecutivas, *, bloqueado=False):
    """Combina el estado persistido con la regla histórica del contador.

    El campo ``bloqueado`` es el estado efectivo. El contador se conserva como
    respaldo para documentos anteriores a la migración que aún no tengan el
    campo y para que la regla automática siga funcionando durante el relleno.
    """
    return bool(bloqueado) or (
        (cancelaciones_consecutivas or 0) >= LIMITE_CANCELACIONES_CONSECUTIVAS
    )


def cancelacion_abierta(fecha_inicio, ahora):
    """La cancelación se permite mientras el taller no haya comenzado."""
    return ahora < fecha_inicio
