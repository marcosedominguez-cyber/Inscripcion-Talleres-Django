from django.urls import path

from talleres import api_gestion

app_name = "gestion"

urlpatterns = [
    path("talleres/", api_gestion.talleres_instructor, name="talleres"),
    path("talleres/<str:codigo>/", api_gestion.taller_instructor, name="taller"),
]
