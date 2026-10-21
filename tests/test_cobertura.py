"""Pruebas de agentcad.cobertura (escritas antes de la implementación, TDD).

Todo el material de prueba vive en un directorio creado con tempfile y se
borra al terminar cada test. sys.modules y sys.path se restauran en tearDown.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from agentcad.cobertura import Medidor, lineas_ejecutables

RAIZ_PROYECTO = Path(__file__).resolve().parents[1]

# Líneas: 1 docstring (no ejecutable), 2 def, 3 if, 4 asignación, 5 else,
# 6 asignación, 7 return, 8 vacía, 9 def, 10-13 cuerpo de no_llamada.
MODULO = textwrap.dedent('''\
    """Módulo de prueba."""
    def clasifica(x):
        if x > 0:
            r = "positivo"
        else:
            r = "no positivo"
        return r

    def no_llamada(y):
        z = y * 2
        if z > 10:
            return "grande"
        return "pequeño"
''')

# Ejecutables esperadas: la def (2), if (3), r= (4), r= del else (6), return (7),
# def (9), z= (10), if (11), return (12) y return (13). La línea 5 ('else:') no cuenta.
EJECUTABLES_MODULO = {2, 3, 4, 6, 7, 9, 10, 11, 12, 13}

NUNCA = "X = 2\n\ndef f():\n    return 1\n"  # no se importa nunca: 0 % siempre

NOMBRES_TEMPORALES = {"pkgmini", "externo"}


class _ConTemporal(unittest.TestCase):
    """Crea un directorio temporal con un mini-paquete `pkgmini`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cobertura_test_")).resolve()
        self.modulos_antes = set(sys.modules)
        self.path_antes = list(sys.path)
        self.crear("pkgmini/__init__.py", "")
        self.crear("pkgmini/modulo.py", MODULO)
        self.crear("pkgmini/nunca.py", NUNCA)
        sys.path.insert(0, str(self.tmp))

    def tearDown(self):
        for nombre in list(sys.modules):
            if nombre not in self.modulos_antes and nombre.split(".")[0] in NOMBRES_TEMPORALES:
                del sys.modules[nombre]
        sys.path[:] = self.path_antes
        shutil.rmtree(self.tmp, ignore_errors=True)

    def crear(self, relativa, texto):
        ruta = self.tmp / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        importlib.invalidate_caches()
        return ruta

    def herramientas_en_uso(self):
        return [i for i in range(6) if sys.monitoring.get_tool(i) is not None]


class LineasEjecutablesTests(_ConTemporal):
    def test_lineas_de_codigo_sin_docstring(self):
        ruta = self.tmp / "pkgmini" / "modulo.py"
        self.assertEqual(lineas_ejecutables(ruta), EJECUTABLES_MODULO)
        self.assertNotIn(1, lineas_ejecutables(ruta))

    def test_fichero_vacio_no_tiene_lineas(self):
        ruta = self.tmp / "pkgmini" / "__init__.py"
        self.assertEqual(lineas_ejecutables(ruta), set())


class MedidorTests(_ConTemporal):
    def test_cobertura_parcial_de_una_rama(self):
        medidor = Medidor(self.tmp / "pkgmini")
        medidor.iniciar()
        try:
            modulo = __import__("pkgmini.modulo", fromlist=["clasifica"])
            modulo.clasifica(5)  # solo rama positiva
        finally:
            medidor.parar()

        informe = medidor.informe()
        # Las defs de nivel de módulo (2 y 9) se ejecutan al importar.
        entrada = informe["ficheros"]["modulo.py"]
        self.assertEqual(entrada["ejecutables"], 10)
        self.assertEqual(entrada["cubiertas"], 5)
        self.assertEqual(entrada["pct"], 50.0)
        self.assertEqual(entrada["faltan"], [6, 10, 11, 12, 13])

    def test_fichero_nunca_importado_cuenta_cero(self):
        medidor = Medidor(self.tmp / "pkgmini")
        medidor.iniciar()
        medidor.parar()

        entrada = medidor.informe()["ficheros"]["nunca.py"]
        self.assertEqual(entrada["ejecutables"], 3)
        self.assertEqual(entrada["cubiertas"], 0)
        self.assertEqual(entrada["pct"], 0.0)
        self.assertEqual(entrada["faltan"], [1, 3, 4])

    def test_total_suma_todos_los_ficheros(self):
        medidor = Medidor(self.tmp / "pkgmini")
        medidor.iniciar()
        try:
            modulo = __import__("pkgmini.modulo", fromlist=["clasifica"])
            modulo.clasifica(5)
        finally:
            medidor.parar()

        total = medidor.informe()["total"]
        self.assertEqual(total["ejecutables"], 13)
        self.assertEqual(total["cubiertas"], 5)
        self.assertEqual(total["pct"], 38.5)

    def test_excluir_omite_los_patrones(self):
        # Los patrones se comparan con la ruta relativa a raiz (p. ej. "nunca.py").
        medidor = Medidor(self.tmp / "pkgmini", excluir=("n*.py",))
        medidor.iniciar()
        medidor.parar()

        informe = medidor.informe()
        self.assertNotIn("nunca.py", informe["ficheros"])
        self.assertIn("modulo.py", informe["ficheros"])
        self.assertEqual(informe["total"]["ejecutables"], 10)

    def test_parar_libera_la_herramienta(self):
        antes = self.herramientas_en_uso()
        primero = Medidor(self.tmp / "pkgmini")
        primero.iniciar()
        self.assertNotEqual(self.herramientas_en_uso(), antes)
        primero.parar()
        self.assertEqual(self.herramientas_en_uso(), antes)

        segundo = Medidor(self.tmp / "pkgmini")
        segundo.iniciar()
        try:
            modulo = __import__("pkgmini.modulo", fromlist=["clasifica"])
            modulo.clasifica(-1)
        finally:
            segundo.parar()
        # Import (2, 9) + cuerpo con x=-1 (3, 6, 7) = 5 líneas.
        self.assertEqual(segundo.informe()["ficheros"]["modulo.py"]["cubiertas"], 5)

    def test_parar_libera_aunque_falle_algo(self):
        antes = self.herramientas_en_uso()
        medidor = Medidor(self.tmp / "pkgmini")
        medidor.iniciar()
        with mock.patch.object(sys.monitoring, "set_events", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                medidor.parar()
        self.assertEqual(self.herramientas_en_uso(), antes)

    def test_ficheros_fuera_de_raiz_no_aparecen(self):
        self.crear("externo/otro.py", "def g():\n    return 1\n\ng()\n")
        medidor = Medidor(self.tmp / "pkgmini")
        medidor.iniciar()
        try:
            __import__("externo.otro")
        finally:
            medidor.parar()

        ficheros = medidor.informe()["ficheros"]
        self.assertEqual(sorted(ficheros), ["__init__.py", "modulo.py", "nunca.py"])
        self.assertTrue(all(not os.path.isabs(k) for k in ficheros))


class CliTests(_ConTemporal):
    def ejecutar_cli(self, *args_cli):
        entorno = dict(os.environ)
        entorno["PYTHONPATH"] = os.pathsep.join(
            [str(RAIZ_PROYECTO), entorno.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        return subprocess.run(
            [sys.executable, "-m", "agentcad.cobertura", *args_cli],
            cwd=self.tmp,
            env=entorno,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def crear_tests(self, cuerpo):
        self.crear("tests/__init__.py", "")
        self.crear(
            "tests/test_uso.py",
            "import unittest\nfrom pkgmini.modulo import clasifica\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_uno(self):\n" + textwrap.indent(cuerpo, "        ") + "\n",
        )

    def argumentos(self, *extra):
        return [
            "--raiz", str(self.tmp / "pkgmini"),
            "--json", str(self.tmp / "cov.json"),
            *extra,
            "--", "discover", "-s", "tests", "-t", ".",
        ]

    def test_cli_correcta_escribe_json_y_sale_cero(self):
        self.crear_tests('self.assertEqual(clasifica(5), "positivo")\n')
        resultado = self.ejecutar_cli(*self.argumentos())
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn("modulo.py", resultado.stdout)

        datos = json.loads((self.tmp / "cov.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["ficheros"]["modulo.py"]["pct"], 50.0)
        self.assertEqual(datos["total"]["cubiertas"], 5)

    def test_cli_sale_con_error_si_falla_un_test(self):
        self.crear_tests("self.assertEqual(clasifica(5), 'otra cosa')\n")
        resultado = self.ejecutar_cli(*self.argumentos())
        self.assertNotEqual(resultado.returncode, 0)
        self.assertTrue((self.tmp / "cov.json").exists())

    def test_cli_sale_con_error_si_no_llega_al_minimo(self):
        self.crear_tests('self.assertEqual(clasifica(5), "positivo")\n')
        resultado = self.ejecutar_cli(*self.argumentos("--min", "99"))
        self.assertNotEqual(resultado.returncode, 0)


if __name__ == "__main__":
    unittest.main()
