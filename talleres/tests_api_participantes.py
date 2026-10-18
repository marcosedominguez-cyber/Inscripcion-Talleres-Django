import json
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase
from talleres.api_participantes import catalogo_talleres_api
from talleres.models import Usuario


class CatalogoApiTests(SimpleTestCase):
    def solicitud(self, rol):
        request = RequestFactory().get("/api/participantes/talleres/")
        request.user = User(username="ismael")
        request.user.perfil = Usuario(rol=rol)
        return request

    def test_participante_recibe_catalogo_vacio(self):
        response = catalogo_talleres_api(self.solicitud(Usuario.Rol.PARTICIPANTE))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["talleres"], [])

    def test_instructor_no_puede_consultar_catalogo(self):
        response = catalogo_talleres_api(self.solicitud(Usuario.Rol.INSTRUCTOR))
        self.assertEqual(response.status_code, 403)
