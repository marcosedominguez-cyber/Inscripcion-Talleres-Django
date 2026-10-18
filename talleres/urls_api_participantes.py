from django.urls import path

from talleres.api_participantes import catalogo_talleres_api, inscripcion_participante_api

app_name = "participantes_api"

urlpatterns = [
    path("talleres/", catalogo_talleres_api, name="catalogo"),
    path("inscripciones/", inscripcion_participante_api, name="inscripcion"),
]
