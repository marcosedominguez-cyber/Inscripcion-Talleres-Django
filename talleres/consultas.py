"""Consultas de lectura compartidas por las APIs de participantes y gestión."""

from django.utils import timezone

from talleres.models import Inscripcion, Taller
from talleres.reglas import MARGEN_CIERRE_INSCRIPCION


def cupos_disponibles(taller):
    # count() del backend 6.0 usa $unionWith, no admitido en transacciones.
    confirmadas = len(list(Inscripcion.objects.filter(
        taller_id=taller.pk, estado=Inscripcion.Estado.CONFIRMADA
    ).values_list("pk", flat=True)[:taller.cupos]))
    return max(taller.cupos - confirmadas, 0)


def listar_talleres_proximos():
    ahora = timezone.now()
    candidatos = Taller.objects.filter(
        estado_aprobacion=Taller.Aprobacion.APROBADO,
        fecha_inicio__gt=ahora + MARGEN_CIERRE_INSCRIPCION,
    )
    return [taller for taller in candidatos if cupos_disponibles(taller) > 0]


def listar_talleres_instructor(instructor):
    return Taller.objects.filter(instructor=instructor)


def buscar_taller_instructor(instructor, codigo):
    return Taller.objects.filter(instructor=instructor, codigo=codigo).first()


def contar_confirmadas(taller):
    return len(list(Inscripcion.objects.filter(
        taller=taller, estado=Inscripcion.Estado.CONFIRMADA
    ).values_list("pk", flat=True)))
