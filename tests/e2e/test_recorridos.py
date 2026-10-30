"""Cuatro recorridos completos sin simular HTTP, servicios ni MongoDB."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from talleres import servicios
from talleres.models import Bloqueo, Cancelacion, Inscripcion, Notificacion, Taller, Usuario

pytestmark = pytest.mark.django_db(transaction=True)


def ingresar(page, ci, clave, rol="participante"):
    page.goto("/")
    page.get_by_role("button", name="Descubrir talleres").click()
    if rol == "instructor":
        page.get_by_role("button", name="Instructor", exact=True).click()
    page.get_by_label("CI", exact=True).fill(ci)
    page.get_by_label("Contraseña", exact=True).fill(clave)
    page.get_by_role("button", name="Ingresar", exact=True).click()


def tarjeta(page, nombre):
    return page.locator("article").filter(has=page.get_by_role("heading", name=nombre, exact=True))


def ingresar_admin(page, cuenta, clave):
    page.goto("/admin/")
    page.get_by_label("Nombre de usuario:", exact=True).fill(cuenta.username)
    page.get_by_label("Contraseña:", exact=True).fill(clave)
    page.get_by_role("button", name="Iniciar sesión").click()
    expect(page.get_by_role("heading", name="Gestión global")).to_be_visible()


def test_registro_sesion_bloqueo_rehabilitacion_y_logout(fabrica, navegador):
    administrador = fabrica.administrador()
    with navegador() as (page, browser, base_url):
        page.goto("/")
        page.get_by_role("button", name="Descubrir talleres").click()
        page.get_by_role("button", name="Crear cuenta de participante").click()
        page.get_by_label("Nombre de usuario").fill("AnaNavegador")
        page.get_by_label("CI", exact=True).fill("70000001")
        page.get_by_label("Contraseña", exact=True).fill(fabrica.clave)
        page.get_by_label("Confirmar contraseña").fill(fabrica.clave)
        page.get_by_role("button", name="Crear cuenta", exact=True).click()
        expect(page.get_by_role("heading", name="Iniciar sesión")).to_be_visible()
        page.get_by_label("CI", exact=True).fill("70000001")
        page.get_by_label("Contraseña", exact=True).fill(fabrica.clave)
        page.get_by_role("button", name="Ingresar", exact=True).click()
        expect(page.get_by_role("heading", name="No hay talleres disponibles")).to_be_visible()
        page.reload()
        expect(page.get_by_role("button", name="Mis inscripciones")).to_be_visible()
        admin_sesion = browser.new_context(base_url=base_url)
        try:
            admin = admin_sesion.new_page()
            ingresar_admin(admin, administrador, fabrica.clave)
            admin.goto("/admin/talleres/usuario/?q=70000001")
            admin.get_by_role("link", name="AnaNavegador", exact=True).click()
            admin.get_by_role("link", name="Bloquear participante", exact=True).click()
            admin.get_by_label("Motivo del bloqueo:").select_option("manual")
            admin.get_by_role("button", name="Confirmar bloqueo", exact=True).click()
            expect(admin.get_by_role("link", name="Rehabilitar participante", exact=True)).to_be_visible()
            page.reload()
            page.get_by_role("button", name="Notificaciones, 1 sin leer").click()
            expect(page.get_by_role("heading", name="Tu cuenta ha sido bloqueada")).to_be_visible()
            expect(page.get_by_text("Motivo: Otro motivo administrativo.", exact=False)).to_be_visible()
            admin.get_by_role("link", name="Rehabilitar participante", exact=True).click()
            admin.get_by_role("button", name="Confirmar rehabilitación", exact=True).click()
            expect(admin.get_by_role("link", name="Bloquear participante", exact=True)).to_be_visible()
        finally:
            admin_sesion.close()
        page.reload()
        page.get_by_role("button", name="Cerrar sesión").click()
        expect(page.get_by_role("button", name="Descubrir talleres")).to_be_visible()
        page.reload()
        expect(page.get_by_role("button", name="Descubrir talleres")).to_be_visible()
    perfil = Usuario.objects.get(ci="70000001")
    assert perfil.rol == "participante" and not perfil.cuenta.is_staff
    assert not perfil.bloqueado
    assert Bloqueo.objects.get(participante=perfil).fecha_desbloqueo is not None


def test_inscripcion_y_rechazo_visible_de_superposicion(fabrica, navegador):
    persona = fabrica.persona(cuenta=True)
    primero = fabrica.taller("Cerámica")
    cruzado = fabrica.taller("Pintura", fecha=fabrica.inicio + timedelta(days=1))
    with navegador() as (page, _, _):
        ingresar(page, persona.ci, fabrica.clave)
        tarjeta(page, primero.nombre).get_by_role("button", name="Inscribirme", exact=True).click()
        expect(tarjeta(page, primero.nombre).get_by_role("button", name="Inscripción confirmada")).to_be_disabled()
        tarjeta(page, cruzado.nombre).get_by_role("button", name="Inscribirme", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Superposición de horarios")
        expect(page.get_by_role("alert")).to_contain_text(primero.codigo)
        page.get_by_role("button", name="Mis inscripciones").click()
        expect(tarjeta(page, primero.nombre)).to_be_visible()
        expect(tarjeta(page, cruzado.nombre)).to_have_count(0)
    assert Inscripcion.objects.filter(participante=persona).count() == 1
    assert servicios.cupos_disponibles(cruzado) == cruzado.cupos


def test_espera_cancelacion_promocion_y_notificacion_leida(fabrica, navegador):
    titular, pendiente = fabrica.persona(cuenta=True), fabrica.persona(cuenta=True)
    taller = fabrica.taller("Fotografía")
    for persona in [titular] + [fabrica.persona() for _ in range(4)]:
        servicios.inscribir_participante(persona.ci, taller.codigo)
    with navegador() as (page, browser, base_url):
        ingresar(page, pendiente.ci, fabrica.clave)
        tarjeta(page, taller.nombre).get_by_role("button", name="Entrar en lista de espera").click()
        expect(tarjeta(page, taller.nombre).get_by_role("button", name="En espera · Posición 1")).to_be_disabled()
        otra_sesion = browser.new_context(base_url=base_url, locale="es-BO")
        try:
            otra = otra_sesion.new_page()
            ingresar(otra, titular.ci, fabrica.clave)
            otra.get_by_role("button", name="Mis inscripciones").click()
            otra.get_by_role("button", name=f"Acciones para {taller.nombre}").click()
            otra.get_by_role("menuitem", name="Cancelar inscripción").click()
            otra.get_by_role("button", name="Sí, cancelar").click()
            expect(otra.get_by_role("dialog")).to_have_count(0)
            expect(otra.get_by_role("status").filter(has_text="Cancelación registrada")).to_be_visible()
        finally:
            otra_sesion.close()
        page.reload()
        page.get_by_role("button", name="Notificaciones, 1 sin leer").click()
        expect(page.get_by_role("heading", name="¡Tu plaza está confirmada!")).to_be_visible()
        page.get_by_role("button", name="Marcar como leída").click()
        expect(page.get_by_role("button", name="Notificaciones, 0 sin leer")).to_be_visible()
        page.reload()
        expect(tarjeta(page, taller.nombre).get_by_role("button", name="Inscripción confirmada")).to_be_disabled()
    assert Inscripcion.objects.get(participante=pendiente, taller=taller).estado == "confirmada"
    assert Cancelacion.objects.filter(participante=titular, taller=taller).count() == 1
    assert Notificacion.objects.get(participante=pendiente, tipo="promocion").leida


def test_propuesta_instructor_aprobacion_admin_y_publicacion(fabrica, navegador):
    instructor = fabrica.persona(cuenta=True, rol=Usuario.Rol.INSTRUCTOR)
    participante = fabrica.persona(cuenta=True)
    administrador = fabrica.administrador()
    fecha = fabrica.inicio.astimezone(ZoneInfo("America/La_Paz"))
    with navegador() as (page, browser, base_url):
        ingresar(page, instructor.ci, fabrica.clave)
        expect(page.get_by_role("alert")).to_contain_text("tipo de acceso seleccionado")
        page.reload()
        expect(page.get_by_role("button", name="Descubrir talleres")).to_be_visible()
        ingresar(page, instructor.ci, fabrica.clave, rol="instructor")
        page.get_by_label("Nombre", exact=True).fill("Taller propuesto")
        page.get_by_label("Descripción", exact=True).fill("Una propuesta del instructor.")
        page.get_by_label("Cupo máximo").fill("10")
        page.get_by_label("Inicio (hora de Bolivia)").fill(fecha.strftime("%Y-%m-%dT%H:%M"))
        page.get_by_label("Fin (hora de Bolivia)").fill((fecha + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"))
        page.get_by_role("button", name="Enviar propuesta").click()
        expect(page.get_by_text("Propuesta enviada para aprobación.")).to_be_visible()
        admin_sesion = browser.new_context(base_url=base_url)
        try:
            admin = admin_sesion.new_page()
            ingresar_admin(admin, administrador, fabrica.clave)
            admin.goto("/admin/talleres/taller/")
            admin.locator("input.action-select").check()
            admin.locator('select[name="action"]').select_option("aprobar_seleccionados")
            admin.locator('button[name="index"]').first.click()
            expect(admin.get_by_text("1 taller(es) aprobados.")).to_be_visible()
        finally:
            admin_sesion.close()
        page.get_by_role("button", name="Cerrar sesión").click()
        expect(page.get_by_role("button", name="Descubrir talleres")).to_be_visible()
        ingresar(page, participante.ci, fabrica.clave, rol="instructor")
        expect(page.get_by_role("alert")).to_contain_text("tipo de acceso seleccionado")
        ingresar(page, participante.ci, fabrica.clave)
        expect(tarjeta(page, "Taller propuesto").get_by_role("button", name="Inscribirme", exact=True)).to_be_enabled()
    taller = Taller.objects.get(nombre="Taller propuesto")
    assert taller.estado_aprobacion == "aprobado" and taller.instructor_id == instructor.pk
