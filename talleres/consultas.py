"""Consultas de lectura compartidas por las APIs de participantes y gestión."""

from django.utils import timezone

from talleres.models import Cancelacion, Inscripcion, Taller
from talleres.reglas import inscripcion_abierta


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
        fecha_inicio__gt=ahora,
    )
    # Catálogo e inscripción usan la misma regla, incluido el instante límite.
    return [taller for taller in candidatos if inscripcion_abierta(taller.fecha_inicio, ahora)]


def listar_inscripciones_participante(participante):
    ahora = timezone.now()
    return [
        inscripcion
        for inscripcion in Inscripcion.objects.filter(
            participante=participante,
            estado__in=(Inscripcion.Estado.CONFIRMADA, Inscripcion.Estado.EN_ESPERA),
        ).select_related("taller", "taller__instructor")
        if inscripcion.taller.fecha_fin > ahora
    ]


def listar_cancelaciones_participante(participante):
    return list(Cancelacion.objects.filter(
        participante=participante,
    ).order_by("-fecha_cancelacion", "-id"))


def listar_talleres_instructor(instructor):
    return Taller.objects.filter(instructor=instructor)


def buscar_taller_instructor(instructor, codigo):
    return Taller.objects.filter(instructor=instructor, codigo=codigo).first()


def contar_confirmadas(taller):
    return len(list(Inscripcion.objects.filter(
        taller=taller, estado=Inscripcion.Estado.CONFIRMADA
    ).values_list("pk", flat=True)))


def consultar_espera(taller):
    return list(Inscripcion.objects.filter(
        taller=taller, estado=Inscripcion.Estado.EN_ESPERA,
    ).order_by("fecha_solicitud", "id"))


def resumen_espera(taller, participante):
    from talleres.reglas import limite_espera
    solicitudes = consultar_espera(taller)
    propia = Inscripcion.objects.filter(taller=taller, participante=participante).first()
    return {
        "limite_espera": limite_espera(taller.cupos),
        "lugares_espera": max(0, limite_espera(taller.cupos) - len(solicitudes)),
        "mi_estado": propia.estado if propia else None,
        "posicion_espera": next((i for i, s in enumerate(solicitudes, 1)
                                 if s.participante_id == participante.pk), None),
    }
