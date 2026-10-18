from django.contrib import admin, messages
from django.db.models import Q

from talleres.admin_site import admin_site
from talleres.models import Inscripcion, Taller, Usuario


class AdminSistemaModelAdmin(admin.ModelAdmin):
    """El sitio ya valida staff + rol; cada modelo repite el rol al autorizar."""

    def _autorizado(self, request):
        return admin_site.has_permission(request)

    def has_module_permission(self, request):
        return self._autorizado(request)

    def has_view_permission(self, request, obj=None):
        return self._autorizado(request)

    def has_add_permission(self, request):
        return self._autorizado(request)

    def has_change_permission(self, request, obj=None):
        return self._autorizado(request)

    def has_delete_permission(self, request, obj=None):
        return self._autorizado(request)


@admin.register(Usuario, site=admin_site)
class UsuarioAdmin(AdminSistemaModelAdmin):
    list_display = ("nombre", "ci", "rol", "codigo", "cuenta")
    list_filter = ("rol",)
    search_fields = ("nombre", "ci", "codigo", "cuenta__username")
    list_select_related = ("cuenta",)


class AprobacionFilter(admin.SimpleListFilter):
    title = "estado de aprobación"
    parameter_name = "estado_aprobacion"

    def lookups(self, request, model_admin):
        return Taller.Aprobacion.choices

    def queryset(self, request, queryset):
        if self.value() == Taller.Aprobacion.PENDIENTE:
            return queryset.filter(
                Q(estado_aprobacion=Taller.Aprobacion.PENDIENTE)
                | Q(estado_aprobacion__isnull=True)
            )
        if self.value():
            return queryset.filter(estado_aprobacion=self.value())
        return queryset


@admin.register(Taller, site=admin_site)
class TallerAdmin(AdminSistemaModelAdmin):
    list_display = (
        "codigo", "nombre", "instructor", "estado_aprobacion", "cupos",
        "fecha_inicio", "fecha_fin",
    )
    list_filter = (AprobacionFilter, "instructor")
    search_fields = ("codigo", "nombre", "instructor__nombre")
    list_select_related = ("instructor",)
    actions = ("aprobar_seleccionados", "rechazar_seleccionados")

    @admin.action(description="Aprobar propuestas seleccionadas")
    def aprobar_seleccionados(self, request, queryset):
        actualizados = queryset.filter(
            Q(estado_aprobacion=Taller.Aprobacion.PENDIENTE)
            | Q(estado_aprobacion__isnull=True)
        ).update(estado_aprobacion=Taller.Aprobacion.APROBADO)
        self.message_user(request, f"{actualizados} taller(es) aprobados.", messages.SUCCESS)

    @admin.action(description="Rechazar propuestas seleccionadas")
    def rechazar_seleccionados(self, request, queryset):
        actualizados = queryset.filter(
            Q(estado_aprobacion=Taller.Aprobacion.PENDIENTE)
            | Q(estado_aprobacion__isnull=True)
        ).update(estado_aprobacion=Taller.Aprobacion.RECHAZADO)
        self.message_user(request, f"{actualizados} taller(es) rechazados.", messages.SUCCESS)


@admin.register(Inscripcion, site=admin_site)
class InscripcionAdmin(AdminSistemaModelAdmin):
    list_display = ("participante", "taller", "estado", "fecha_solicitud")
    list_filter = ("estado",)
    search_fields = ("participante__nombre", "participante__ci", "taller__codigo", "taller__nombre")
    list_select_related = ("participante", "taller")
