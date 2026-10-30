import json
from datetime import date, datetime

from django.contrib import admin, messages
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import models
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.text import capfirst

from talleres.admin_site import admin_site
from talleres.admin_transacciones import TransaccionMongoChangeFormMixin
from talleres.models import Bloqueo, Cancelacion, Inscripcion, Taller, Usuario
from talleres.servicios import (
    BloqueoParticipanteError, actualizar_taller, bloquear_participante, rehabilitar_participante,
    _notificar_edicion_taller, transaccion_con_reintentos,
)

_VALOR_AUSENTE = object()
_LONGITUD_MAXIMA_AUDITORIA = 80
_CAMPOS_SENSIBLES_AUDITORIA = frozenset({
    "password", "contrasena", "contraseña", "token", "secret", "api_key",
    "ci", "cuenta",
})


class AdminSistemaModelAdmin(admin.ModelAdmin):
    """El sitio ya valida staff + rol; cada modelo repite el rol al autorizar."""

    etiquetas_auditoria = {}
    campos_sensibles_auditoria = _CAMPOS_SENSIBLES_AUDITORIA
    longitud_maxima_auditoria = _LONGITUD_MAXIMA_AUDITORIA

    def _autorizado(self, request):
        return admin_site.has_permission(request)

    def construct_change_message(self, request, form, formsets, add=False):
        mensaje = super().construct_change_message(request, form, formsets, add)
        if add or not form.changed_data:
            return mensaje

        resumenes = [
            self._resumen_campo_formulario(form, nombre)
            for nombre in form.changed_data
        ]
        for entrada in mensaje:
            if "changed" in entrada and "name" not in entrada["changed"]:
                entrada["changed"]["fields"] = resumenes
                break
        else:
            mensaje.append({"changed": {"fields": resumenes}})
        return mensaje

    def log_change(self, request, obj, message):
        if isinstance(message, list):
            message = json.dumps(message, ensure_ascii=False)
        return super().log_change(request, obj, message)

    def _resumen_campo_formulario(self, form, nombre):
        etiqueta = self._etiqueta_campo(nombre, form=form)
        if nombre in self.campos_sensibles_auditoria:
            return f"{etiqueta}: valor sensible modificado"
        return self._resumen_cambio(
            etiqueta,
            form.initial.get(nombre, _VALOR_AUSENTE),
            form.cleaned_data.get(nombre, _VALOR_AUSENTE),
            self._campo_modelo(form, nombre),
        )

    def _campo_modelo(self, form, nombre):
        try:
            return form._meta.model._meta.get_field(nombre)
        except (AttributeError, FieldDoesNotExist):
            return None

    def _etiqueta_campo(self, nombre, *, form=None, modelo=None):
        if nombre in self.etiquetas_auditoria:
            return self.etiquetas_auditoria[nombre]
        if form is not None:
            try:
                etiqueta = form.fields[nombre].label
            except (AttributeError, KeyError):
                etiqueta = None
            if etiqueta:
                return capfirst(str(etiqueta))
        try:
            modelo = modelo or self.model
            return capfirst(str(modelo._meta.get_field(nombre).verbose_name))
        except (AttributeError, FieldDoesNotExist):
            return capfirst(nombre)

    def _resumen_cambio(self, etiqueta, anterior, nuevo, campo=None):
        return (
            f"{etiqueta}: {self._valor_legible(anterior, campo)}"
            f" → {self._valor_legible(nuevo, campo)}"
        )

    def _valor_legible(self, valor, campo=None):
        if valor is _VALOR_AUSENTE:
            return "desconocido"
        if valor is None:
            return "vacío"
        if isinstance(valor, bool):
            return "sí" if valor else "no"
        if isinstance(valor, datetime):
            if timezone.is_aware(valor):
                valor = timezone.localtime(valor)
            return self._truncar(valor.strftime("%d/%m/%Y %H:%M"))
        if isinstance(valor, date):
            return self._truncar(valor.strftime("%d/%m/%Y"))
        if campo is not None and isinstance(campo, models.ForeignKey):
            if isinstance(valor, models.Model):
                valor = valor.pk
            return self._truncar(str(valor))
        if isinstance(valor, models.QuerySet):
            valor = list(valor)
        if isinstance(valor, (list, tuple, set)):
            return self._truncar(", ".join(
                str(elemento.pk if isinstance(elemento, models.Model) else elemento)
                for elemento in valor
            ))
        if campo is not None:
            opciones = getattr(campo, "flatchoices", None)
            if opciones and not isinstance(valor, str):
                etiqueta = dict(opciones).get(valor)
                if etiqueta is not None:
                    return self._truncar(str(etiqueta))
        if isinstance(valor, models.Model):
            return self._truncar(str(valor))
        return self._truncar(str(valor))

    def _truncar(self, texto):
        limite = self.longitud_maxima_auditoria
        if limite and len(texto) > limite:
            return f"{texto[:limite - 1]}…"
        return texto

    def has_module_permission(self, request):
        return self._autorizado(request)

    def has_view_permission(self, request, obj=None):
        return self._autorizado(request)

    def has_add_permission(self, request):
        return self._autorizado(request)

    def has_change_permission(self, request, obj=None):
        return self._autorizado(request)

    def has_delete_permission(self, request, obj=None):
        # Conservar usuarios, talleres e inscripciones: el retiro se registra
        # mediante el servicio de cancelación, no mediante borrados del admin.
        return False


@admin.register(Usuario, site=admin_site)
class UsuarioAdmin(AdminSistemaModelAdmin):
    list_display = (
        "nombre", "ci", "rol", "bloqueado", "cuenta",
        "cancelaciones_consecutivas",
    )
    list_filter = ("rol", "bloqueado")
    search_fields = ("nombre", "ci", "cuenta__username")
    list_select_related = ("cuenta",)
    readonly_fields = ("bloqueado",)
    actions = ("bloquear_participantes", "rehabilitar_participantes")
    change_form_template = "admin/talleres/usuario/change_form.html"
    bloquear_participantes_template = (
        "admin/talleres/usuario/bloquear_participantes.html"
    )
    rehabilitar_participante_template = (
        "admin/talleres/usuario/rehabilitar_participante.html"
    )

    def get_urls(self):
        return [
            path(
                "<path:object_id>/bloquear/",
                self.admin_site.admin_view(self._vista_bloquear),
                name="talleres_usuario_bloquear",
            ),
            path(
                "<path:object_id>/rehabilitar/",
                self.admin_site.admin_view(self._vista_rehabilitar),
                name="talleres_usuario_rehabilitar",
            ),
        ] + super().get_urls()

    def _url_cambio(self, participante):
        return reverse(
            f"{self.admin_site.name}:talleres_usuario_change",
            args=[str(participante.pk)],
        )

    def _url_listado(self):
        return reverse(f"{self.admin_site.name}:talleres_usuario_changelist")

    def _participante_accion(self, request, object_id):
        if not self._autorizado(request):
            raise PermissionDenied
        participante = self.get_object(request, object_id)
        if participante is None:
            raise Http404("El participante no existe.")
        if not self.has_change_permission(request, participante):
            raise PermissionDenied
        if participante.rol != Usuario.Rol.PARTICIPANTE:
            raise Http404("El usuario indicado no es un participante.")
        return participante

    def _contexto_bloqueo(
        self, request, participantes, *, individual, motivo=None,
    ):
        if individual:
            participante = participantes[0]
            title = "Bloquear participante"
            explicacion = (
                "Se abrirá un episodio de bloqueo para el participante "
                "seleccionado. Se cancelarán sus inscripciones confirmadas y "
                "solicitudes en espera, conservando los antecedentes. Las plazas "
                "liberadas se asignarán según las reglas de promoción."
            )
            form_action = reverse(
                f"{self.admin_site.name}:talleres_usuario_bloquear",
                args=[str(participante.pk)],
            )
            cancel_url = self._url_cambio(participante)
        else:
            title = "Bloquear participantes"
            explicacion = (
                "Se abrirá un episodio de bloqueo para cada participante "
                "seleccionado. Se cancelarán sus inscripciones confirmadas y "
                "solicitudes en espera, conservando los antecedentes. Las plazas "
                "liberadas se asignarán según las reglas de promoción."
            )
            form_action = ""
            cancel_url = self._url_listado()
        return {
            **self.admin_site.each_context(request),
            "title": title,
            "opts": self.model._meta,
            "participantes": participantes,
            "motivos": Bloqueo.motivos_manuales(),
            "motivo_seleccionado": motivo,
            "accion_masiva": not individual,
            "form_action": form_action,
            "cancel_url": cancel_url,
            "explicacion": explicacion,
        }

    def _formulario_bloqueo(self, request, queryset):
        return render(
            request,
            self.bloquear_participantes_template,
            self._contexto_bloqueo(
                request, list(queryset), individual=False,
            ),
        )

    def _contexto_rehabilitacion(self, request, participante):
        return {
            **self.admin_site.each_context(request),
            "title": "Rehabilitar participante",
            "opts": self.model._meta,
            "participante": participante,
            "form_action": reverse(
                f"{self.admin_site.name}:talleres_usuario_rehabilitar",
                args=[str(participante.pk)],
            ),
            "cancel_url": self._url_cambio(participante),
        }

    def _vista_bloquear(self, request, object_id):
        participante = self._participante_accion(request, object_id)
        if request.method == "POST":
            motivo = request.POST.get("motivo")
            if motivo not in dict(Bloqueo.motivos_manuales()):
                self.message_user(
                    request, "Selecciona un motivo de bloqueo válido.",
                    messages.ERROR,
                )
                return render(
                    request,
                    self.bloquear_participantes_template,
                    self._contexto_bloqueo(
                        request, [participante], individual=True, motivo=motivo,
                    ),
                )
            try:
                bloquear_participante(
                    participante, motivo, administrador=request.user,
                )
            except BloqueoParticipanteError as error:
                self.message_user(request, str(error), messages.ERROR)
            else:
                self.message_user(
                    request,
                    f"{participante} fue bloqueado.",
                    messages.SUCCESS,
                )
            return HttpResponseRedirect(self._url_cambio(participante))
        return render(
            request,
            self.bloquear_participantes_template,
            self._contexto_bloqueo(
                request, [participante], individual=True,
            ),
        )

    def _vista_rehabilitar(self, request, object_id):
        participante = self._participante_accion(request, object_id)
        if request.method == "POST":
            try:
                rehabilitar_participante(participante, request.user)
            except BloqueoParticipanteError as error:
                self.message_user(request, str(error), messages.ERROR)
            else:
                self.message_user(
                    request,
                    f"{participante} fue rehabilitado.",
                    messages.SUCCESS,
                )
            return HttpResponseRedirect(self._url_cambio(participante))
        return render(
            request,
            self.rehabilitar_participante_template,
            self._contexto_rehabilitacion(request, participante),
        )

    def _resultado_accion(self, request, accion, exitosos, errores):
        if exitosos:
            self.message_user(
                request,
                f"{exitosos} participante(s) {accion}.",
                messages.SUCCESS,
            )
        if errores:
            self.message_user(
                request,
                "No se pudieron procesar: " + "; ".join(errores),
                messages.WARNING,
            )

    @admin.action(
        description="Bloquear participantes seleccionados",
        permissions=["change"],
    )
    def bloquear_participantes(self, request, queryset):
        if not self._autorizado(request):
            self.message_user(
                request, "No tienes permiso para bloquear participantes.",
                messages.ERROR,
            )
            return None
        if request.POST.get("confirmar_bloqueo") != "1":
            return self._formulario_bloqueo(request, queryset)

        motivo = request.POST.get("motivo")
        if motivo not in dict(Bloqueo.motivos_manuales()):
            self.message_user(
                request, "Selecciona un motivo de bloqueo válido.",
                messages.ERROR,
            )
            return None

        bloqueados = 0
        errores = []
        for participante in queryset:
            try:
                bloquear_participante(
                    participante, motivo, administrador=request.user,
                )
                bloqueados += 1
            except BloqueoParticipanteError as error:
                errores.append(f"{participante}: {error}")
        self._resultado_accion(request, "bloqueados", bloqueados, errores)
        return None

    @admin.action(
        description="Rehabilitar participantes seleccionados",
        permissions=["change"],
    )
    def rehabilitar_participantes(self, request, queryset):
        if not self._autorizado(request):
            self.message_user(
                request, "No tienes permiso para rehabilitar participantes.",
                messages.ERROR,
            )
            return None

        rehabilitados = 0
        errores = []
        for participante in queryset:
            try:
                rehabilitar_participante(participante, request.user)
                rehabilitados += 1
            except BloqueoParticipanteError as error:
                errores.append(f"{participante}: {error}")
        self._resultado_accion(request, "rehabilitados", rehabilitados, errores)
        return None


@admin.register(Bloqueo, site=admin_site)
class BloqueoAdmin(AdminSistemaModelAdmin):
    list_display = (
        "participante", "motivo", "fecha_bloqueo", "bloqueado_por",
        "fecha_desbloqueo", "desbloqueado_por",
    )
    list_filter = ("motivo",)
    search_fields = (
        "participante__nombre", "participante__ci", "bloqueado_por__username",
        "desbloqueado_por__username",
    )
    list_select_related = ("participante", "bloqueado_por", "desbloqueado_por")
    readonly_fields = (
        "participante", "motivo", "fecha_bloqueo", "bloqueado_por",
        "fecha_desbloqueo", "desbloqueado_por",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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
class TallerAdmin(TransaccionMongoChangeFormMixin, AdminSistemaModelAdmin):
    list_display = (
        "codigo", "nombre", "instructor", "estado_aprobacion", "cupos",
        "fecha_inicio", "fecha_fin",
    )
    list_filter = (AprobacionFilter, "instructor")
    search_fields = ("codigo", "nombre", "instructor__nombre")
    list_select_related = ("instructor",)
    actions = ("aprobar_seleccionados", "rechazar_seleccionados")
    etiquetas_auditoria = {"estado_aprobacion": "Estado de aprobación"}

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        if not form.changed_data:
            return
        anterior = Taller.objects.get(pk=obj.pk)
        actualizar_taller(anterior, {campo: getattr(obj, campo) for campo in form.changed_data},
                          reenviar_revision=False)

    @admin.action(description="Aprobar propuestas seleccionadas")
    def aprobar_seleccionados(self, request, queryset):
        self._cambiar_estado_talleres(
            request, queryset, Taller.Aprobacion.APROBADO, "aprobados",
        )

    @admin.action(description="Rechazar propuestas seleccionadas")
    def rechazar_seleccionados(self, request, queryset):
        self._cambiar_estado_talleres(
            request, queryset, Taller.Aprobacion.RECHAZADO, "rechazados",
        )

    @transaccion_con_reintentos
    def _cambiar_estado_talleres(self, request, queryset, nuevo_estado, resultado):
        etiqueta = self._etiqueta_campo("estado_aprobacion")
        campo = self.model._meta.get_field("estado_aprobacion")
        actualizados = 0
        for taller in queryset:
            anterior = (
                getattr(taller, "estado_aprobacion", None)
                or Taller.Aprobacion.PENDIENTE
            )
            if anterior != Taller.Aprobacion.PENDIENTE:
                continue
            # El listado del admin carga relaciones; MongoDB solo admite
            # update sobre una colección. Los seleccionados ya se iteran arriba.
            afectados = Taller.objects.filter(
                Q(pk=taller.pk)
                & (
                    Q(estado_aprobacion=Taller.Aprobacion.PENDIENTE)
                    | Q(estado_aprobacion__isnull=True)
                )
            ).update(estado_aprobacion=nuevo_estado)
            if not afectados:
                continue
            taller.estado_aprobacion = nuevo_estado
            _notificar_edicion_taller(taller, {"estado_aprobacion": (anterior, nuevo_estado)})
            self.log_change(
                request,
                taller,
                [{
                    "changed": {
                        "fields": [
                            self._resumen_cambio(
                                etiqueta, anterior, nuevo_estado, campo,
                            )
                        ]
                    }
                }],
            )
            actualizados += 1
        self.message_user(
            request, f"{actualizados} taller(es) {resultado}.", messages.SUCCESS,
        )


@admin.register(Inscripcion, site=admin_site)
class InscripcionAdmin(AdminSistemaModelAdmin):
    list_display = ("participante", "taller", "estado", "fecha_solicitud")
    list_filter = ("estado",)
    search_fields = ("participante__nombre", "participante__ci", "taller__codigo", "taller__nombre")
    list_select_related = ("participante", "taller")

    # Las altas, promociones y cancelaciones pasan por los servicios para
    # respetar las reglas y conservar el historial, también para administradores.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Cancelacion, site=admin_site)
class CancelacionAdmin(AdminSistemaModelAdmin):
    list_display = (
        "participante", "codigo_taller", "nombre_taller", "estado_anterior",
        "fecha_cancelacion",
    )
    list_filter = ("estado_anterior",)
    search_fields = (
        "participante__nombre", "participante__ci", "codigo_taller", "nombre_taller",
    )
    list_select_related = ("participante",)
    readonly_fields = (
        "participante", "taller", "codigo_taller", "nombre_taller",
        "estado_anterior", "fecha_cancelacion",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
