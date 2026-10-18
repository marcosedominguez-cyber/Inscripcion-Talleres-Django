from django.contrib.admin import AdminSite
from django.core.exceptions import ObjectDoesNotExist

from talleres.models import Usuario


class AdministracionSistemaSite(AdminSite):
    site_header = "Administración del sistema de talleres"
    site_title = "Administración de talleres"
    index_title = "Gestión global"

    def has_permission(self, request):
        user = request.user
        if not user.is_active or not user.is_staff:
            return False
        try:
            return user.perfil.rol == Usuario.Rol.ADMINISTRADOR
        except ObjectDoesNotExist:
            return False


admin_site = AdministracionSistemaSite(name="admin")
