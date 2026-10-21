import datetime
from dataclasses import dataclass

import pytest

from proyecto.reglas import (
    CupoAgotadoError,
    DatosParticipanteInvalidosError,
    EstadoInscripcion,
    InscripcionDuplicadaError,
    ParticipanteNoEncontradoError,
    TallerNoEncontradoError,
    cupos_disponibles,
    inscribir_participante,
    registrar_participante,
)
from proyecto.reglas_talleres import GestorTalleres, Talleres


@dataclass(frozen=True)
class TallerParaPruebas:
    """Contrato mínimo que implementará el módulo de talleres para pruebas aisladas."""

    id: str
    cupos: int


# ==============================================================================
# BLOQUE 1: PRUEBAS DE USUARIOS / PARTICIPANTES (Marcos)
# ==============================================================================

def test_registra_participante_con_identificador_automatico():
    participantes = {}

    resultado = registrar_participante(participantes, "Ana Pérez")

    assert resultado.id == "P-001"
    assert resultado.nombre == "Ana Pérez"
    assert participantes == {"P-001": resultado}


def test_genera_identificadores_consecutivos_sin_que_el_usuario_los_elija():
    participantes = {}

    ana = registrar_participante(participantes, "Ana Pérez")
    bruno = registrar_participante(participantes, "Bruno Díaz")

    assert ana.id == "P-001"
    assert bruno.id == "P-002"
    assert len(participantes) == 2


def test_rechaza_nombre_vacio_sin_consumir_un_identificador():
    participantes = {}

    with pytest.raises(DatosParticipanteInvalidosError, match="nombre"):
        registrar_participante(participantes, "   ")

    assert participantes == {}
    assert registrar_participante(participantes, "Ana Pérez").id == "P-001"



# ==============================================================================
# BLOQUE 2: PRUEBAS DE TALLERES (Ismael)
# ==============================================================================

def test_registrar_taller_genera_identificador_automatico():
    gestor = GestorTalleres()

    taller = Talleres(
        nombre="Python básico",
        cupos=20,
        fecha=datetime.date(2026, 10, 15),
    )

    resultado = gestor.registrar_taller(taller)

    assert resultado is taller
    assert taller.id == "T-001"
    assert taller.nombre == "Python básico"
    assert taller.cupos == 20
    assert taller.fecha == datetime.date(2026, 10, 15)


def test_calcular_cupos_disponibles():
    taller = Talleres(
        nombre="Diseño gráfico",
        cupos=5,
        fecha=datetime.date(2026, 11, 10),
    )

    assert taller.calcular_cupos_disponibles(3) == 2


def test_taller_lleno_no_tiene_cupo():
    taller = Talleres(
        nombre="Fotografía",
        cupos=2,
        fecha=datetime.date(2026, 12, 5),
    )

    assert taller.hay_cupo(2) is False


def test_registrar_y_buscar_taller():
    gestor = GestorTalleres()

    taller = Talleres(
        nombre="Marketing digital",
        cupos=10,
        fecha=datetime.date(2026, 11, 20),
    )

    gestor.registrar_taller(taller)

    assert gestor.buscar_taller("T-001") is taller


def test_generar_identificadores_consecutivos():
    gestor = GestorTalleres()

    primer_taller = Talleres(
        nombre="Excel básico",
        cupos=15,
        fecha=datetime.date(2026, 12, 1),
    )

    segundo_taller = Talleres(
        nombre="Excel avanzado",
        cupos=8,
        fecha=datetime.date(2026, 12, 2),
    )

    gestor.registrar_taller(primer_taller)
    gestor.registrar_taller(segundo_taller)

    assert primer_taller.id == "T-001"
    assert segundo_taller.id == "T-002"


def test_buscar_taller_inexistente_devuelve_none():
    gestor = GestorTalleres()

    assert gestor.buscar_taller("T-999") is None


# ==============================================================================
# BLOQUE 3: PRUEBAS DE INSCRIPCIONES E INTEGRACIÓN (Katrina)
# ==============================================================================

def test_inscribe_participante_y_confirma_la_plaza_disponible():
    participantes = {}
    participante = registrar_participante(participantes, "Ana Pérez")
    taller = TallerParaPruebas(id="T-001", cupos=2)
    talleres = {taller.id: taller}
    inscripciones = []

    resultado = inscribir_participante(
        participante.id,
        taller.id,
        participantes,
        talleres,
        inscripciones,
    )

    assert resultado.participante_id == "P-001"
    assert resultado.taller_id == "T-001"
    assert resultado.estado == EstadoInscripcion.CONFIRMADA
    assert inscripciones == [resultado]
    assert cupos_disponibles(taller, inscripciones) == 1


def test_inscripcion_en_el_ultimo_cupo_deja_el_taller_sin_disponibilidad():
    participantes = {}
    participante = registrar_participante(participantes, "Ana Pérez")
    taller = TallerParaPruebas(id="T-001", cupos=1)
    talleres = {taller.id: taller}
    inscripciones = []

    inscribir_participante(
        participante.id,
        taller.id,
        participantes,
        talleres,
        inscripciones,
    )

    assert cupos_disponibles(taller, inscripciones) == 0


def test_rechaza_inscripcion_duplicada_sin_ocupar_otro_cupo():
    participantes = {}
    participante = registrar_participante(participantes, "Ana Pérez")
    taller = TallerParaPruebas(id="T-001", cupos=2)
    talleres = {taller.id: taller}
    inscripciones = []
    inscribir_participante(
        participante.id, taller.id, participantes, talleres, inscripciones
    )

    with pytest.raises(InscripcionDuplicadaError, match="ya está inscrito"):
        inscribir_participante(
            participante.id, taller.id, participantes, talleres, inscripciones
        )

    assert len(inscripciones) == 1
    assert cupos_disponibles(taller, inscripciones) == 1


def test_rechaza_inscripcion_sin_cupo_y_no_modifica_el_estado():
    participantes = {}
    ana = registrar_participante(participantes, "Ana Pérez")
    bruno = registrar_participante(participantes, "Bruno Díaz")
    taller = TallerParaPruebas(id="T-001", cupos=1)
    talleres = {taller.id: taller}
    inscripciones = []
    inscribir_participante(
        ana.id, taller.id, participantes, talleres, inscripciones
    )

    with pytest.raises(CupoAgotadoError, match="no tiene cupos"):
        inscribir_participante(
            bruno.id, taller.id, participantes, talleres, inscripciones
        )

    assert len(inscripciones) == 1
    assert inscripciones[0].participante_id == ana.id


def test_rechaza_inscripcion_de_participante_inexistente_sin_modificar_el_estado():
    taller = TallerParaPruebas(id="T-001", cupos=2)
    inscripciones = []

    with pytest.raises(ParticipanteNoEncontradoError, match="P-999"):
        inscribir_participante(
            "P-999", taller.id, {}, {taller.id: taller}, inscripciones
        )

    assert inscripciones == []


def test_rechaza_inscripcion_en_taller_inexistente_sin_modificar_el_estado():
    participantes = {}
    participante = registrar_participante(participantes, "Ana Pérez")
    inscripciones = []

    with pytest.raises(TallerNoEncontradoError, match="T-999"):
        inscribir_participante(
            participante.id,
            "T-999",
            participantes,
            {},
            inscripciones,
        )

    assert inscripciones == []


def test_integracion_inscripcion_con_objeto_taller_real():
    """Valida la comunicación directa entre talleres e inscripciones."""
    participantes = {}
    participante = registrar_participante(participantes, "Katrina")

    taller = Talleres(
        nombre="Scrum Avanzado",
        cupos=3,
        fecha=datetime.date(2026, 11, 1),
    )

    gestor = GestorTalleres()
    gestor.registrar_taller(taller)

    talleres = {taller.id: taller}
    inscripciones = []

    resultado = inscribir_participante(
        participante.id,
        taller.id,
        participantes,
        talleres,
        inscripciones,
    )

    assert taller.id == "T-001"
    assert resultado.estado == EstadoInscripcion.CONFIRMADA
    assert len(inscripciones) == 1
    assert cupos_disponibles(taller, inscripciones) == 2


def test_integracion_rechaza_inscripcion_duplicada_con_taller_real():
    """Valida los duplicados usando instancias completas del sistema."""
    participantes = {}
    participante = registrar_participante(participantes, "Marcos")

    taller = Talleres(
        nombre="Git & GitHub",
        cupos=5,
        fecha=datetime.date(2026, 11, 5),
    )

    gestor = GestorTalleres()
    gestor.registrar_taller(taller)

    talleres = {taller.id: taller}
    inscripciones = []

    inscribir_participante(
        participante.id,
        taller.id,
        participantes,
        talleres,
        inscripciones,
    )

    with pytest.raises(InscripcionDuplicadaError):
        inscribir_participante(
            participante.id,
            taller.id,
            participantes,
            talleres,
            inscripciones,
        )

    assert len(inscripciones) == 1