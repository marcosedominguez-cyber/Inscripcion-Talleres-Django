"""Pruebas del decorador transaccional y del mixin de formularios del Admin."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.admin import ModelAdmin
from django.db import DEFAULT_DB_ALIAS, DatabaseError
from django.test import RequestFactory, SimpleTestCase

from talleres import servicios
from talleres.admin import TallerAdmin
from talleres.admin_site import admin_site
from talleres.models import Taller


class ErrorTransitorio(Exception):
    def has_error_label(self, etiqueta):
        return etiqueta == "TransientTransactionError"


class AtomicEspia:
    def __init__(self, eventos):
        self.eventos = eventos

    def __enter__(self):
        self.eventos.append("entrar")
        return self

    def __exit__(self, tipo, valor, traceback):
        self.eventos.append(("salir", tipo))
        return False


def conexion(*, mongo=False, django=False):
    return SimpleNamespace(
        in_atomic_block_mongo=mongo,
        in_atomic_block=django,
    )


class TransaccionConReintentosTests(SimpleTestCase):
    def decorar(self, funcion):
        return servicios.transaccion_con_reintentos(funcion)

    def test_sin_transaccion_exterior_abre_una_transaccion_mongo(self):
        eventos = []
        funcion = Mock(return_value="resultado")

        with (
            patch.object(servicios, "_conexion", return_value=conexion()),
            patch.object(
                servicios, "atomic",
                side_effect=lambda using: AtomicEspia(eventos),
            ) as abrir,
        ):
            resultado = self.decorar(funcion)("argumento")

        self.assertEqual(resultado, "resultado")
        abrir.assert_called_once_with(using=DEFAULT_DB_ALIAS)
        self.assertEqual(eventos, ["entrar", ("salir", None)])
        funcion.assert_called_once_with("argumento")

    def test_con_transaccion_mongo_exterior_participa_sin_abrir_ni_confirmar(self):
        eventos = []
        funcion = Mock(return_value="resultado")

        with (
            patch.object(
                servicios, "_conexion",
                return_value=conexion(mongo=True),
            ),
            patch.object(
                servicios, "atomic",
                side_effect=lambda using: AtomicEspia(eventos),
            ) as abrir,
        ):
            resultado = self.decorar(funcion)("argumento")

        self.assertEqual(resultado, "resultado")
        abrir.assert_not_called()
        self.assertEqual(eventos, [])
        funcion.assert_called_once_with("argumento")

    def test_con_atomic_django_sin_transaccion_mongo_falla_antes_de_escribir(self):
        llamadas = []

        def funcion():
            llamadas.append(1)

        with (
            patch.object(
                servicios, "_conexion",
                return_value=conexion(django=True),
            ),
            patch.object(servicios, "atomic") as abrir,
        ):
            with self.assertRaisesRegex(
                servicios.TransaccionMongoRequeridaError,
                "transacción MongoDB",
            ):
                self.decorar(funcion)()

        abrir.assert_not_called()
        self.assertEqual(llamadas, [])

    def test_reintenta_solo_cuando_es_responsable_de_la_transaccion(self):
        eventos = []
        intentos = {"cantidad": 0}
        funcion = Mock(return_value="resultado")

        class AtomicReintento(AtomicEspia):
            def __init__(self, eventos, fallar):
                super().__init__(eventos)
                self.fallar = fallar

            def __exit__(self, tipo, valor, traceback):
                super().__exit__(tipo, valor, traceback)
                if self.fallar and tipo is None:
                    raise DatabaseError("Reintentar commit") from ErrorTransitorio()
                return False

        def abrir(using):
            intentos["cantidad"] += 1
            return AtomicReintento(eventos, intentos["cantidad"] == 1)

        with (
            patch.object(servicios, "_conexion", return_value=conexion()),
            patch.object(servicios, "atomic", side_effect=abrir),
            patch.object(servicios.time, "sleep") as dormir,
        ):
            resultado = self.decorar(funcion)()

        self.assertEqual(resultado, "resultado")
        self.assertEqual(funcion.call_count, 2)
        self.assertEqual(intentos["cantidad"], 2)
        dormir.assert_called_once()

    def test_servicio_anidado_no_reintenta_ni_oculta_el_error(self):
        funcion = Mock()
        error = DatabaseError("Fallo transitorio")
        error.__cause__ = ErrorTransitorio()
        funcion.side_effect = error

        with (
            patch.object(
                servicios, "_conexion",
                return_value=conexion(mongo=True),
            ),
            patch.object(servicios, "atomic") as abrir,
        ):
            with self.assertRaises(DatabaseError):
                self.decorar(funcion)()

        abrir.assert_not_called()
        funcion.assert_called_once_with()

    def test_excepcion_del_servicio_sale_del_atomic_exterior(self):
        eventos = []
        funcion = Mock(side_effect=RuntimeError("falló el servicio"))

        with (
            patch.object(servicios, "_conexion", return_value=conexion()),
            patch.object(
                servicios, "atomic",
                side_effect=lambda using: AtomicEspia(eventos),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "falló el servicio"):
                self.decorar(funcion)()

        self.assertEqual(eventos, ["entrar", ("salir", RuntimeError)])


class ChangeFormTransaccionalTests(SimpleTestCase):
    def setUp(self):
        self.admin = TallerAdmin(Taller, admin_site)
        self.factory = RequestFactory()

    def test_metodos_seguros_no_abren_una_transaccion_mongo(self):
        for metodo in ("get", "head", "options", "trace"):
            with self.subTest(metodo=metodo):
                request = getattr(self.factory, metodo)("/admin/talleres/taller/1/change/")
                respuesta = object()

                with (
                    patch.object(
                        ModelAdmin, "changeform_view", return_value=respuesta,
                    ) as delegar,
                    patch("talleres.admin_transacciones.atomic") as abrir,
                ):
                    resultado = self.admin.changeform_view(request, object_id="1")

                self.assertIs(resultado, respuesta)
                delegar.assert_called_once_with(request, "1", "", None)
                abrir.assert_not_called()

    def test_post_abre_transaccion_mongo_y_llama_changeform_view_privado(self):
        request = self.factory.post("/admin/talleres/taller/1/change/")
        request._dont_enforce_csrf_checks = True
        respuesta = object()
        eventos = []

        with (
            patch.object(self.admin, "_changeform_view", return_value=respuesta) as privado,
            patch.object(ModelAdmin, "changeform_view") as publico,
            patch(
                "talleres.admin_transacciones.atomic",
                side_effect=lambda using: AtomicEspia(eventos),
            ) as abrir,
        ):
            resultado = self.admin.changeform_view(
                request, object_id="1", form_url="/form/", extra_context={"x": 1},
            )

        self.assertIs(resultado, respuesta)
        abrir.assert_called_once_with(using=DEFAULT_DB_ALIAS)
        privado.assert_called_once_with(
            request, "1", "/form/", {"x": 1},
        )
        publico.assert_not_called()
        self.assertEqual(eventos, ["entrar", ("salir", None)])
