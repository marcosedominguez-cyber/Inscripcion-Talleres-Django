from django.urls import path
from . import vistas

urlpatterns = [
    path("sesion/", vistas.sesion, name="cuentas-sesion"),
    path("registro/", vistas.registro, name="cuentas-registro"),
    path("login/", vistas.ingresar, name="cuentas-login"),
    path("logout/", vistas.salir, name="cuentas-logout"),
]
