"""Transacciones reales de los formularios individuales de talleres en Admin."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.db import transaction as transaccion_django
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_mongodb_backend.transaction import atomic as transaccion_mongo

from talleres import servicios
from talleres.admin import TallerAdmin
from talleres.models import Notificacion, Taller

pytestmark = pytest.mark.django_db(transaction=True)


def datos_taller(taller, **cambios):
    inicio = timezone.localtime(taller.fecha_inicio)
    fin = timezone.localtime(taller.fecha_fin)
    datos = {
        "codigo": taller.codigo,
        "nombre": taller.nombre,
        "descripcion": taller.descripcion,
        "cupos": taller.cupos,
        "fecha_inicio_0": inicio.strftime("%Y-%m-%d"),
        "fecha_inicio_1": inicio.strftime("%H:%M:%S"),
        "fecha_fin_0": fin.strftime("%Y-%m-%d"),
        "fecha_fin_1": fin.strftime("%H:%M:%S"),
        "instructor": str(taller.instructor_id) if taller.instructor_id else "",
        "estado_aprobacion": taller.estado_aprobacion,
    }
    datos.update(cambios)
    return datos


def cliente_admin(administrador):
    cliente = Client(enforce_csrf_checks=True)
    cliente.force_login(administrador)
    return cliente


def abrir_formulario(cliente, url):
    respuesta = cliente.get(url)
    assert respuesta.status_code == 200
    return cliente.cookies["csrftoken"].value


def test_edicion_admin_confirma_taller_notificacion_y_auditoria(fabrica):
    administrador = fabrica.administrador()
    persona = fabrica.persona()
    taller = fabrica.taller("Nombre original")
    servicios.inscribir_participante(persona.ci, taller.codigo)
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])
    token = abrir_formulario(cliente, url)

    respuesta = cliente.post(
        url,
        datos_taller(taller, nombre="Nombre actualizado"),
        HTTP_X_CSRFTOKEN=token,
    )

    assert respuesta.status_code == 302
    taller.refresh_from_db()
    assert taller.nombre == "Nombre actualizado"
    assert Notificacion.objects.filter(
        taller=taller, participante=persona, tipo="edicion_taller",
    ).count() == 1
    auditoria = LogEntry.objects.get(
        object_id=str(taller.pk), action_flag=CHANGE,
    )
    assert "Nombre" in auditoria.change_message


def test_creacion_admin_confirma_taller_y_auditoria(fabrica):
    administrador = fabrica.administrador()
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_add")
    token = abrir_formulario(cliente, url)
    inicio = timezone.localtime(fabrica.inicio)
    fin = timezone.localtime(fabrica.inicio + timedelta(days=2))

    respuesta = cliente.post(
        url,
        {
            "codigo": "T-ADMIN",
            "nombre": "Taller creado desde Admin",
            "descripcion": "Creado en la prueba de integración.",
            "cupos": 8,
            "fecha_inicio_0": inicio.strftime("%Y-%m-%d"),
            "fecha_inicio_1": inicio.strftime("%H:%M:%S"),
            "fecha_fin_0": fin.strftime("%Y-%m-%d"),
            "fecha_fin_1": fin.strftime("%H:%M:%S"),
            "instructor": "",
            "estado_aprobacion": Taller.Aprobacion.PENDIENTE,
        },
        HTTP_X_CSRFTOKEN=token,
    )

    assert respuesta.status_code == 302
    taller = Taller.objects.get(codigo="T-ADMIN")
    auditoria = LogEntry.objects.get(
        object_id=str(taller.pk), action_flag=ADDITION,
    )
    assert "Taller creado desde Admin" in auditoria.object_repr


def test_error_al_auditar_revierte_taller_y_notificaciones(fabrica):
    administrador = fabrica.administrador()
    persona = fabrica.persona()
    taller = fabrica.taller("Nombre original")
    servicios.inscribir_participante(persona.ci, taller.codigo)
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])
    token = abrir_formulario(cliente, url)

    with patch.object(
        TallerAdmin, "log_change",
        side_effect=RuntimeError("fallo al registrar la auditoría"),
    ):
        with pytest.raises(RuntimeError, match="fallo al registrar la auditoría"):
            cliente.post(
                url,
                datos_taller(taller, nombre="No debe persistir"),
                HTTP_X_CSRFTOKEN=token,
            )

    taller.refresh_from_db()
    assert taller.nombre == "Nombre original"
    assert not Notificacion.objects.filter(taller=taller).exists()
    assert not LogEntry.objects.filter(object_id=str(taller.pk)).exists()


def test_edicion_sin_cambios_no_invoca_el_servicio_ni_notifica(fabrica):
    administrador = fabrica.administrador()
    persona = fabrica.persona()
    taller = fabrica.taller("Sin cambios")
    servicios.inscribir_participante(persona.ci, taller.codigo)
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])
    token = abrir_formulario(cliente, url)

    with patch("talleres.admin.actualizar_taller") as actualizar:
        respuesta = cliente.post(
            url, datos_taller(taller), HTTP_X_CSRFTOKEN=token,
        )

    assert respuesta.status_code == 302
    actualizar.assert_not_called()
    assert not Notificacion.objects.filter(taller=taller).exists()


def test_formulario_invalido_no_escribe_ni_notifica(fabrica):
    administrador = fabrica.administrador()
    taller = fabrica.taller("Cupo válido", cupos=5)
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])
    token = abrir_formulario(cliente, url)

    respuesta = cliente.post(
        url,
        datos_taller(taller, cupos=0),
        HTTP_X_CSRFTOKEN=token,
    )

    assert respuesta.status_code == 200
    taller.refresh_from_db()
    assert taller.cupos == 5
    assert not Notificacion.objects.filter(taller=taller).exists()


def test_post_sin_csrf_se_rechaza_antes_de_escribir(fabrica):
    administrador = fabrica.administrador()
    taller = fabrica.taller("Protegido")
    cliente = cliente_admin(administrador)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])
    abrir_formulario(cliente, url)

    respuesta = cliente.post(
        url, datos_taller(taller, nombre="No debe persistir"),
    )

    assert respuesta.status_code == 403
    taller.refresh_from_db()
    assert taller.nombre == "Protegido"


def test_participante_no_puede_entrar_al_admin(fabrica):
    persona = fabrica.persona(cuenta=True)
    taller = fabrica.taller("Privado")
    cliente = Client()
    cliente.force_login(persona.cuenta)
    url = reverse("admin:talleres_taller_change", args=[taller.pk])

    respuesta = cliente.get(url)

    assert respuesta.status_code in (302, 403)


def test_servicio_rechaza_atomic_django_sin_transaccion_mongo(fabrica):
    taller = fabrica.taller("Sin cambios")

    with pytest.raises(servicios.TransaccionMongoRequeridaError):
        with transaccion_django.atomic():
            servicios.actualizar_taller(taller, {"nombre": "No debe persistir"})

    taller.refresh_from_db()
    assert taller.nombre == "Sin cambios"


def test_error_anidado_revierte_la_transaccion_mongo_exterior(fabrica):
    taller = fabrica.taller("Nombre original")

    with patch(
        "talleres.servicios._notificar_edicion_taller",
        side_effect=RuntimeError("fallo después de guardar"),
    ):
        with pytest.raises(RuntimeError, match="fallo después de guardar"):
            with transaccion_mongo():
                servicios.actualizar_taller(taller, {"nombre": "No debe persistir"})

    taller.refresh_from_db()
    assert taller.nombre == "Nombre original"
