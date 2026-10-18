"""Operaciones del menú sobre MongoDB, conservando los errores del dominio."""

import time
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import F, Q
from django_mongodb_backend.transaction import atomic

from proyecto.reglas_inscripciones import (
    CupoAgotadoError, InscripcionDuplicadaError,
    ParticipanteNoEncontradoError, TallerNoEncontradoError,
)
from proyecto.reglas_usuarios import DatosParticipanteInvalidosError
from talleres.models import Contador, Inscripcion, Usuario, Taller


def _transaccion(funcion):
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


@_transaccion
def _crear_participante(nombre):
    participante = Usuario(codigo=_siguiente_codigo("participantes", "P"), nombre=nombre)
    participante.full_clean()
    participante.save()
    return participante


def registrar_participante(nombre):
    if not nombre.strip():
        raise DatosParticipanteInvalidosError("El nombre del participante es obligatorio.")
    _preparar_contador("participantes")
    return _crear_participante(nombre.strip())


@_transaccion
def _crear_taller(datos):
    taller = Taller(codigo=_siguiente_codigo("talleres", "T"), **datos)
    taller.full_clean()
    taller.save()
    return taller


def registrar_taller(nombre, cupos, fecha_inicio, fecha_fin, descripcion="", *,
                     instructor=None):
    # Ninguna alta del servicio se publica antes de una decisión administrativa.
    # El parámetro opcional conserva la firma anterior de CLI/servicios.
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


def cupos_disponibles(taller):
    # count() del backend 6.0 usa $unionWith, no admitido en transacciones.
    confirmadas = len(list(Inscripcion.objects.filter(
        taller_id=taller.pk, estado=Inscripcion.Estado.CONFIRMADA
    ).values_list("pk", flat=True)[:taller.cupos]))
    return max(taller.cupos - confirmadas, 0)


@_transaccion
def inscribir_participante(codigo_participante, codigo_taller):
    try:
        participante = Usuario.objects.get(
            Q(codigo=codigo_participante) | Q(ci=codigo_participante),
            rol=Usuario.Rol.PARTICIPANTE,
        )
    except Usuario.DoesNotExist:
        raise ParticipanteNoEncontradoError(
            f"No existe un participante con el ID {codigo_participante!r}."
        ) from None
    try:
        taller = Taller.objects.get(codigo=codigo_taller)
    except Taller.DoesNotExist:
        raise TallerNoEncontradoError(
            f"No existe un taller con el ID {codigo_taller!r}."
        ) from None
    # Todas las solicitudes del mismo taller escriben el mismo documento.
    # Un conflicto hace reintentar toda la transacción con un estado actualizado.
    Taller.objects.filter(pk=taller.pk).update(revision=F("revision") + 1)
    if Inscripcion.objects.filter(participante=participante, taller=taller).exists():
        raise InscripcionDuplicadaError("El participante ya está inscrito en este taller.")
    if cupos_disponibles(taller) == 0:
        raise CupoAgotadoError("El taller no tiene cupos disponibles.")
    return Inscripcion.objects.create(participante=participante, taller=taller)
