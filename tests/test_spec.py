import json, os, unittest
from tests import fixtures as fx
from agentcad import spec as sp, lightening as lg, registro as rg
import tempfile
from pathlib import Path
from tests._marcas import pesada

@pesada
class CheckSpec(unittest.TestCase):
    def setUp(self):
        self.reg = tempfile.mkdtemp(prefix='agentcad-reg-'); os.environ['AGENTCAD_REGISTRO_DIR'] = self.reg
    def tearDown(self): os.environ.pop('AGENTCAD_REGISTRO_DIR', None)
    def spec_base(self, ref):
        return dict(pieza='placa_s', version=1, prioridades=['fabricabilidad', 'masa'],
            zonas_obligatorias=[dict(id='agujeros_M3', tipo='agujeros_conservados', referencia=ref, tolerancia_mm=0.1)],
            requisitos=[dict(id='pared_min', metrica='fabricabilidad.pared_min_mm', op='>=', valor=1.2, prioridad=1),
                        dict(id='masa', metrica='describe.masa_estimada_g', op='<=', valor=30.0, prioridad=2),
                        dict(id='interf', metrica='interferencia.volumen_total_mm3', op='<=', valor=0.1)])
    def test_cumple_con_margen_por_requisito(self):
        ruta = fx.placa_con_pilares(nombre='placa_s.stl')
        r = sp.check_spec(ruta, spec=self.spec_base(ruta))
        self.assertEqual(r['estado'], 'ok')
        por = {q['id']: q for q in r['requisitos']}
        self.assertEqual(por['pared_min']['estado'], 'cumple'); self.assertGreater(por['pared_min']['margen'], 0)
        self.assertAlmostEqual(por['pared_min']['margen'], por['pared_min']['valor'] - 1.2, places=3)
        self.assertEqual(por['masa']['estado'], 'cumple'); self.assertAlmostEqual(por['masa']['margen'], 30.0 - por['masa']['valor'], places=3)
        self.assertEqual(r['zonas'][0]['estado'], 'cumple')
        self.assertEqual(r['veredicto'], 'cumple')
    def test_no_cumple_y_margen_negativo(self):
        ruta = fx.placa_con_pilares(nombre='placa_s.stl'); s = self.spec_base(ruta); s['requisitos'][1]['valor'] = 0.5
        r = sp.check_spec(ruta, spec=s)
        m = next(q for q in r['requisitos'] if q['id'] == 'masa')
        self.assertEqual(m['estado'], 'no_cumple'); self.assertLess(m['margen'], 0); self.assertEqual(r['veredicto'], 'no_cumple')
    def test_zona_agujeros_falla_si_falta_un_agujero(self):
        import manifold3d as M
        ruta = fx.placa_con_pilares(nombre='placa_s.stl')
        tapada = fx.guardar(M.Manifold.cube([60, 40, 3]), 'placa_tapada.stl')       # sin agujeros
        r = sp.check_spec(tapada, spec=self.spec_base(ruta))
        z = r['zonas'][0]; self.assertEqual(z['estado'], 'no_cumple'); self.assertEqual(len(z['faltantes']), 4)
        self.assertEqual(r['veredicto'], 'no_cumple')
    def test_zona_caja_material(self):
        ruta = fx.cubo(10)
        s = dict(pieza='cubo', version=1, prioridades=[], requisitos=[], zonas_obligatorias=[
            dict(id='lleno', tipo='caja_material', caja_mm=[[0, 0, 0], [10, 10, 5]], fraccion_min=0.99),
            dict(id='vacio', tipo='caja_hueco', caja_mm=[[20, 0, 0], [30, 10, 5]], fraccion_max=0.01),
            dict(id='mal', tipo='caja_material', caja_mm=[[5, 0, 0], [20, 10, 5]], fraccion_min=0.9)])
        z = {q['id']: q for q in sp.check_spec(ruta, spec=s)['zonas']}
        self.assertEqual((z['lleno']['estado'], z['vacio']['estado'], z['mal']['estado']), ('cumple', 'cumple', 'no_cumple'))
        self.assertAlmostEqual(z['mal']['valor'], 1 / 3, places=3)
    def test_requisito_estructural_sin_modelo_no_es_evaluable(self):
        ruta = fx.cubo(10)
        s = dict(pieza='cubo', version=1, prioridades=[], zonas_obligatorias=[], requisitos=[dict(id='margen', metrica='estructura.margen_min', op='>=', valor=2.0)])
        r = sp.check_spec(ruta, spec=s)
        self.assertEqual(r['requisitos'][0]['estado'], 'no_evaluable'); self.assertEqual(r['veredicto'], 'no_validado')
    def test_un_fallo_domina_sobre_no_evaluable(self):
        ruta = fx.cubo(10)
        s = dict(pieza='cubo', version=1, prioridades=[], zonas_obligatorias=[], requisitos=[
            dict(id='margen', metrica='estructura.margen_min', op='>=', valor=2.0), dict(id='masa', metrica='describe.masa_estimada_g', op='<=', valor=0.1)])
        self.assertEqual(sp.check_spec(ruta, spec=s)['veredicto'], 'no_cumple')
    def test_spec_inexistente_y_invalida(self):
        self.assertEqual(sp.check_spec(fx.cubo(10))['codigo'], 'spec_no_encontrada')
        self.assertEqual(sp.check_spec(fx.cubo(10), spec={'requisitos': [{'id': 'x'}]})['codigo'], 'spec_invalida')
    def test_tolerancia_de_medida_declarada_en_el_requisito(self):
        ruta = fx.cubo(10)           # masa estimada 0.7... se usa la métrica de volumen vía describe.masa_estimada_g
        masa = sp.check_spec(ruta, spec=dict(pieza='c', version=1, requisitos=[dict(id='m', metrica='describe.masa_estimada_g', op='<=', valor=1.0)]))['requisitos'][0]['valor']
        s = lambda umbral, tol: dict(pieza='c', version=1, requisitos=[dict(id='m', metrica='describe.masa_estimada_g', op='<=', valor=umbral, tolerancia=tol)])
        sin = sp.check_spec(ruta, spec=s(masa - 0.05, 0.0))['requisitos'][0]; con = sp.check_spec(ruta, spec=s(masa - 0.05, 0.06))['requisitos'][0]
        self.assertEqual(sin['estado'], 'no_cumple'); self.assertEqual(con['estado'], 'cumple')
        self.assertGreater(con['margen'], 0); self.assertEqual(con['tolerancia'], 0.06)
    def test_cargas_y_supuestos_se_devuelven_en_la_salida(self):
        from tests.test_spec_sdd import spec_ok
        s = spec_ok(); s['pieza'] = 'x'; s['zonas_obligatorias'] = []; s['cargas'][0]['supuesto'] = True
        r = sp.check_spec(fx.cubo(10), spec=s); self.assertEqual(r['cargas'][0]['id'], 'mano'); self.assertEqual(r['supuestos'], ['mano'])
    def test_metrica_desconocida(self):
        s = dict(pieza='c', version=1, prioridades=[], zonas_obligatorias=[], requisitos=[dict(id='x', metrica='fabricabilidad.no_existe', op='>=', valor=1)])
        self.assertEqual(sp.check_spec(fx.cubo(10), spec=s)['requisitos'][0]['estado'], 'no_evaluable')
    def test_registrar_deja_linea(self):
        ruta = fx.placa_con_pilares(nombre='placa_s.stl'); s = self.spec_base(ruta); s['requisitos'][1]['valor'] = 0.5
        r = sp.check_spec(ruta, spec=s, registrar=True)
        self.assertTrue(r['registro']['hash_entradas'])
        lin = [json.loads(l) for l in (Path(self.reg) / 'registro.jsonl').read_text().splitlines()]
        self.assertEqual(lin[-1]['herramienta'], 'check_spec'); self.assertEqual(lin[-1]['resultado']['veredicto'], 'no_cumple')
    def test_specs_del_repositorio_validan_contra_su_esquema(self):
        from agentcad import config
        for f in config.specs_dir().glob('*.json'):
            self.assertEqual(sp.validar_spec(json.loads(f.read_text())), [], f.name)
        self.assertTrue(list(config.specs_dir().glob('*.json')))
if __name__ == '__main__': unittest.main()
