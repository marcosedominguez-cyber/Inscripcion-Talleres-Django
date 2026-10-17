import json
from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from talleres.api_participantes import catalogo_talleres_api
from talleres.models import Taller


@override_settings(PARTICIPANTES_FILTRO_PUBLICACION={"estado_publicacion": "aprobado"})
class CatalogoApiTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("participantes_api:catalogo")
        self.factory = RequestFactory()
        self.ahora = datetime(2026, 10, 17, 12, tzinfo=datetime_timezone.utc)

    def solicitud(self, metodo="get"):
        request = getattr(self.factory, metodo)(self.url)
        request.user = User(username="ismael")
        return request

    def test_devuelve_campos_publicos_y_consulta_futuros_en_orden(self):
        taller = Taller(codigo="T-001", nombre="Python", descripcion="Desde cero", cupos=5,
                       fecha_inicio=self.ahora + timedelta(days=3),
                       fecha_fin=self.ahora + timedelta(days=3, hours=2))
        with (
            patch("talleres.consultas_participantes.timezone.now", return_value=self.ahora),
            patch("talleres.consultas_participantes.Taller.objects.filter") as consulta,
        ):
            consulta.return_value.order_by.return_value = [taller]
            response = catalogo_talleres_api(self.solicitud())
        datos = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(datos["talleres"], [{"codigo": "T-001", "nombre": "Python", "descripcion": "Desde cero", "cupos": 5, "fecha_inicio": "2026-10-20T12:00:00Z", "fecha_fin": "2026-10-20T14:00:00Z"}])
        self.assertEqual(datos["usuario"], {"nombre": "ismael"})
        self.assertEqual(datos["zona_horaria"], "America/La_Paz")
        consulta.assert_called_once_with(fecha_inicio__gt=self.ahora, estado_publicacion="aprobado")
        consulta.return_value.order_by.assert_called_once_with("fecha_inicio", "codigo")

    def test_sin_sesion_devuelve_401_json_sin_consultar(self):
        with patch("talleres.api_participantes.listar_talleres_proximos") as consulta:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        consulta.assert_not_called()

    def test_catalogo_vacio_devuelve_lista_vacia(self):
        with patch("talleres.api_participantes.listar_talleres_proximos", return_value=[]):
            response = catalogo_talleres_api(self.solicitud())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["talleres"], [])

    def test_post_no_ejecuta_la_consulta(self):
        with patch("talleres.api_participantes.listar_talleres_proximos") as consulta:
            response = catalogo_talleres_api(self.solicitud("post"))
        self.assertEqual(response.status_code, 405)
        consulta.assert_not_called()

    def test_error_de_base_responde_503_sin_exponer_detalles(self):
        with patch("talleres.api_participantes.listar_talleres_proximos", side_effect=DatabaseError("detalle interno")):
            response = catalogo_talleres_api(self.solicitud())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("detalle interno", response.content.decode())

    @override_settings(PARTICIPANTES_FILTRO_PUBLICACION=None)
    def test_sin_filtro_de_aprobacion_no_publica_talleres(self):
        response = catalogo_talleres_api(self.solicitud())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("talleres", json.loads(response.content))
