"""Autorización compartida por las APIs de talleres."""

from django.core.exceptions import ObjectDoesNotExist


def perfil_autorizado(request, rol, *, mensaje_sin_perfil, mensaje_rol):
    """Devuelve ``(perfil, None)`` o ``(None, (mensaje, estado))``."""
    if not request.user.is_authenticated:
        return None, ("Se requiere iniciar sesión.", 401)
    if not request.user.is_active:
        return None, ("La cuenta está inactiva.", 403)
    try:
        perfil = request.user.perfil
    except ObjectDoesNotExist:
        return None, (mensaje_sin_perfil, 403)
    if perfil.rol != rol:
        return None, (mensaje_rol, 403)
    return perfil, None
