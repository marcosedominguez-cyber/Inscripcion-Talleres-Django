from django.urls import include, path

from talleres.urls import participantes_urlpatterns

urlpatterns = [
    path(
        "api/participantes/",
        include((participantes_urlpatterns, "participantes_api")),
    )
]
