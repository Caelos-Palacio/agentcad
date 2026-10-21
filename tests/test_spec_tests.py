import copy, io, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from tests import fixtures as fx
from tests.test_spec_sdd import spec_ok
from agentcad import spec_tests as st, spec as sp

def spec_cubo(ruta, masa=5.0):
    s = spec_ok(); s['pieza'] = ruta; s['zonas_obligatorias'] = [dict(id='lleno', tipo='caja_material', caja_mm=[[0, 0, 0], [10, 10, 5]], fraccion_min=0.99)]
    s['requisitos'] = [dict(id='masa', metrica='describe.masa_estimada_g', op='<=', valor=masa, unidad='g', prioridad=1),
                       dict(id='una_pieza', metrica='describe.componentes', op='<=', valor=1, unidad='adimensional', prioridad=1),
                       dict(id='margen', metrica='estructura.margen_min', op='>=', valor=2.0, unidad='adimensional', prioridad=1)]
    return s

def correr(suite):
    r = __import__('unittest').TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite); return r

class Generador(unittest.TestCase):
    def test_un_caso_por_requisito_y_zona(self):
        casos = st.generar_casos(spec_cubo(fx.cubo(10)))
        self.assertEqual([(c['tipo'], c['id']) for c in casos], [('zona', 'lleno'), ('requisito', 'masa'), ('requisito', 'una_pieza'), ('requisito', 'margen')])
    def test_suite_tiene_un_test_por_caso_con_nombre_derivado(self):
        suite = st.construir_suite(spec_cubo(fx.cubo(10)))
        nombres = sorted(t._testMethodName for t in suite)
        self.assertEqual(nombres, ['test_req_margen', 'test_req_masa', 'test_req_una_pieza', 'test_zona_lleno'])
    def test_cumplen_pasan_y_no_evaluable_se_salta(self):
        r = correr(st.construir_suite(spec_cubo(fx.cubo(10))))
        self.assertTrue(r.wasSuccessful(), r.failures); self.assertEqual(r.testsRun, 4)
        self.assertEqual(len(r.skipped), 1); self.assertIn('no_evaluable', r.skipped[0][1])        # margen: cubo sin modelo de carga
    def test_cambiar_el_umbral_de_la_spec_cambia_el_test_sin_tocar_codigo(self):
        ruta = fx.cubo(10)
        ok = correr(st.construir_suite(spec_cubo(ruta, masa=5.0))); mal = correr(st.construir_suite(spec_cubo(ruta, masa=0.1)))
        self.assertTrue(ok.wasSuccessful()); self.assertFalse(mal.wasSuccessful())
        self.assertEqual(len(mal.failures), 1); self.assertIn('test_req_masa', str(mal.failures[0][0])); self.assertIn('margen', mal.failures[0][1])
    def test_incumplimiento_conocido_es_fallo_esperado(self):
        s = spec_cubo(fx.cubo(10), masa=0.1); s['requisitos'][0]['incumplimiento_conocido'] = 'hallazgo documentado'
        r = correr(st.construir_suite(s)); self.assertTrue(r.wasSuccessful()); self.assertEqual(len(r.expectedFailures), 1)
    def test_incumplimiento_conocido_que_ya_se_cumple_avisa(self):
        s = spec_cubo(fx.cubo(10), masa=5.0); s['requisitos'][0]['incumplimiento_conocido'] = 'ya arreglado'
        r = correr(st.construir_suite(s)); self.assertFalse(r.wasSuccessful()); self.assertEqual(len(r.unexpectedSuccesses), 1)
    def test_spec_invalida_se_rechaza_antes_de_derivar(self):
        s = spec_cubo(fx.cubo(10)); s.pop('cargas')
        with self.assertRaises(st.SpecInvalida) as cm: st.construir_suite(s)
        self.assertIn('cargas', str(cm.exception))
    def test_se_mide_una_sola_vez_por_spec(self):
        with mock.patch.object(sp, 'check_spec', wraps=sp.check_spec) as m:
            correr(st.construir_suite(spec_cubo(fx.cubo(10))))
        self.assertEqual(m.call_count, 1)
    def test_zona_incumplida_falla(self):
        s = spec_cubo(fx.cubo(10)); s['zonas_obligatorias'][0]['caja_mm'] = [[20, 0, 0], [30, 10, 5]]
        r = correr(st.construir_suite(s)); self.assertEqual(len(r.failures), 1); self.assertIn('zona_lleno', str(r.failures[0][0]))
    def test_error_de_herramienta_hace_fallar_la_clase(self):
        s = spec_cubo('no_existe_xyz'); r = correr(st.construir_suite(s)); self.assertFalse(r.wasSuccessful())

class CLI(unittest.TestCase):
    def dir(self, masa):
        d = Path(tempfile.mkdtemp()); s = spec_cubo(fx.cubo(10), masa); (d / 'cubo_cli.json').write_text(json.dumps(s)); return d
    def test_main_codigo_de_salida_segun_la_spec(self):
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()) as o: self.assertEqual(st.main(['--specs', str(self.dir(5.0))]), 0)
        self.assertIn('cubo_cli', o.getvalue())
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(st.main(['--specs', str(self.dir(0.1))]), 1)
    def test_main_rechaza_spec_mal_formada_con_codigo_2(self):
        import contextlib
        d = Path(tempfile.mkdtemp()); (d / 'mala.json').write_text('{"pieza": "x"}')
        with contextlib.redirect_stdout(io.StringIO()) as o: self.assertEqual(st.main(['--specs', str(d)]), 2)
        self.assertIn('INVÁLIDA', o.getvalue())
    def test_main_filtra_por_pieza(self):
        import contextlib
        d = self.dir(5.0)
        with contextlib.redirect_stdout(io.StringIO()) as o: self.assertEqual(st.main(['--specs', str(d), 'otra']), 0)
        self.assertNotIn('cubo_cli', o.getvalue())
if __name__ == '__main__': unittest.main()
