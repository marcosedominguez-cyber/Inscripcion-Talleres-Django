"""Menú de terminal con persistencia en MongoDB Atlas mediante Django."""
import os
import sys
from datetime import datetime
from pathlib import Path

# Permite tanto python -m proyecto.main como python proyecto/main.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections
from django.utils import timezone
from pymongo.errors import PyMongoError
from proyecto.reglas_inscripciones import InscripcionError
from proyecto.reglas_usuarios import DatosParticipanteInvalidosError
from talleres.models import Usuario, Taller, Inscripcion
from talleres.servicios import ErrorNegocioTalleres
from talleres import servicios


def leer_fecha(etiqueta):
    texto = input(f"{etiqueta} (AAAA-MM-DD HH:MM): ").strip()
    return timezone.make_aware(datetime.strptime(texto, "%Y-%m-%d %H:%M"))


def mostrar_menu():
    print("\n========================================")
    print("   SISTEMA DE GESTIÓN DE TALLERES")
    print("========================================")
    print("1. Registrar participante")
    print("2. Registrar taller")
    print("3. Listar talleres y cupos")
    print("4. Inscribir participante a un taller")
    print("5. Ver inscripciones realizadas")
    print("6. Listar participantes registrados")
    print("7. Salir")
    print("========================================")


def ejecutar():
    print("Datos guardados en MongoDB Atlas. Horarios en America/La_Paz (AAAA-MM-DD HH:MM).")
    try:
        while True:
            mostrar_menu()
            opcion = input("Selecciona una opción (1-7): ").strip()
            try:
                if opcion == "1":
                    ci = input("CI del participante: ").strip()
                    nombre = input("Nombre del participante: ").strip()
                    participante = servicios.registrar_participante(nombre, ci)
                    print(f"Participante registrado con éxito. CI: {participante.ci}")
                elif opcion == "2":
                    nombre = input("Nombre del taller: ").strip()
                    cupos = int(input("Cantidad de cupos: "))
                    inicio = leer_fecha("Inicio")
                    fin = leer_fecha("Fin")
                    descripcion = input("Descripción (opcional): ").strip()
                    taller = servicios.registrar_taller(nombre, cupos, inicio, fin, descripcion)
                    print(f"Taller '{taller.nombre}' registrado con éxito. ID: {taller.codigo}")
                elif opcion == "3":
                    talleres = list(Taller.objects.all())
                    if not talleres:
                        print("No hay talleres registrados.")
                    for taller in talleres:
                        print(f"[{taller.codigo}] {taller.nombre} | Cupos totales: {taller.cupos} | Disponibles: {servicios.cupos_disponibles(taller)}")
                        print(f"  Inicio: {timezone.localtime(taller.fecha_inicio):%Y-%m-%d %H:%M} | Fin: {timezone.localtime(taller.fecha_fin):%Y-%m-%d %H:%M}")
                elif opcion == "4":
                    participante = input("CI del participante: ").strip()
                    taller = input("ID del taller (ej. T-001): ").strip()
                    servicios.inscribir_participante(participante, taller)
                    print(f"¡Inscripción confirmada! Participante {participante} en taller {taller}")
                elif opcion == "5":
                    inscripciones = list(Inscripcion.objects.all())
                    if not inscripciones:
                        print("Aún no hay inscripciones registradas.")
                    participantes = {p.pk: p for p in Usuario.objects.filter(rol=Usuario.Rol.PARTICIPANTE)}
                    talleres = {t.pk: t for t in Taller.objects.all()}
                    for numero, inscripcion in enumerate(inscripciones, start=1):
                        participante = participantes.get(inscripcion.participante_id)
                        taller = talleres.get(inscripcion.taller_id)
                        print(f"{numero}. {participante or inscripcion.participante_id} -> {taller or inscripcion.taller_id} [{inscripcion.estado}]")
                elif opcion == "6":
                    participantes = list(Usuario.objects.filter(rol=Usuario.Rol.PARTICIPANTE))
                    if not participantes:
                        print("No hay participantes registrados.")
                    for participante in participantes:
                        print(f"[{participante.ci}] {participante.nombre}")
                elif opcion == "7":
                    print("¡Hasta luego! Los datos permanecen guardados.")
                    break
                else:
                    print("Opción inválida, intenta de nuevo.")
            except ValidationError as error:
                print("No se pudo realizar la operación: " + "; ".join(error.messages))
            except (InscripcionError, DatosParticipanteInvalidosError, ErrorNegocioTalleres) as error:
                print(f"No se pudo realizar la operación: {error}")
            except ValueError:
                print("Datos inválidos. Usá cupos enteros y fechas con formato AAAA-MM-DD HH:MM.")
            except (DatabaseError, PyMongoError):
                print("No se pudo completar la operación en Atlas. Revisá la conexión, los permisos, la IP autorizada y las migraciones. Consultá los listados antes de repetir una escritura.")
    except (EOFError, KeyboardInterrupt):
        print("\n¡Hasta luego! Los datos permanecen guardados.")
    finally:
        connections.close_all()


if __name__ == "__main__":
    ejecutar()
