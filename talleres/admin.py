from django.contrib import admin
from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "ci", "rol", "codigo", "cuenta")
    list_filter = ("rol",)
    search_fields = ("nombre", "ci", "codigo")
    list_select_related = ("cuenta",)
