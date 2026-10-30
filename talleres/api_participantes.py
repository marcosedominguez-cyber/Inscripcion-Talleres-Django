"""API del participante para catálogo, inscripciones, espera y cancelaciones."""

import json

from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe, require_http_methods
from pymongo.errors import PyMongoError

from talleres.api_comun import perfil_autorizado
from talleres.consultas import (
    cupos_disponibles, listar_cancelaciones_participante,
    listar_inscripciones_participante, listar_talleres_proximos, resumen_espera,
)
from talleres.models import Inscripcion, Usuario
from talleres.reglas import LIMITE_CANCELACIONES_CONSECUTIVAS
from talleres.servicios import (
    CuentaBloqueadaError, CupoAgotadoError, InscripcionDuplicadaError,
    InscripcionNoEncontradaError, ParticipanteNoEncontradoError,
    PlazoCancelacionVencidoError, PlazoInscripcionVencidoError,
    TallerNoAprobadoError, TallerNoEncontradoError, cancelar_inscripcion,
    esta_bloqueado, inscribir_participante, solicitar_espera,
    ListaEsperaLlenaError, TallerConCuposError,
)


def _participante(request, mensaje_rol):
    perfil, error = perfil_autorizado(
        request,
        Usuario.Rol.PARTICIPANTE,
        mensaje_sin_perfil="Se requiere un perfil de participante.",
        mensaje_rol=mensaje_rol,
    )
    if error:
        mensaje, estado = error
        return None, JsonResponse({"detail": mensaje}, status=estado)
    return perfil, None


def _serializar_cancelacion(cancelacion):
    return {
        "codigo": cancelacion.codigo_taller,
        "nombre": cancelacion.nombre_taller,
        "estado_anterior": cancelacion.estado_anterior,
        "fecha_cancelacion": cancelacion.fecha_cancelacion,
    }


def _serializar_mis_inscripciones(perfil):
    por_taller = {}
    for inscripcion in listar_inscripciones_participante(perfil):
        anterior = por_taller.get(inscripcion.taller_id)
        if anterior is None or (
            anterior.estado != Inscripcion.Estado.CONFIRMADA
            and inscripcion.estado == Inscripcion.Estado.CONFIRMADA
        ):
            por_taller[inscripcion.taller_id] = inscripcion

    return [
        {
            "codigo": inscripcion.taller.codigo,
            "nombre": inscripcion.taller.nombre,
            "descripcion": inscripcion.taller.descripcion,
            "cupos": inscripcion.taller.cupos,
            "fecha_inicio": inscripcion.taller.fecha_inicio,
            "fecha_fin": inscripcion.taller.fecha_fin,
            "instructor": (
                getattr(inscripcion.taller.instructor, "nombre", None)
                if inscripcion.taller.instructor_id else None
            ),
            "fecha_solicitud": inscripcion.fecha_solicitud,
            "estado": inscripcion.estado,
        }
        for inscripcion in sorted(
            por_taller.values(),
            key=lambda item: (item.taller.fecha_inicio, item.taller.codigo),
        )
    ]


@require_safe
@never_cache
def catalogo_talleres_api(request):
    perfil, error = _participante(
        request, "Esta sección es exclusiva para participantes."
    )
    if error:
        return error

    try:
        talleres = [
            {
                "codigo": taller.codigo,
                "nombre": taller.nombre,
                "descripcion": taller.descripcion,
                "cupos": taller.cupos,
                "cupos_disponibles": cupos_disponibles(taller),
                "fecha_inicio": taller.fecha_inicio,
                "fecha_fin": taller.fecha_fin,
                **resumen_espera(taller, perfil),
            }
            for taller in listar_talleres_proximos()
        ]
    except (DatabaseError, PyMongoError, FieldError, ImproperlyConfigured):
        return JsonResponse(
            {"detail": "No se pudo consultar el catálogo."}, status=503
        )

    return JsonResponse({
        "talleres": talleres,
        "zona_horaria": timezone.get_current_timezone_name(),
        "usuario": {
            "nombre": request.user.get_full_name() or request.user.get_username(),
        },
    })


@require_http_methods(["GET", "POST"])
@never_cache
def inscripcion_participante_api(request, *, espera=False):
    """Lista o registra inscripciones del participante autenticado."""
    perfil, error = _participante(
        request, "Esta operación es exclusiva para participantes."
    )
    if error:
        return error

    if request.method == "GET":
        if espera:
            return JsonResponse({"detail": "Método no permitido."}, status=405)
        try:
            inscripciones = _serializar_mis_inscripciones(perfil)
            cancelaciones = [
                _serializar_cancelacion(cancelacion)
                for cancelacion in listar_cancelaciones_participante(perfil)
            ]
        except (DatabaseError, PyMongoError, FieldError, ImproperlyConfigured):
            return JsonResponse(
                {"detail": "No se pudieron consultar tus inscripciones."}, status=503
            )
        total = getattr(perfil, "cancelaciones_consecutivas", 0) or 0
        return JsonResponse({
            "inscripciones": inscripciones,
            "cancelaciones": cancelaciones,
            "cancelaciones_consecutivas": total,
            "limite_cancelaciones": LIMITE_CANCELACIONES_CONSECUTIVAS,
            "inscripciones_bloqueadas": esta_bloqueado(perfil),
            "zona_horaria": timezone.get_current_timezone_name(),
        })

    if not perfil.ci:
        return JsonResponse({"detail": "El perfil no tiene una identificación válida."}, status=403)
    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "El cuerpo debe ser JSON válido."}, status=400)
    if not isinstance(datos, dict) or set(datos) != {"codigo_taller"}:
        return JsonResponse(
            {"detail": "Envía únicamente el código del taller."}, status=400
        )
    codigo = datos.get("codigo_taller")
    if not isinstance(codigo, str) or not codigo.strip() or len(codigo.strip()) > 32:
        return JsonResponse({"detail": "El código del taller no es válido."}, status=400)
    try:
        inscripcion = (solicitar_espera if espera else inscribir_participante)(perfil.ci, codigo.strip())
    except ParticipanteNoEncontradoError:
        return JsonResponse({"detail": "El perfil no corresponde a un participante válido."}, status=403)
    except TallerNoEncontradoError:
        return JsonResponse({"detail": "No se encontró el taller solicitado."}, status=404)
    except CuentaBloqueadaError as error:
        return JsonResponse({"detail": str(error)}, status=403)
    except InscripcionDuplicadaError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except (CupoAgotadoError, ListaEsperaLlenaError, TallerConCuposError) as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except TallerNoAprobadoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except PlazoInscripcionVencidoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except (DatabaseError, PyMongoError, FieldError, ImproperlyConfigured):
        return JsonResponse({"detail": "No se pudo completar la inscripción."}, status=503)

    return JsonResponse({
        "mensaje": "Solicitud admitida en la lista de espera." if espera else "Te inscribiste correctamente.",
        "inscripcion": {"id": str(inscripcion.pk), "estado": inscripcion.estado,
                        "posicion_espera": getattr(inscripcion, "posicion_espera", None)},
    }, status=201)


@require_POST
@never_cache
def espera_participante_api(request):
    return inscripcion_participante_api(request, espera=True)


@require_POST
@never_cache
def cancelar_inscripcion_api(request):
    """Cancela la inscripción activa del participante autenticado."""
    perfil, error = _participante(
        request, "Esta operación es exclusiva para participantes."
    )
    if error:
        return error
    if not perfil.ci:
        return JsonResponse(
            {"detail": "El perfil no tiene una identificación válida."}, status=403
        )
    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "El cuerpo debe ser JSON válido."}, status=400)
    if not isinstance(datos, dict) or set(datos) != {"codigo_taller"}:
        return JsonResponse(
            {"detail": "Envía únicamente el código del taller."}, status=400
        )
    codigo = datos.get("codigo_taller")
    if not isinstance(codigo, str) or not codigo.strip() or len(codigo.strip()) > 32:
        return JsonResponse({"detail": "El código del taller no es válido."}, status=400)
    try:
        cancelacion = cancelar_inscripcion(perfil.ci, codigo.strip())
    except ParticipanteNoEncontradoError:
        return JsonResponse(
            {"detail": "El perfil no corresponde a un participante válido."}, status=403
        )
    except TallerNoEncontradoError:
        return JsonResponse({"detail": "No se encontró el taller solicitado."}, status=404)
    except InscripcionNoEncontradaError as error:
        return JsonResponse({"detail": str(error)}, status=404)
    except PlazoCancelacionVencidoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except (DatabaseError, PyMongoError, FieldError, ImproperlyConfigured):
        return JsonResponse(
            {"detail": "No se pudo cancelar la inscripción."}, status=503
        )

    mensaje = "Cancelación registrada."
    if cancelacion.promovido:
        mensaje += " Se promovió a la primera persona en lista de espera."
    if cancelacion.cuenta_bloqueada:
        mensaje += (
            " La cuenta quedó bloqueada para nuevas inscripciones por acumular "
            f"{LIMITE_CANCELACIONES_CONSECUTIVAS} cancelaciones consecutivas."
        )
    return JsonResponse({
        "mensaje": mensaje,
        "cancelacion": _serializar_cancelacion(cancelacion),
        "promovido": cancelacion.promovido,
        "cancelaciones_consecutivas": cancelacion.cancelaciones_consecutivas,
        "inscripciones_bloqueadas": cancelacion.cuenta_bloqueada,
    })
