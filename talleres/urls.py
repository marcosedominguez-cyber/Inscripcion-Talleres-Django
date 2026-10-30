from django.urls import include, path

from talleres import api_gestion, api_participantes

participantes_urlpatterns = [
    path("notificaciones/", api_participantes.notificaciones_api, name="notificaciones"),
    path("notificaciones/<str:identificador>/leer/", api_participantes.leer_notificacion_api, name="leer_notificacion"),
    path("espera/", api_participantes.espera_participante_api, name="espera"),
    path("talleres/", api_participantes.catalogo_talleres_api, name="catalogo"),
    path("inscripciones/cancelar/", api_participantes.cancelar_inscripcion_api, name="cancelar"),
    path("inscripciones/", api_participantes.inscripcion_participante_api, name="inscripcion"),
]

gestion_urlpatterns = [
    path("talleres/<str:codigo>/espera/", api_gestion.espera_instructor, name="espera"),
    path("talleres/", api_gestion.talleres_instructor, name="talleres"),
    path("talleres/<str:codigo>/", api_gestion.taller_instructor, name="taller"),
]

urlpatterns = [
    path("participantes/", include((participantes_urlpatterns, "participantes_api"))),
    path("gestion/", include((gestion_urlpatterns, "gestion"))),
]
