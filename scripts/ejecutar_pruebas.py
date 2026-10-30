"""Ejecuta y cuenta la pirámide: 72 unitarias, 14 integración y 4 e2e."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

RAIZ = Path(__file__).resolve().parent.parent
EVIDENCIAS = RAIZ / "evidencias"


def ejecutar(comando, *, carpeta=RAIZ, entorno=None):
    subprocess.run(comando, cwd=carpeta, env=entorno, check=True)


def comprobar_informe(nombre, esperadas):
    casos = ET.parse(EVIDENCIAS / f"{nombre}.xml").findall(".//testcase")
    assert len(casos) == esperadas, f"{nombre}: se esperaban {esperadas} pruebas, hay {len(casos)}."
    assert all(c.find("skipped") is None for c in casos), f"{nombre}: hay pruebas omitidas."
    assert all(c.find("failure") is None and c.find("error") is None for c in casos), f"{nombre}: hay fallos."
    return {"cantidad": len(casos), "casos": [f"{c.get('classname')}.{c.get('name')}" for c in casos]}


@contextmanager
def mongodb_pruebas(ruta_mongod):
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    proceso = None
    temporal = None
    cliente = None
    base_preparada = False
    entorno = os.environ.copy()
    nombre = f"test_talleres_{uuid4().hex[:12]}"
    try:
        uri = os.getenv("MONGODB_TEST_URI")
        if not uri:
            binario = ruta_mongod or shutil.which("mongod")
            if not binario:
                raise RuntimeError("No se encontró mongod. Instala MongoDB local o configura MONGODB_TEST_URI para un entorno de pruebas.")
            temporal = Path(tempfile.mkdtemp(prefix="talleres-pruebas-"))
            with socket.socket() as reserva:
                reserva.bind(("127.0.0.1", 0))
                puerto = reserva.getsockname()[1]
            uri = f"mongodb://127.0.0.1:{puerto}/?directConnection=true"
            proceso = subprocess.Popen([
                str(binario), "--dbpath", str(temporal), "--logpath", str(temporal / "mongodb.log"),
                "--bind_ip", "127.0.0.1", "--port", str(puerto), "--replSet", "pruebas",
                "--nounixsocket", "--wiredTigerCacheSizeGB", "0.25",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        cliente = MongoClient(uri, serverSelectionTimeoutMS=1000, connectTimeoutMS=1000)
        for _ in range(60):
            if proceso and proceso.poll() is not None:
                raise RuntimeError("MongoDB local no inició; revisa su instalación.")
            try:
                cliente.admin.command("ping")
                break
            except Exception:
                if not proceso:
                    raise RuntimeError("No se pudo acceder al MongoDB de pruebas; comprueba sus credenciales y acceso de red.") from None
                time.sleep(.25)
        else:
            raise RuntimeError("MongoDB local no respondió.")
        if proceso:
            cliente.admin.command("replSetInitiate", {"_id": "pruebas", "members": [{"_id": 0, "host": f"127.0.0.1:{puerto}"}]})
        for _ in range(60):
            saludo = cliente.admin.command("hello")
            if saludo.get("isWritablePrimary"):
                break
            time.sleep(.25)
        if not saludo.get("setName") and saludo.get("msg") != "isdbgrid":
            raise RuntimeError("Las transacciones requieren un replica set o un clúster compatible.")
        if cliente[nombre].list_collection_names():
            raise RuntimeError("La base generada ya contiene datos; no se ejecutarán las pruebas.")
        entorno.update(EJECUTAR_PRUEBAS_MONGODB="1", MONGODB_TEST_URI=uri, MONGODB_TEST_DATABASE=nombre)
        base_preparada = True
        print(f"Base exclusiva de esta ejecución: {nombre}", flush=True)
        yield entorno
    finally:
        error_limpieza = False
        if cliente is not None:
            # Esta base se generó aquí; nunca se toma el nombre del .env de la app.
            try:
                if base_preparada:
                    cliente.drop_database(nombre)
            except PyMongoError:
                error_limpieza = True
            finally:
                cliente.close()
        if proceso:
            proceso.terminate()
            try:
                proceso.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proceso.kill()
                proceso.wait()
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)
        if error_limpieza:
            raise RuntimeError(f"No se pudo limpiar la base de pruebas {nombre}.") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completa", action="store_true", help="Incluye MongoDB real y navegador: 90 pruebas.")
    parser.add_argument("--mongod", help="Ruta al binario mongod si no está en PATH.")
    args = parser.parse_args()
    EVIDENCIAS.mkdir(exist_ok=True)
    for nombre in ("unitarios-python.xml", "unitarios-react.xml", "integracion.xml", "e2e.xml", "resumen-pruebas.json"):
        (EVIDENCIAS / nombre).unlink(missing_ok=True)
    shutil.rmtree(EVIDENCIAS / "e2e", ignore_errors=True)
    # Una configuración de aplicación heredada no puede seleccionar la base del equipo.
    entorno = os.environ.copy()
    entorno["DJANGO_SETTINGS_MODULE"] = "config.settings_test_api_participantes"
    resultados = {}
    ejecutar([sys.executable, "-m", "pytest", "tests/unitarios", "-q", "--ds=config.settings_test_api_participantes",
              f"--junitxml={EVIDENCIAS / 'unitarios-python.xml'}"], entorno=entorno)
    resultados["unitarios_python"] = comprobar_informe("unitarios-python", 60)
    ejecutar(["npm", "test", "--", "--reporter=junit", "--outputFile=../evidencias/unitarios-react.xml"], carpeta=RAIZ / "frontend")
    resultados["unitarios_react"] = comprobar_informe("unitarios-react", 12)
    if args.completa:
        ejecutar(["npm", "run", "build"], carpeta=RAIZ / "frontend")
        with mongodb_pruebas(args.mongod) as entorno_mongo:
            for grupo, cantidad in (("integracion", 14), ("e2e", 4)):
                ejecutar([sys.executable, "-m", "pytest", f"tests/{grupo}", "-q", "--ds=config.settings_test_mongodb", "--create-db",
                          f"--junitxml={EVIDENCIAS / (grupo + '.xml')}"], entorno=entorno_mongo)
                resultados[grupo] = comprobar_informe(grupo, cantidad)
    total = sum(r["cantidad"] for r in resultados.values())
    (EVIDENCIAS / "resumen-pruebas.json").write_text(json.dumps({"total": total, "grupos": resultados}, ensure_ascii=False, indent=2))
    print(f"\n{total} pruebas aprobadas: " + ("72 unitarias, 14 integración y 4 end to end." if args.completa else "72 unitarias. Usa --completa para las 90."))


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError, AssertionError) as error:
        print(f"Suite detenida: {error}", file=sys.stderr)
        raise SystemExit(1)
