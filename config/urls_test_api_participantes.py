from django.urls import include, path

urlpatterns = [path("api/participantes/", include("talleres.urls_api_participantes"))]
