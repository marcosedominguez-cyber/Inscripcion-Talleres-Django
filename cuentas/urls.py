from django.urls import path
from . import views

urlpatterns = [
    path("sesion/", views.sesion, name="cuentas-sesion"),
    path("registro/", views.registro, name="cuentas-registro"),
    path("login/", views.ingresar, name="cuentas-login"),
    path("logout/", views.salir, name="cuentas-logout"),
]
