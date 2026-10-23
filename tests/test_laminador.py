"""Comparación con el laminador (validacion/laminador): métricas puras con datos SINTÉTICOS y coherencia de las tablas guardadas (datos/*.json -> resultados.json).
Las tablas son del proyecto de origen y son DIGITALES; no se prueba aquí ninguna impresión."""
import json, unittest
from pathlib import Path
from validacion.laminador import metricas as m

RAIZ = Path(__file__).resolve().parents[1] / 'validacion' / 'laminador'

def casi_igual(a, b, rel=1e-9, abs_=1e-12, ruta='raiz'):
    """Comparación recursiva con tolerancia para floats (ajustes numéricos difieren en los últimos dígitos entre plataformas/BLAS); el resto, igualdad exacta."""
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)): raise AssertionError(f'{ruta}: {a!r} != {b!r}')
        if abs(a - b) > max(abs_, rel * max(abs(a), abs(b))): raise AssertionError(f'{ruta}: {a!r} != {b!r} (rel > {rel})')
    elif isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b): raise AssertionError(f'{ruta}: claves distintas {sorted(set(a) ^ set(b))}')
        for k in a: casi_igual(a[k], b[k], rel, abs_, f'{ruta}.{k}')
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b): raise AssertionError(f'{ruta}: longitudes {len(a)} != {len(b)}')
        for i, (x, y) in enumerate(zip(a, b)): casi_igual(x, y, rel, abs_, f'{ruta}[{i}]')
    elif a != b: raise AssertionError(f'{ruta}: {a!r} != {b!r}')

class Matriz(unittest.TestCase):
    def test_clases_y_tasas(self):
        r = m.matriz(dict(a=True, b=True, c=False, d=False), dict(a=True, b=False, c=True, d=False))
        self.assertEqual((r['tp'], r['fp'], r['fn'], r['tn']), (1, 1, 1, 1)); self.assertEqual(r['clases'], dict(a='TP', b='FP', c='FN', d='TN')); self.assertEqual((r['precision'], r['sensibilidad']), (0.5, 0.5))
    def test_sin_positivos_no_inventa_tasas(self):
        r = m.matriz(dict(a=False), dict(a=False)); self.assertIsNone(r['precision']); self.assertIsNone(r['sensibilidad'])
    def test_mayoria_de_impresoras(self):
        self.assertTrue(m.mayoria(dict(x=dict(i=1), y=dict(i=2), z=dict(i=0)), 'i')); self.assertFalse(m.mayoria(dict(x=dict(i=1), y=dict(i=0), z=dict(i=0)), 'i'))

class Comparar(unittest.TestCase):
    def test_umbrales_por_defecto_y_categorias(self):
        pr = dict(p=dict(islas=1, luz_puente_mm=12.0, voladizo_fraccion=0.03), q=dict(islas=0, luz_puente_mm=9.0, voladizo_fraccion=0.001))
        B = lambda isl, pu, vo: {i: dict(islas=isl, puentes_largos=pu, voladizos_fuertes=vo) for i in m.IMPRESORAS}
        ver = dict(p=dict(A=dict(islas=1, puentes_largos=1, voladizos_fuertes=0, luz_max_mm=11.0), B=B(0, 1, 0)), q=dict(A=dict(islas=0, puentes_largos=0, voladizos_fuertes=1, luz_max_mm=None), B=B(0, 0, 1)))
        c = m.comparar(pr, ver)['categorias']
        self.assertEqual(c['islas']['A']['clases'], dict(p='TP', q='TN')); self.assertEqual(c['islas']['B']['clases'], dict(p='FP', q='TN'))
        self.assertEqual(c['puentes_largos']['A']['clases'], dict(p='TP', q='TN')); self.assertEqual(c['voladizos']['A']['clases'], dict(p='TP', q='FN'))

class Guardado(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pr, cls.ver, cls.lam = (json.loads((RAIZ / 'datos' / f'{n}.json').read_text()) for n in ('printability', 'verdad_laminador', 'laminado'))
        cls.res = json.loads((RAIZ / 'resultados.json').read_text())
    def test_resultados_se_reproducen_desde_los_datos(self):
        casi_igual(json.loads(json.dumps(m.comparar(self.pr, self.ver))), self.res['comparacion'])
        casi_igual(json.loads(json.dumps(m.masa_y_tiempo(self.lam))), self.res['masa_tiempo'])
    def test_informe_coincide_con_los_resultados(self):
        self.assertEqual(m.informe(self.res['comparacion'], self.res['masa_tiempo'], self.pr, self.ver), (RAIZ / 'INFORME.md').read_text())
    def test_16_piezas_y_confusion_suma_16(self):
        self.assertEqual(len(self.pr), 16); self.assertEqual(set(self.pr), set(self.ver))
        for cat in self.res['comparacion']['categorias'].values():
            for v in 'AB': self.assertEqual(sum(cat[v][k] for k in ('tp', 'fp', 'fn', 'tn')), 16)
    def test_totales_de_tiempo_y_filamento_son_los_del_informe_de_laminado(self):
        p = self.res['masa_tiempo']['por_impresora']
        self.assertEqual({k: hms for k, hms in ((k, m.hms(v['tiempo_s'])) for k, v in p.items())}, dict(kobra_x='19 h 51 min', kobra_3='17 h 55 min', kobra_2_neo='25 h 15 min'))
        for k, g in (('kobra_x', 393.0), ('kobra_3', 393.8), ('kobra_2_neo', 405.4)): self.assertAlmostEqual(p[k]['filamento_g'], g, places=1)
    def test_la_validacion_cruzada_declara_pocos_grupos(self):
        for d in self.res['masa_tiempo']['por_impresora'].values():
            for k in ('filamento', 'tiempo'): self.assertFalse(d[k]['fiable']); self.assertEqual(d[k]['cv']['n_grupos'], 4)
    def test_solo_tablas_pequenas(self):
        total = sum(f.stat().st_size for f in RAIZ.rglob('*') if f.is_file() and '__pycache__' not in f.parts); self.assertLess(total, 200_000)
        self.assertEqual([f.name for f in RAIZ.rglob('*') if f.suffix.lower() in ('.gcode', '.stl', '.3mf')], [])

if __name__ == '__main__': unittest.main()
