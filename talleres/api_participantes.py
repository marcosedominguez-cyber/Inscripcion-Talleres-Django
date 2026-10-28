"""API de solo lectura consumida por el catálogo React."""

import json

from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe
from pymongo.errors import PyMongoError

from talleres.api_comun import perfil_autorizado
from talleres.consultas import cupos_disponibles, listar_talleres_proximos
from talleres.models import Usuario
from talleres.servicios import (
    CupoAgotadoError, InscripcionDuplicadaError, ParticipanteNoEncontradoError,
    PlazoInscripcionVencidoError, TallerNoAprobadoError, TallerNoEncontradoError,
    inscribir_participante,
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


@require_safe
@never_cache
def catalogo_talleres_api(request):
    _, error = _participante(
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


@require_POST
@never_cache
def inscripcion_participante_api(request):
    """Inscribe al participante autenticado; la identidad nunca viene del cliente."""
    perfil, error = _participante(
        request, "Esta operación es exclusiva para participantes."
    )
    if error:
        return error
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
        inscripcion = inscribir_participante(perfil.ci, codigo.strip())
    except ParticipanteNoEncontradoError:
        return JsonResponse({"detail": "El perfil no corresponde a un participante válido."}, status=403)
    except TallerNoEncontradoError:
        return JsonResponse({"detail": "No se encontró el taller solicitado."}, status=404)
    except InscripcionDuplicadaError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except CupoAgotadoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except TallerNoAprobadoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except PlazoInscripcionVencidoError as error:
        return JsonResponse({"detail": str(error)}, status=409)
    except (DatabaseError, PyMongoError, FieldError, ImproperlyConfigured):
        return JsonResponse({"detail": "No se pudo completar la inscripción."}, status=503)

    return JsonResponse({
        "mensaje": "Te inscribiste correctamente.",
        "inscripcion": {"id": str(inscripcion.pk), "estado": inscripcion.estado},
    }, status=201)
