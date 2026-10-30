"""Servicios de negocio para gestionar participantes, talleres e inscripciones."""

import time
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError
from django.db.models import F
from django.utils import timezone
from django_mongodb_backend.transaction import atomic

from talleres.consultas import buscar_superposicion, cupos_disponibles, consultar_espera
from talleres.models import Bloqueo, Cancelacion, Contador, Inscripcion, Usuario, Taller
from talleres.reglas import (
    LIMITE_CANCELACIONES_CONSECUTIVAS, cancelacion_abierta,
    cuenta_bloqueada_para_inscripciones, inscripcion_abierta, limite_espera,
    limite_inscripcion,
)


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


class SuperposicionHorariaError(InscripcionError):
    """La persona ya tiene una confirmación en un horario incompatible."""


class CuentaBloqueadaError(InscripcionError):
    """La cuenta está bloqueada para nuevas inscripciones."""


class BloqueoParticipanteError(ErrorNegocioTalleres):
    """Error base de las operaciones administrativas de bloqueo."""


class ParticipanteYaBloqueadoError(BloqueoParticipanteError):
    """El participante ya tiene un bloqueo vigente."""


class ParticipanteNoBloqueadoError(BloqueoParticipanteError):
    """El participante no tiene un bloqueo que pueda rehabilitarse."""


class MotivoBloqueoInvalidoError(BloqueoParticipanteError, ValueError):
    """El motivo no corresponde al origen automático o manual del bloqueo."""


class InscripcionNoEncontradaError(InscripcionError, LookupError):
    """No existe una inscripción activa del participante en el taller."""


class PlazoCancelacionVencidoError(InscripcionError):
    """El taller ya comenzó y no admite cancelaciones."""


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


def esta_bloqueado(participante):
    """Estado efectivo compartido por inscripción, espera y API."""
    return cuenta_bloqueada_para_inscripciones(
        getattr(participante, "cancelaciones_consecutivas", 0),
        bloqueado=bool(getattr(participante, "bloqueado", False)),
    )


def _validar_participante_para_bloqueo(participante):
    if getattr(participante, "rol", None) != Usuario.Rol.PARTICIPANTE:
        raise MotivoBloqueoInvalidoError(
            "Solo se puede bloquear o rehabilitar a un participante."
        )


def _bloqueo_abierto(participante):
    return Bloqueo.objects.filter(
        participante_id=participante.pk,
        fecha_desbloqueo__isnull=True,
    ).order_by("fecha_bloqueo", "id").first()


def _marcar_bloqueado(participante):
    Usuario.objects.filter(pk=participante.pk).update(bloqueado=True)
    participante.bloqueado = True


def _abrir_bloqueo(participante, motivo, administrador=None, *, reutilizar=False):
    abierto = _bloqueo_abierto(participante)
    if abierto is not None:
        if reutilizar:
            _marcar_bloqueado(participante)
            return abierto
        raise ParticipanteYaBloqueadoError(
            "El participante ya tiene un bloqueo vigente."
        )
    if getattr(participante, "bloqueado", False) and not reutilizar:
        raise ParticipanteYaBloqueadoError(
            "El participante ya está marcado como bloqueado."
        )
    try:
        bloqueo = Bloqueo.objects.create(
            participante=participante,
            motivo=motivo,
            bloqueado_por=administrador,
        )
    except IntegrityError:
        if reutilizar:
            raise ParticipanteYaBloqueadoError(
                "Otro proceso abrió un bloqueo para el participante."
            ) from None
        raise ParticipanteYaBloqueadoError(
            "El participante ya tiene un bloqueo vigente."
        ) from None
    _marcar_bloqueado(participante)
    return bloqueo


def bloquear_participante(participante, motivo, administrador=None):
    """Abre un episodio manual y actualiza el estado del participante."""
    _validar_participante_para_bloqueo(participante)
    if administrador is None:
        if motivo != Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS:
            raise MotivoBloqueoInvalidoError(
                "Solo el sistema puede registrar un bloqueo automático."
            )
    elif motivo not in dict(Bloqueo.motivos_manuales()):
        raise MotivoBloqueoInvalidoError("Selecciona un motivo de bloqueo válido.")
    if esta_bloqueado(participante):
        raise ParticipanteYaBloqueadoError(
            "El participante ya tiene un bloqueo vigente."
        )
    return _bloquear_transaccion(participante, motivo, administrador)


@transaccion_con_reintentos
def _bloquear_transaccion(participante, motivo, administrador):
    return _abrir_bloqueo(participante, motivo, administrador)


def rehabilitar_participante(participante, administrador):
    """Cierra el episodio abierto y habilita de nuevo al participante."""
    if administrador is None:
        raise MotivoBloqueoInvalidoError(
            "La rehabilitación debe registrar al administrador responsable."
        )
    _validar_participante_para_bloqueo(participante)
    return _rehabilitar_transaccion(participante, administrador)


@transaccion_con_reintentos
def _rehabilitar_transaccion(participante, administrador):
    abierto = _bloqueo_abierto(participante)
    total = getattr(participante, "cancelaciones_consecutivas", 0) or 0
    if (
        abierto is None
        and not getattr(participante, "bloqueado", False)
        and total < LIMITE_CANCELACIONES_CONSECUTIVAS
    ):
        raise ParticipanteNoBloqueadoError(
            "El participante no tiene un bloqueo vigente."
        )

    ahora = timezone.now()
    if abierto is not None:
        abierto.fecha_desbloqueo = ahora
        abierto.desbloqueado_por = administrador
        abierto.save(update_fields=["fecha_desbloqueo", "desbloqueado_por"])

    # El contador mide el ciclo disciplinario vigente. Al rehabilitar un
    # bloqueo por límite se inicia un ciclo nuevo; sin este reinicio el
    # participante quedaría habilitado y bloqueado a la vez por la regla
    # histórica. Los antecedentes siguen en Cancelacion y Bloqueo.
    campos = {"bloqueado": False}
    if total >= LIMITE_CANCELACIONES_CONSECUTIVAS:
        campos["cancelaciones_consecutivas"] = 0
    Usuario.objects.filter(pk=participante.pk).update(**campos)
    participante.bloqueado = False
    if "cancelaciones_consecutivas" in campos:
        participante.cancelaciones_consecutivas = 0
    return abierto


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
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") + 1)
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") - 1)
    if len(consultar_espera(taller)) > limite_espera(taller.cupos):
        raise ValidationError({"cupos": "El nuevo cupo no permite conservar la lista de espera."})
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


class ListaEsperaLlenaError(InscripcionError):
    """La lista alcanzó su capacidad."""


class TallerConCuposError(InscripcionError):
    """Todavía hay plazas para una inscripción confirmada."""


def inscribir_participante(ci, codigo_taller):
    return _registrar_solicitud(ci, codigo_taller, espera=False)


def solicitar_espera(ci, codigo_taller):
    return _registrar_solicitud(ci, codigo_taller, espera=True)


def _validar_plazo(taller, ahora):
    if not inscripcion_abierta(taller.fecha_inicio, ahora):
        limite = timezone.localtime(limite_inscripcion(taller.fecha_inicio))
        raise PlazoInscripcionVencidoError(
            "Fuera de plazo: la inscripción cierra un minuto antes del inicio. "
            f"El límite fue el {limite:%d/%m/%Y a las %H:%M:%S} "
            f"({timezone.get_current_timezone_name()})."
        )


def _validar_superposicion(participante, taller):
    otro = buscar_superposicion(participante, taller)
    if otro is not None:
        inicio = timezone.localtime(otro.fecha_inicio)
        fin = timezone.localtime(otro.fecha_fin)
        raise SuperposicionHorariaError(
            "Superposición de horarios: ya tienes una inscripción confirmada "
            f"en {otro.codigo} — {otro.nombre} "
            f"({inicio:%d/%m/%Y %H:%M} a {fin:%d/%m/%Y %H:%M}, "
            f"{timezone.get_current_timezone_name()})."
        )


def _serializar_inscripciones(participante):
    # Igual que con cupos: dos escrituras reales dentro de la transacción.
    # No cambia el total de cancelaciones. Permite detectar solicitudes
    # simultáneas de la misma persona en talleres distintos y reintentarlas.
    Usuario.objects.filter(pk=participante.pk).update(
        cancelaciones_consecutivas=F("cancelaciones_consecutivas") + 1
    )
    Usuario.objects.filter(pk=participante.pk).update(
        cancelaciones_consecutivas=F("cancelaciones_consecutivas") - 1
    )


@transaccion_con_reintentos
def _registrar_solicitud(ci, codigo_taller, *, espera):
    try:
        participante = Usuario.objects.get(
            ci=ci,
            rol=Usuario.Rol.PARTICIPANTE,
        )
    except Usuario.DoesNotExist:
        raise ParticipanteNoEncontradoError(
            f"No existe un participante con la CI {ci!r}."
        ) from None
    if esta_bloqueado(participante):
        raise CuentaBloqueadaError(
            "La cuenta está bloqueada para nuevas inscripciones y solicitudes "
            "de lista de espera."
        )
    try:
        taller = Taller.objects.get(codigo=codigo_taller)
    except Taller.DoesNotExist:
        raise TallerNoEncontradoError(
            f"No existe un taller con el código {codigo_taller!r}."
        ) from None
    if taller.estado_aprobacion != Taller.Aprobacion.APROBADO:
        raise TallerNoAprobadoError("El taller todavía no está aprobado para inscripciones.")
    _validar_plazo(taller, timezone.now())
    if Inscripcion.objects.filter(participante=participante, taller=taller).exists():
        raise InscripcionDuplicadaError("El participante ya está inscrito en este taller.")
    _validar_superposicion(participante, taller)
    disponibles = cupos_disponibles(taller)
    if espera:
        if disponibles:
            raise TallerConCuposError("Hay plazas disponibles: utiliza Inscribirme.")
        if len(consultar_espera(taller)) >= limite_espera(taller.cupos):
            raise ListaEsperaLlenaError("La lista de espera está llena.")
    elif disponibles == 0:
        raise CupoAgotadoError("El taller no tiene cupos disponibles.")
    _serializar_inscripciones(participante)
    # Escritura real compartida: MongoDB debe detectar conflictos entre
    # solicitudes y ediciones del mismo taller. La transacción revierte ambos pasos.
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") + 1)
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") - 1)
    try:
        datos = {"participante": participante, "taller": taller}
        if espera:
            datos["estado"] = Inscripcion.Estado.EN_ESPERA
        inscripcion = Inscripcion.objects.create(**datos)
        if espera:
            inscripcion.posicion_espera = next(
                posicion for posicion, solicitud in enumerate(consultar_espera(taller), 1)
                if solicitud.pk == inscripcion.pk
            )
        return inscripcion
    except IntegrityError:
        raise InscripcionDuplicadaError(
            "El participante ya está inscrito en este taller."
        ) from None


def _promover_desde_espera(taller):
    if taller.estado_aprobacion != Taller.Aprobacion.APROBADO:
        return None, "El taller no está aprobado para confirmar inscripciones."
    try:
        _validar_plazo(taller, timezone.now())
    except PlazoInscripcionVencidoError as error:
        return None, str(error)
    motivo = None
    for solicitud in consultar_espera(taller):
        participante = solicitud.participante
        if esta_bloqueado(participante):
            motivo = "Las solicitudes en espera no cumplen las reglas de inscripción."
            continue
        try:
            _validar_superposicion(participante, taller)
        except SuperposicionHorariaError:
            motivo = "Las solicitudes en espera tienen horarios incompatibles."
            continue
        _serializar_inscripciones(participante)
        solicitud.estado = Inscripcion.Estado.CONFIRMADA
        solicitud.save(update_fields=["estado"])
        return solicitud, None
    return None, motivo


@transaccion_con_reintentos
def cancelar_inscripcion(ci, codigo_taller):
    """Cancela una inscripción activa y conserva su antecedente.

    La plaza liberada se asigna a la primera persona habilitada en espera. La operación
    devuelve la cancelación registrada y deja en ella si hubo promoción.
    """
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
    if not cancelacion_abierta(taller.fecha_inicio, timezone.now()):
        raise PlazoCancelacionVencidoError(
            "El taller ya comenzó; no se puede cancelar la inscripción."
        )
    inscripcion = Inscripcion.objects.filter(
        participante=participante, taller=taller
    ).first()
    if inscripcion is None:
        raise InscripcionNoEncontradaError(
            "No existe una inscripción activa en este taller."
        )

    estado_anterior = inscripcion.estado
    # Escritura real compartida para que las operaciones sobre el mismo taller
    # detecten conflictos dentro de la transacción MongoDB.
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") + 1)
    Taller.objects.filter(pk=taller.pk).update(cupos=F("cupos") - 1)
    cancelacion = Cancelacion.objects.create(
        participante=participante,
        taller=taller,
        codigo_taller=taller.codigo,
        nombre_taller=taller.nombre,
        estado_anterior=estado_anterior,
    )
    Usuario.objects.filter(pk=participante.pk).update(
        cancelaciones_consecutivas=F("cancelaciones_consecutivas") + 1
    )
    total_cancelaciones = (
        getattr(participante, "cancelaciones_consecutivas", 0) or 0
    ) + 1
    participante.cancelaciones_consecutivas = total_cancelaciones
    if total_cancelaciones >= LIMITE_CANCELACIONES_CONSECUTIVAS:
        _abrir_bloqueo(
            participante,
            Bloqueo.Motivo.CANCELACIONES_CONSECUTIVAS,
            reutilizar=True,
        )
    inscripcion.delete()

    promovido = None
    motivo_sin_promocion = None
    if estado_anterior == Inscripcion.Estado.CONFIRMADA:
        promovido, motivo_sin_promocion = _promover_desde_espera(taller)

    cancelacion.promovido = promovido is not None
    cancelacion.motivo_sin_promocion = motivo_sin_promocion
    cancelacion.cancelaciones_consecutivas = total_cancelaciones
    cancelacion.cuenta_bloqueada = esta_bloqueado(participante)
    return cancelacion
