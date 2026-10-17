"""API de solo lectura consumida por el catálogo React."""

from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_safe

from talleres.consultas_participantes import listar_talleres_proximos


@require_safe
def catalogo_talleres_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Se requiere iniciar sesión."}, status=401)

    try:
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
