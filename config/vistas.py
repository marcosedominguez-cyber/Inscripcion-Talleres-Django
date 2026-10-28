"""Vistas de nivel de proyecto que no pertenecen a una app de negocio."""

from django.http import JsonResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def frontend(request):
    try:
        return render(request, "index.html")
    except TemplateDoesNotExist:
        return JsonResponse(
            {
                "mensaje": (
                    "Compila React en frontend con npm install y npm run build, "
                    "o inicia npm run dev."
                )
            },
            status=503,
        )


def csrf_error(request, reason=""):
    return JsonResponse(
        {
            "mensaje": (
                "La sesión del formulario caducó. Recarga la página e intenta "
                "nuevamente."
            )
        },
        status=403,
    )
