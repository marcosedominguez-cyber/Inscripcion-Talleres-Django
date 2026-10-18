"""Consultas de lectura para las pantallas del participante."""

from django.utils import timezone

from talleres.models import Taller
from talleres.services import cupos_disponibles


def listar_talleres_proximos():
    # La política de inscripción vigente cierra al inicio del taller; por eso
    # el catálogo limita la disponibilidad a talleres cuyo inicio no pasó.
    candidatos = Taller.objects.filter(
        estado_aprobacion=Taller.Aprobacion.APROBADO,
        fecha_inicio__gt=timezone.now(),
    )
    return [taller for taller in candidatos if cupos_disponibles(taller) > 0]
