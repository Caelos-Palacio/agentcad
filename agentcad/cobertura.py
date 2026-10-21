"""Medidor de cobertura de líneas de bajo coste basado en sys.monitoring (Python 3.12+).

Solo usa la librería estándar. Cada ubicación (código, línea) se registra una
única vez: el callback devuelve sys.monitoring.DISABLE tras anotarla, de modo
que el coste por línea ya cubierta es prácticamente nulo.

Uso:
    python -m agentcad.cobertura [--raiz DIR] [--excluir PATRON ...] \\
        [--json SALIDA.json] [--min PCT] -- <args de unittest>

Sin argumentos tras '--' se ejecuta: discover -s tests -t .
(relativo al directorio de trabajo, que debe ser la raíz del proyecto).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import sys
import types
import unittest
from collections import defaultdict
from pathlib import Path

_DIR_PAQUETE = Path(__file__).resolve().parent
_ARGS_POR_DEFECTO = ["discover", "-s", "tests", "-t", "."]
_NOMBRE_HERRAMIENTA = "agentcad.cobertura"
_EVENTO = sys.monitoring.events.LINE


def _lineas_docstrings(arbol: ast.AST) -> set[int]:
    """Líneas ocupadas por docstrings de módulo, clase o función.

    Limitación: si un docstring comparte línea con otro código, esa línea
    también se considera docstring y deja de contar como ejecutable.
    """
    lineas: set[int] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not nodo.body:
            continue
        primera = nodo.body[0]
        if (
            isinstance(primera, ast.Expr)
            and isinstance(primera.value, ast.Constant)
            and isinstance(primera.value.value, str)
        ):
            lineas.update(range(primera.lineno, primera.end_lineno + 1))
    return lineas


def lineas_ejecutables(ruta) -> set[int]:
    """Devuelve las líneas con código ejecutable de un fichero .py.

    Compila el fichero y recorre recursivamente sus code objects con co_lines().
    Se excluyen las líneas que son solo docstring de módulo, clase o función.
    """
    ruta = Path(ruta)
    fuente = ruta.read_bytes()
    codigo = compile(fuente, str(ruta), "exec", dont_inherit=True)
    excluidas = _lineas_docstrings(ast.parse(fuente, filename=str(ruta)))

    lineas: set[int] = set()
    pendientes = [codigo]
    while pendientes:
        objeto = pendientes.pop()
        for _inicio, _fin, linea in objeto.co_lines():
            # co_lines() puede dar None o 0 para instrucciones sintéticas sin línea real.
            if linea and linea not in excluidas:
                lineas.add(linea)
        pendientes.extend(c for c in objeto.co_consts if isinstance(c, types.CodeType))
    return lineas


class Medidor:
    """Registra las líneas ejecutadas de los .py bajo `raiz`."""

    def __init__(self, raiz, excluir=()):
        self.raiz = Path(raiz).resolve()
        self.excluir = tuple(excluir)
        self._cubiertas: set[tuple[str, int]] = set()
        self._relativos: dict[str, str | None] = {}
        self._herramienta: int | None = None

    def _ruta_relativa(self, nombre_fichero: str) -> str | None:
        """Ruta relativa a `raiz` si el fichero debe medirse; None si no."""
        if nombre_fichero in self._relativos:
            return self._relativos[nombre_fichero]

        resultado = None
        ruta = Path(nombre_fichero).resolve()
        if ruta.suffix == ".py" and ruta.is_relative_to(self.raiz):
            relativa = ruta.relative_to(self.raiz).as_posix()
            if not any(fnmatch.fnmatch(relativa, patron) for patron in self.excluir):
                resultado = relativa
        self._relativos[nombre_fichero] = resultado
        return resultado

    def _al_ejecutar_linea(self, codigo, linea):
        relativa = self._ruta_relativa(codigo.co_filename)
        if relativa is not None:
            self._cubiertas.add((relativa, linea))
        # Cada ubicación se anota una sola vez; ajenas o ya vistas se desactivan.
        return sys.monitoring.DISABLE

    def iniciar(self):
        if self._herramienta is not None:
            raise RuntimeError("El medidor ya está iniciado")

        monitor = sys.monitoring
        for identificador in range(6):
            try:
                monitor.use_tool_id(identificador, _NOMBRE_HERRAMIENTA)
            except ValueError:
                continue
            self._herramienta = identificador
            break
        else:
            raise RuntimeError("No hay identificador libre para sys.monitoring")

        try:
            monitor.register_callback(identificador, _EVENTO, self._al_ejecutar_linea)
            monitor.restart_events()  # reactiva ubicaciones desactivadas en medidas previas
            monitor.set_events(identificador, _EVENTO)
        except BaseException:
            self.parar()
            raise

    def parar(self):
        identificador = self._herramienta
        if identificador is None:
            return
        monitor = sys.monitoring
        try:
            monitor.set_events(identificador, 0)
            monitor.register_callback(identificador, _EVENTO, None)
        finally:
            monitor.free_tool_id(identificador)
            self._herramienta = None

    def informe(self) -> dict:
        """Cobertura de todos los .py bajo `raiz` no excluidos (incluidos los nunca importados).

        Un fichero sin líneas ejecutables se da por cubierto al 100 %.
        """
        por_fichero: dict[str, set[int]] = defaultdict(set)
        for relativa, linea in self._cubiertas:
            por_fichero[relativa].add(linea)

        ficheros = {}
        total_ejecutables = 0
        total_cubiertas = 0
        for ruta in sorted(self.raiz.rglob("*.py")):
            partes = ruta.relative_to(self.raiz).parts
            if any(p == "__pycache__" or p.startswith(".") for p in partes):
                continue
            relativa = ruta.relative_to(self.raiz).as_posix()
            if any(fnmatch.fnmatch(relativa, patron) for patron in self.excluir):
                continue

            ejecutables = lineas_ejecutables(ruta)
            cubiertas = por_fichero.get(relativa, set()) & ejecutables
            ficheros[relativa] = {
                "ejecutables": len(ejecutables),
                "cubiertas": len(cubiertas),
                "pct": _porcentaje(len(cubiertas), len(ejecutables)),
                "faltan": sorted(ejecutables - cubiertas),
            }
            total_ejecutables += len(ejecutables)
            total_cubiertas += len(cubiertas)

        return {
            "ficheros": ficheros,
            "total": {
                "ejecutables": total_ejecutables,
                "cubiertas": total_cubiertas,
                "pct": _porcentaje(total_cubiertas, total_ejecutables),
            },
        }


def _porcentaje(cubiertas: int, ejecutables: int) -> float:
    if ejecutables == 0:
        return 100.0
    return round(100.0 * cubiertas / ejecutables, 1)


def _separar_argumentos(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        indice = argv.index("--")
        return argv[:indice], argv[indice + 1:]
    return argv, []


def _imprimir_tabla(informe: dict) -> None:
    anchura = max([len(r) for r in informe["ficheros"]] + [len("Total"), len("Fichero")])
    print(f"{'Fichero':<{anchura}}  {'%':>6}  {'ejec.':>6}  {'cubr.':>6}")
    for relativa, datos in informe["ficheros"].items():
        print(f"{relativa:<{anchura}}  {datos['pct']:>5.1f}%  {datos['ejecutables']:>6}  {datos['cubiertas']:>6}")
    total = informe["total"]
    print(f"{'Total':<{anchura}}  {total['pct']:>5.1f}%  {total['ejecutables']:>6}  {total['cubiertas']:>6}")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    opciones, args_unittest = _separar_argumentos(argv)

    parser = argparse.ArgumentParser(prog="python -m agentcad.cobertura")
    parser.add_argument("--raiz", default=str(_DIR_PAQUETE),
                        help="directorio cuyos .py se miden (por defecto, el paquete agentcad)")
    parser.add_argument("--excluir", action="extend", nargs="+", default=[], metavar="PATRON",
                        help="patrones fnmatch sobre la ruta relativa a --raiz")
    parser.add_argument("--json", dest="salida_json", metavar="SALIDA.json",
                        help="escribe el informe en JSON")
    parser.add_argument("--min", dest="minimo", type=float, default=0.0,
                        help="porcentaje total mínimo exigido")
    args = parser.parse_args(opciones)

    if not args_unittest:
        args_unittest = list(_ARGS_POR_DEFECTO)

    medidor = Medidor(args.raiz, excluir=args.excluir)
    medidor.iniciar()
    try:
        programa = unittest.main(module=None, argv=["unittest", *args_unittest],
                                 exit=False)
    finally:
        medidor.parar()

    informe = medidor.informe()
    _imprimir_tabla(informe)
    if args.salida_json:
        Path(args.salida_json).write_text(
            json.dumps(informe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    tests_ok = programa.result.wasSuccessful()
    cobertura_ok = informe["total"]["pct"] >= args.minimo
    if not cobertura_ok:
        print(f"Cobertura total {informe['total']['pct']}% inferior al mínimo {args.minimo}%")
    return 0 if (tests_ok and cobertura_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
