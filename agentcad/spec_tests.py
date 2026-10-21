"""SDD: deriva pruebas unittest de cada especificación (specs/<pieza>.json). Cada requisito -> test_req_<id>; cada zona obligatoria -> test_zona_<id>.
Los umbrales salen del JSON: editar el umbral cambia el test sin tocar código. La pieza se mide UNA vez por spec (check_spec) y los tests leen ese resultado.
  cumple -> pasa | no_cumple -> falla (con valor, umbral y margen) | no_evaluable -> se salta | incumplimiento_conocido -> fallo esperado (si pasa, avisa)
Uso:  python -m agentcad.spec_tests [pieza ...] [--specs DIR] [--fidelity MM]      (0 todo bien, 1 fallos, 2 spec inválida)"""
import argparse, json, re, sys, unittest
from pathlib import Path
from . import config, spec as sp

class SpecInvalida(ValueError): pass

def _nombre(x): return re.sub(r'\W', '_', str(x))

def generar_casos(spec):
    """Lista ordenada de casos derivados: zonas primero, luego requisitos."""
    return ([dict(tipo='zona', id=z['id'], definicion=z) for z in spec.get('zonas_obligatorias', [])] +
            [dict(tipo='requisito', id=q['id'], definicion=q) for q in spec.get('requisitos', [])])

def _cargar(spec):
    if isinstance(spec, (str, Path)): spec = json.loads(Path(spec).read_text())
    v = sp.check_spec_file(spec)
    if not v['valido']: raise SpecInvalida(f"especificación inválida ({spec.get('pieza') if isinstance(spec, dict) else '?'}): " + '; '.join(v['errores']))
    return spec

def construir_clase(spec, fidelity=1.0, nombre=None):
    spec = _cargar(spec); casos = generar_casos(spec)
    def setUpClass(cls):
        cls.resultado = sp.check_spec(spec['pieza'], spec=spec, fidelity_estructura=fidelity)
        if cls.resultado.get('estado') != 'ok': raise RuntimeError(f"check_spec falló: {cls.resultado}")
    ns = dict(setUpClass=classmethod(setUpClass), __doc__=f"Pruebas derivadas de la especificación de {spec['pieza']} (v{spec['version']})")
    for c in casos:
        d = c['definicion']
        def prueba(self, c=c, d=d):
            lista = self.resultado['zonas'] if c['tipo'] == 'zona' else self.resultado['requisitos']
            r = next(x for x in lista if x['id'] == c['id'])
            if r['estado'] == 'no_evaluable': self.skipTest(f"no_evaluable: {r.get('motivo', 'sin dato')}")
            if r['estado'] == 'no_cumple':
                self.fail(f"{c['tipo']} '{c['id']}': valor {r.get('valor')} {d.get('op', '')} umbral {r.get('umbral')} {d.get('unidad', '')} -> margen {r.get('margen')}"
                          + (f" (faltantes: {r['faltantes']})" if r.get('faltantes') else ''))
        prueba.__doc__ = (f"{d['metrica']} {d['op']} {d['valor']} {d['unidad']}" if c['tipo'] == 'requisito' else f"zona {d['tipo']}")
        if d.get('incumplimiento_conocido'): prueba = unittest.expectedFailure(prueba)
        ns[f"test_{'req' if c['tipo'] == 'requisito' else 'zona'}_{_nombre(c['id'])}"] = prueba
    return type(nombre or f"Spec_{_nombre(spec['pieza'])}", (unittest.TestCase,), ns)

def construir_suite(spec, fidelity=1.0):
    return unittest.defaultTestLoader.loadTestsFromTestCase(construir_clase(spec, fidelity))

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('piezas', nargs='*'); ap.add_argument('--specs', default=None); ap.add_argument('--fidelity', type=float, default=1.0)
    a = ap.parse_args(argv); d = Path(a.specs) if a.specs else config.specs_dir(); codigo = 0
    for f in sorted(d.glob('*.json')):
        if a.piezas and f.stem not in a.piezas: continue
        print(f'== {f.stem} ==', flush=True)
        try: suite = construir_suite(f, a.fidelity)
        except SpecInvalida as e: print(f'ESPECIFICACIÓN INVÁLIDA: {e}'); codigo = max(codigo, 2); continue
        r = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
        if not r.wasSuccessful(): codigo = max(codigo, 1)
    return codigo

if __name__ == '__main__': sys.exit(main())
