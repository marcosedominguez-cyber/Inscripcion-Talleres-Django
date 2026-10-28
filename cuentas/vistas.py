import json
import logging
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError, IntegrityError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from pymongo.errors import PyMongoError

from .forms import LoginForm, RegistroForm
from .servicios import registrar_cuenta

logger = logging.getLogger(__name__)


def errores_formulario(form):
    return {campo: [e["message"] for e in errores]
            for campo, errores in form.errors.get_json_data().items()}


def api(funcion):
    @wraps(funcion)
    def ejecutar(request):
        try:
            return funcion(request)
        except (DatabaseError, PyMongoError):
            logger.warning("No se pudo completar una operación de cuentas en la base de datos.")
            return JsonResponse({"mensaje": "No se pudo conectar con la base de datos. Intenta nuevamente."}, status=503)
    return never_cache(ejecutar)


def datos_json(request):
    if request.content_type != "application/json":
        raise ValueError("Envía los datos como JSON.")
    try:
        datos = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("El formulario no contiene JSON válido.") from None
    if not isinstance(datos, dict) or any(not isinstance(v, str) for v in datos.values()):
        raise ValueError("Los campos deben ser texto.")
    return datos


def perfil_json(cuenta):
    perfil = cuenta.perfil
    return {"id": str(perfil.pk), "nombre_usuario": cuenta.username,
            "ci": perfil.ci, "rol": perfil.rol, "rol_nombre": perfil.get_rol_display()}


@require_GET
@api
def sesion(request):
    token = get_token(request)
    if not request.user.is_authenticated:
        return JsonResponse({"usuario": None, "csrfToken": token})
    if not request.user.is_active:
        return JsonResponse({"mensaje": "La cuenta está inactiva."}, status=403)
    try:
        usuario = perfil_json(request.user)
    except ObjectDoesNotExist:
        return JsonResponse({"mensaje": "Esta cuenta no tiene un perfil web asociado."}, status=403)
    return JsonResponse({"usuario": usuario, "csrfToken": token})


@require_POST
@api
def registro(request):
    if request.user.is_authenticated:
        return JsonResponse({"mensaje": "Cierra sesión antes de registrar otra cuenta."}, status=409)
    try:
        datos = datos_json(request)
    except ValueError as error:
        return JsonResponse({"mensaje": str(error)}, status=400)
    # Nunca aceptar banderas de privilegios ni asociaciones con registros antiguos.
    if set(datos) - set(RegistroForm.base_fields):
        return JsonResponse({"mensaje": "El formulario contiene campos no permitidos."}, status=400)
    form = RegistroForm(datos)
    if not form.is_valid():
        return JsonResponse({"errores": errores_formulario(form)}, status=400)
    datos = form.cleaned_data
    try:
        registrar_cuenta(**{campo: datos[campo] for campo in ("nombre_usuario", "ci", "contrasena", "rol")})
    except IntegrityError:
        return JsonResponse({"mensaje": "El nombre de usuario o la CI ya están registrados."}, status=409)
    except ValidationError as error:
        return JsonResponse({"errores": error.message_dict if hasattr(error, "message_dict") else {"__all__": error.messages}}, status=400)
    return JsonResponse({"mensaje": "Cuenta creada. Inicia sesión con tu CI y contraseña."}, status=201)


@require_POST
@api
def ingresar(request):
    try:
        form = LoginForm(datos_json(request))
    except ValueError as error:
        return JsonResponse({"mensaje": str(error)}, status=400)
    if not form.is_valid():
        return JsonResponse({"errores": errores_formulario(form)}, status=400)
    cuenta = authenticate(request, ci=form.cleaned_data["ci"], password=form.cleaned_data["contrasena"])
    if cuenta is None:
        return JsonResponse({"mensaje": "CI o contraseña incorrectas."}, status=401)
    login(request, cuenta)
    return JsonResponse({"usuario": perfil_json(cuenta), "csrfToken": get_token(request)})


@require_POST
@api
def salir(request):
    logout(request)
    return JsonResponse({"mensaje": "Sesión cerrada.", "csrfToken": get_token(request)})
