"""Transacciones MongoDB para los formularios individuales del Admin."""

from django.db import DEFAULT_DB_ALIAS
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_mongodb_backend.transaction import atomic

_METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class TransaccionMongoChangeFormMixin:
    """Evita el atomic de Django y usa la transacción del backend MongoDB.

    La transacción exterior cubre el guardado del taller, las notificaciones, el
    ``LogEntry`` y el ``ContentType``. Los hooks ``on_commit`` que se añadan en el
    futuro se ejecutan después del commit; un fallo en ellos no revierte los datos
    ya confirmados.
    """

    @method_decorator(csrf_protect)
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method in _METODOS_SEGUROS:
            return super().changeform_view(
                request, object_id, form_url, extra_context,
            )
        with atomic(using=DEFAULT_DB_ALIAS):
            return self._changeform_view(
                request, object_id, form_url, extra_context,
            )
