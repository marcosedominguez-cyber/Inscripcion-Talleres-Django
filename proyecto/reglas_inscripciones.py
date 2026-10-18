"""Reglas de la primera capacidad de inscripción a talleres."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from proyecto.reglas_usuarios import Participante


class TallerRegistrable(Protocol):
    """Datos mínimos que debe ofrecer el módulo de talleres."""

    id: str
    cupos: int


class EstadoInscripcion(str, Enum):
    CONFIRMADA = "confirmada"


@dataclass(frozen=True)
class Inscripcion:
    participante_id: str
    taller_id: str
    estado: EstadoInscripcion = EstadoInscripcion.CONFIRMADA


class InscripcionError(Exception):
    """Error base de las operaciones de inscripción."""


class ParticipanteNoEncontradoError(InscripcionError, LookupError):
    """No existe el participante solicitado."""


class TallerNoEncontradoError(InscripcionError, LookupError):
    """No existe el taller solicitado."""


class InscripcionDuplicadaError(InscripcionError):
    """El participante ya tiene una inscripción en el taller."""


class CupoAgotadoError(InscripcionError):
    """El taller no puede aceptar otra inscripción confirmada."""


def inscribir_participante(
    participante_id: str,
    taller_id: str,
    participantes: Mapping[str, Participante],
    talleres: Mapping[str, TallerRegistrable],
    inscripciones: list[Inscripcion],
) -> Inscripcion:
    """Crea una inscripción confirmada si se cumplen las reglas acordadas.

    La función modifica ``inscripciones`` solo después de validar toda la
    operación, para que un rechazo no deje cambios parciales.
    """

    if participante_id not in participantes:
        raise ParticipanteNoEncontradoError(
            f"No existe un participante con el ID {participante_id!r}."
        )

    if taller_id not in talleres:
        raise TallerNoEncontradoError(
            f"No existe un taller con el ID {taller_id!r}."
        )

    taller = talleres[taller_id]

    if _ya_esta_inscrito(participante_id, taller_id, inscripciones):
        raise InscripcionDuplicadaError(
            "El participante ya está inscrito en este taller."
        )

    if cupos_disponibles(taller, inscripciones) == 0:
        raise CupoAgotadoError("El taller no tiene cupos disponibles.")

    inscripcion = Inscripcion(
        participante_id=participante_id,
        taller_id=taller_id,
    )
    inscripciones.append(inscripcion)
    return inscripcion


def cupos_disponibles(
    taller: TallerRegistrable, inscripciones: Sequence[Inscripcion]
) -> int:
    """Calcula cupos sin modificar el taller ni las inscripciones."""

    confirmadas = sum(
        inscripcion.taller_id == taller.id
        and inscripcion.estado == EstadoInscripcion.CONFIRMADA
        for inscripcion in inscripciones
    )
    return max(taller.cupos - confirmadas, 0)


def _ya_esta_inscrito(
    participante_id: str,
    taller_id: str,
    inscripciones: Sequence[Inscripcion],
) -> bool:
    return any(
        inscripcion.participante_id == participante_id
        and inscripcion.taller_id == taller_id
        for inscripcion in inscripciones
    )
