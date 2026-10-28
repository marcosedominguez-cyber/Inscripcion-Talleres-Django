"""API de gestión del instructor; el propietario siempre sale de la sesión."""

import json
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from pymongo.errors import PyMongoError

from talleres.api_comun import perfil_autorizado
from talleres.consultas import (
    buscar_taller_instructor,
    contar_confirmadas,
    cupos_disponibles,
    listar_talleres_instructor,
)
from talleres.formularios_gestion import TallerGestionForm
from talleres.models import Usuario
from talleres.servicios import actualizar_taller, proponer_taller

_CAMPOS = {"nombre", "descripcion", "cupos", "fecha_inicio", "fecha_fin"}


def _manejar_error_db(vista):
    @wraps(vista)
    def ejecutar(request, *args, **kwargs):
        try:
            return vista(request, *args, **kwargs)
        except (DatabaseError, PyMongoError):
            return JsonResponse(
                {"mensaje": "No se pudo completar la operación. Intenta nuevamente."},
                status=503,
            )
    return ejecutar


def _error(mensaje, estado):
    return JsonResponse({"mensaje": mensaje}, status=estado)


def _instructor(request):
    perfil, error = perfil_autorizado(
        request,
        Usuario.Rol.INSTRUCTOR,
        mensaje_sin_perfil="La cuenta no tiene un perfil asociado.",
        mensaje_rol="Esta sección es exclusiva para instructores.",
    )
    if error:
        mensaje, estado = error
        return None, _error(mensaje, estado)
    return perfil, None


def _leer_json(request):
    if request.content_type != "application/json":
        raise ValueError("Envía los datos como JSON.")
    datos = json.loads(request.body)
    if not isinstance(datos, dict) or any(
        not isinstance(valor, (str, int, float)) or isinstance(valor, bool)
        for valor in datos.values()
    ):
        raise ValueError("Los campos deben ser texto o números.")
    if set(datos) - _CAMPOS:
        raise ValueError("El formulario contiene campos no permitidos.")
    return datos


def _formulario(datos):
    form = TallerGestionForm(datos)
    if not form.is_valid():
        return None, JsonResponse(
            {"errores": {campo: [str(error) for error in errores] for campo, errores in form.errors.items()}}, status=400
        )
    return form.cleaned_data, None


def _serializar(taller):
    libres = cupos_disponibles(taller)
    confirmadas = contar_confirmadas(taller)
    return {
        "codigo": taller.codigo,
        "nombre": taller.nombre,
        "descripcion": taller.descripcion,
        "cupos": taller.cupos,
        "fecha_inicio": taller.fecha_inicio,
        "fecha_fin": taller.fecha_fin,
        "estado_aprobacion": taller.estado_aprobacion,
        "confirmadas": confirmadas,
        "plazas_libres": libres,
    }


@never_cache
@_manejar_error_db
@require_http_methods(["GET", "POST"])
def talleres_instructor(request):
    instructor, error = _instructor(request)
    if error:
        return error
    try:
        if request.method == "GET":
            return JsonResponse({
                "talleres": [
                    _serializar(t) for t in listar_talleres_instructor(instructor)
                ]
            })
        datos = _leer_json(request)
        if set(datos) != _CAMPOS:
            return _error("Completa todos los campos del taller.", 400)
        limpios, error = _formulario(datos)
        if error:
            return error
        taller = proponer_taller(instructor=instructor, **limpios)
        return JsonResponse({"taller": _serializar(taller)}, status=201)
    except ValueError as error:
        return _error(str(error), 400)
    except ValidationError as error:
        return JsonResponse({"errores": error.message_dict if hasattr(error, "message_dict") else {"__all__": error.messages}}, status=400)


@never_cache
@_manejar_error_db
@require_http_methods(["GET", "PATCH"])
def taller_instructor(request, codigo):
    instructor, error = _instructor(request)
    if error:
        return error
    taller = buscar_taller_instructor(instructor, codigo)
    if taller is None:
        return _error("Taller no encontrado.", 404)
    if request.method == "GET":
        return JsonResponse({"taller": _serializar(taller)})
    try:
        cambios = _leer_json(request)
    except (ValueError, json.JSONDecodeError) as error:
        return _error(str(error), 400)
    if not cambios:
        return _error("Indica al menos un campo para actualizar.", 400)
    actual = {
        "nombre": taller.nombre,
        "descripcion": taller.descripcion,
        "cupos": taller.cupos,
        "fecha_inicio": timezone.localtime(taller.fecha_inicio).strftime("%Y-%m-%dT%H:%M"),
        "fecha_fin": timezone.localtime(taller.fecha_fin).strftime("%Y-%m-%dT%H:%M"),
    }
    actual.update(cambios)
    limpios, error = _formulario(actual)
    if error:
        return error
    try:
        actualizar_taller(taller, limpios)
    except ValidationError as error:
        return JsonResponse({"errores": error.message_dict if hasattr(error, "message_dict") else {"__all__": error.messages}}, status=400)
    return JsonResponse({"taller": _serializar(taller)})
