"""Servicios de negocio para gestionar participantes, talleres e inscripciones."""

import time
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import F
from django.utils import timezone
from django_mongodb_backend.transaction import atomic

from talleres.consultas import cupos_disponibles
from talleres.models import Contador, Inscripcion, Usuario, Taller
from talleres.reglas import inscripcion_abierta


class ErrorNegocioTalleres(Exception):
    """Clase base para errores de negocio emitidos por los servicios web."""


class DatosParticipanteInvalidosError(ErrorNegocioTalleres, ValueError):
    """Los datos del participante no cumplen las reglas de la aplicación web."""


class InscripcionError(ErrorNegocioTalleres):
    """Error base de las operaciones web de inscripción."""


class ParticipanteNoEncontradoError(InscripcionError, LookupError):
    """No existe el participante solicitado."""


class TallerNoEncontradoError(InscripcionError, LookupError):
    """No existe el taller solicitado."""


class InscripcionDuplicadaError(InscripcionError):
    """El participante ya está inscrito en el taller."""


class CupoAgotadoError(InscripcionError):
    """El taller no tiene plazas disponibles."""


class TallerNoAprobadoError(InscripcionError):
    """El taller todavía no fue aprobado para inscripción."""


class PlazoInscripcionVencidoError(InscripcionError):
    """El plazo de inscripción ya venció."""


def transaccion_con_reintentos(funcion):
    """Reintenta transacciones que fallan con una etiqueta transitoria."""
    @wraps(funcion)
    def ejecutar(*args, **kwargs):
        for intento in range(5):
            try:
                with atomic():
                    return funcion(*args, **kwargs)
            except DatabaseError as error:
                causa = error
                transitorio = False
                while causa is not None:
                    etiqueta = getattr(causa, "has_error_label", None)
                    if etiqueta and etiqueta("TransientTransactionError"):
                        transitorio = True
                    causa = causa.__cause__
                if not transitorio or intento == 4:
                    raise
                time.sleep(0.05 * (intento + 1))
    return ejecutar


def _preparar_contador(nombre):
    # La primera creación se realiza fuera de la transacción de negocio.
    try:
        Contador.objects.get_or_create(nombre=nombre)
    except IntegrityError:
        if not Contador.objects.filter(nombre=nombre).exists():
            raise


def _siguiente_codigo(nombre, prefijo):
    Contador.objects.filter(nombre=nombre).update(valor=F("valor") + 1)
    return f"{prefijo}-{Contador.objects.get(nombre=nombre).valor:03d}"


def registrar_participante(nombre, ci):
    if not nombre.strip():
        raise DatosParticipanteInvalidosError("El nombre del participante es obligatorio.")
    participante = Usuario(
        nombre=nombre.strip(), ci=ci, rol=Usuario.Rol.PARTICIPANTE
    )
    participante.full_clean()
    return _guardar_participante(participante)


@transaccion_con_reintentos
def _guardar_participante(participante):
    participante.save()
    return participante


@transaccion_con_reintentos
def _crear_taller(datos):
    taller = Taller(codigo=_siguiente_codigo("talleres", "T"), **datos)
    taller.full_clean()
    taller.save()
    return taller


def registrar_taller(nombre, cupos, fecha_inicio, fecha_fin, descripcion="", *,
                     instructor=None):
    # Ninguna alta del servicio se publica antes de una decisión administrativa.
    datos = dict(nombre=nombre, cupos=cupos, fecha_inicio=fecha_inicio,
                 fecha_fin=fecha_fin, descripcion=descripcion,
                 instructor=instructor,
                 estado_aprobacion=Taller.Aprobacion.PENDIENTE)
    # Validar antes de tocar la secuencia; no consulta unicidad del código provisional.
    Taller(codigo="pendiente", **datos).full_clean(
        validate_unique=False, validate_constraints=False
    )
    _preparar_contador("talleres")
    return _crear_taller(datos)


def proponer_taller(instructor, nombre, cupos, fecha_inicio, fecha_fin, descripcion=""):
    if instructor.rol != Usuario.Rol.INSTRUCTOR:
        raise ValidationError({"instructor": "Solo un instructor puede proponer talleres."})
    return registrar_taller(
        nombre, cupos, fecha_inicio, fecha_fin, descripcion, instructor=instructor
    )


@transaccion_con_reintentos
def actualizar_taller(taller, cambios):
    for campo, valor in cambios.items():
        setattr(taller, campo, valor)
    taller.estado_aprobacion = Taller.Aprobacion.PENDIENTE
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos"))
    confirmadas = len(list(Inscripcion.objects.filter(
        taller_id=taller.pk, estado=Inscripcion.Estado.CONFIRMADA
    ).values_list("pk", flat=True)))
    if taller.cupos < confirmadas:
        raise ValidationError({
            "cupos": (
                f"No se puede reducir el cupo a {taller.cupos}: hay "
                f"{confirmadas} inscripciones confirmadas."
            )
        })
    taller.full_clean()
    taller.save()
    return taller


@transaccion_con_reintentos
def inscribir_participante(ci, codigo_taller):
    try:
        participante = Usuario.objects.get(
            ci=ci,
            rol=Usuario.Rol.PARTICIPANTE,
        )
    except Usuario.DoesNotExist:
        raise ParticipanteNoEncontradoError(
            f"No existe un participante con la CI {ci!r}."
        ) from None
    try:
        taller = Taller.objects.get(codigo=codigo_taller)
    except Taller.DoesNotExist:
        raise TallerNoEncontradoError(
            f"No existe un taller con el código {codigo_taller!r}."
        ) from None
    if taller.estado_aprobacion != Taller.Aprobacion.APROBADO:
        raise TallerNoAprobadoError("El taller todavía no está aprobado para inscripciones.")
    if not inscripcion_abierta(taller.fecha_inicio, timezone.now()):
        raise PlazoInscripcionVencidoError(
            "La inscripción cierra un minuto antes del inicio del taller."
        )
    if Inscripcion.objects.filter(participante=participante, taller=taller).exists():
        raise InscripcionDuplicadaError("El participante ya está inscrito en este taller.")
    if cupos_disponibles(taller) == 0:
        raise CupoAgotadoError("El taller no tiene cupos disponibles.")
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos"))
    try:
        return Inscripcion.objects.create(participante=participante, taller=taller)
    except IntegrityError:
        raise InscripcionDuplicadaError(
            "El participante ya está inscrito en este taller."
        ) from None
