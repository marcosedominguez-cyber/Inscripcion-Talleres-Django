from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from talleres.models import Usuario


class CIBackend(ModelBackend):
    def authenticate(self, request, ci=None, password=None, **kwargs):
        if ci is None or password is None:
            return None
        try:
            perfil = Usuario.objects.select_related("cuenta").get(ci=ci)
        except Usuario.DoesNotExist:
            perfil = None
        cuenta = perfil.cuenta if perfil and perfil.cuenta_id else None
        if cuenta is None:
            # Ejecutar el hash también para identificadores inexistentes.
            get_user_model()().set_password(password)
            return None
        if cuenta.check_password(password) and self.user_can_authenticate(cuenta):
            return cuenta
        return None
