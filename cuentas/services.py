from django.contrib.auth import get_user_model
from talleres.models import Usuario
from talleres.services import _transaccion


@_transaccion
def registrar_cuenta(*, nombre_usuario, ci, contrasena, rol):
    if rol not in (Usuario.Rol.PARTICIPANTE, Usuario.Rol.INSTRUCTOR):
        raise ValueError("El registro público no permite ese rol.")
    cuenta = get_user_model().objects.create_user(
        username=nombre_usuario, password=contrasena, is_staff=False, is_superuser=False,
    )
    perfil = Usuario(cuenta=cuenta, ci=ci, nombre=nombre_usuario, rol=rol)
    # Índices únicos resuelven también registros simultáneos.
    perfil.full_clean()
    perfil.save()
    return perfil
