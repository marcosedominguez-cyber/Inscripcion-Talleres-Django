"""API de solo lectura consumida por el catálogo React."""

from django.core.exceptions import FieldError, ImproperlyConfigured, ObjectDoesNotExist
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_safe
from django.views.decorators.cache import never_cache

from talleres.consultas_participantes import listar_talleres_proximos
from talleres.models import Usuario


@require_safe
@never_cache
def catalogo_talleres_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Se requiere iniciar sesión."}, status=401)

    try:
        try:
            perfil = request.user.perfil
        except ObjectDoesNotExist:
            return JsonResponse({"detail": "Se requiere un perfil de participante."}, status=403)
        if perfil.rol != Usuario.Rol.PARTICIPANTE:
            return JsonResponse({"detail": "Esta sección es exclusiva para participantes."}, status=403)
        talleres = [
            {
                "codigo": taller.codigo,
                "nombre": taller.nombre,
                "descripcion": taller.descripcion,
                "cupos": taller.cupos,
                "fecha_inicio": taller.fecha_inicio,
                "fecha_fin": taller.fecha_fin,
            }
            for taller in listar_talleres_proximos()
        ]
    except (DatabaseError, FieldError, ImproperlyConfigured):
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
