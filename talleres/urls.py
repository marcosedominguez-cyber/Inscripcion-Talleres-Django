from django.urls import include, path

from talleres import api_gestion, api_participantes

participantes_urlpatterns = [
    path("talleres/", api_participantes.catalogo_talleres_api, name="catalogo"),
    path("inscripciones/", api_participantes.inscripcion_participante_api, name="inscripcion"),
]

gestion_urlpatterns = [
    path("talleres/", api_gestion.talleres_instructor, name="talleres"),
    path("talleres/<str:codigo>/", api_gestion.taller_instructor, name="taller"),
]

urlpatterns = [
    path("participantes/", include((participantes_urlpatterns, "participantes_api"))),
    path("gestion/", include((gestion_urlpatterns, "gestion"))),
]
