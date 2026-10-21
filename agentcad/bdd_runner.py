"""Ejecutor mínimo de Gherkin en español (sin behave ni pytest-bdd en el venv).
Soporta: Característica, Antecedentes, Escenario, Esquema del escenario + Ejemplos (tabla con |), pasos Dado/Dada/Cuando/Entonces/Y/E/Pero,
comentarios (#) y etiquetas (@) ignoradas. Los pasos se enlazan por expresión regular sobre el texto (sin la palabra clave).
Uso:  python -m agentcad.bdd_runner [directorio_features] [--pasos fichero.py]"""
import argparse, importlib.util, re, sys, traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

CLAVES = ('Dado', 'Dada', 'Dados', 'Dadas', 'Cuando', 'Entonces', 'Y', 'E', 'Pero')

@dataclass
class Escenario: nombre: str; pasos: list = field(default_factory=list)
@dataclass
class Feature: nombre: str = ''; antecedentes: list = field(default_factory=list); escenarios: list = field(default_factory=list)

def num(s): return float(str(s).replace(',', '.'))

def parsear(texto):
    f = Feature(); actual = None; modo = None; esquema = False; filas = []; cab = None
    def cerrar():
        nonlocal actual, esquema, filas, cab
        if actual is None: return
        if esquema:
            for fila in filas:
                d = dict(zip(cab, fila)); sub = lambda t: re.sub(r'<(\w+)>', lambda m: d[m.group(1)], t)
                f.escenarios.append(Escenario(f'{actual.nombre} [' + ', '.join(f'{k}={v}' for k, v in d.items()) + ']', [(k, sub(t)) for k, t in actual.pasos]))
        else: f.escenarios.append(actual)
        actual = None; esquema = False; filas = []; cab = None
    for crudo in texto.splitlines():
        l = crudo.strip()
        if not l or l.startswith('#') or l.startswith('@'): continue
        m = re.match(r'(Característica|Caracteristica):\s*(.*)', l)
        if m: f.nombre = m.group(2); continue
        if re.match(r'Antecedentes:', l): cerrar(); modo = 'ant'; continue
        m = re.match(r'(Esquema del escenario|Esquema del Escenario):\s*(.*)', l)
        if m: cerrar(); actual = Escenario(m.group(2)); esquema = True; modo = 'esc'; continue
        m = re.match(r'Escenario:\s*(.*)', l)
        if m: cerrar(); actual = Escenario(m.group(1)); modo = 'esc'; continue
        if re.match(r'Ejemplos:', l): modo = 'ej'; continue
        if l.startswith('|'):
            celdas = [c.strip() for c in l.strip('|').split('|')]
            if cab is None: cab = celdas
            else: filas.append(celdas)
            continue
        m = re.match(r'(' + '|'.join(CLAVES) + r')\s+(.*)', l)
        if m:
            paso = (m.group(1), m.group(2))
            (f.antecedentes if modo == 'ant' else actual.pasos).append(paso)
    cerrar(); return f

class Registro:
    def __init__(self): self.pasos = []
    def paso(self, patron):
        def deco(fn): self.pasos.append((re.compile(r'^' + patron + r'$'), fn)); return fn
        return deco
    def buscar(self, texto):
        for rx, fn in self.pasos:
            m = rx.match(texto)
            if m: return fn, m.groupdict()
        return None, None

def ejecutar(feature, registro, nuevo_contexto=SimpleNamespace):
    out = []
    for esc in feature.escenarios:
        ctx = nuevo_contexto(); estado, fallido, err, saltados = 'ok', None, None, []
        for kw, texto in feature.antecedentes + esc.pasos:
            if estado != 'ok': saltados.append(texto); continue
            fn, args = registro.buscar(texto)
            if fn is None: estado, fallido = 'indefinido', texto; continue
            try: fn(ctx, **args)
            except Exception as e:
                estado, fallido, err = 'fallo', texto, f'{type(e).__name__}: {e}' if not isinstance(e, AssertionError) else str(e)
                err_tb = traceback.format_exc(limit=3)
        out.append(dict(feature=feature.nombre, escenario=esc.nombre, estado=estado, paso_fallido=fallido, error=err, saltados=saltados))
    return out

def resumen(res):
    n = lambda e: sum(1 for r in res if r['estado'] == e)
    return dict(total=len(res), ok=n('ok'), fallo=n('fallo'), indefinido=n('indefinido'), exito=all(r['estado'] == 'ok' for r in res))

def cargar_pasos(ruta):
    spec = importlib.util.spec_from_file_location('pasos_bdd', ruta); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod.REGISTRO

def correr_directorio(directorio, pasos):
    reg = cargar_pasos(pasos); res = []
    for f in sorted(Path(directorio).glob('*.feature')): res += ejecutar(parsear(f.read_text()), reg)
    return res

def main(argv=None):
    ap = argparse.ArgumentParser(); here = Path(__file__).resolve().parent
    ap.add_argument('directorio', nargs='?', default=str(here / 'features')); ap.add_argument('--pasos', default=str(here / 'features' / 'pasos.py'))
    a = ap.parse_args(argv); res = correr_directorio(a.directorio, a.pasos)
    for r in res:
        print(f"[{r['estado'].upper():9}] {r['feature']} :: {r['escenario']}" + (f"\n    paso: {r['paso_fallido']}\n    {r['error']}" if r['estado'] != 'ok' else ''))
    s = resumen(res); print(f"\n{s['total']} escenarios: {s['ok']} ok, {s['fallo']} fallan, {s['indefinido']} indefinidos"); return 0 if s['exito'] else 1

if __name__ == '__main__': sys.exit(main())
