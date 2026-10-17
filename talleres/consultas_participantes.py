"""Consultas de lectura para las pantallas del participante."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from talleres.models import Taller


def listar_talleres_proximos():
    """Consulta talleres futuros cuya publicación fue autorizada por gestión.

    El equipo debe indicar el campo y valor reales de aprobación. No se
    publica un catálogo sin filtro mientras ese contrato no esté definido.
    """
    publicacion = getattr(settings, "PARTICIPANTES_FILTRO_PUBLICACION", None)
    if not isinstance(publicacion, dict) or not publicacion:
        raise ImproperlyConfigured("Falta acordar el filtro de publicación con gestión.")
    if "fecha_inicio__gt" in publicacion:
        raise ImproperlyConfigured("El filtro de publicación no debe reemplazar el plazo.")
    return Taller.objects.filter(fecha_inicio__gt=timezone.now(), **publicacion).order_by(
        "fecha_inicio", "codigo"
    )
