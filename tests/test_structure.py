import unittest, numpy as np, manifold3d as M
from tests import fixtures as fx
from agentcad import structure as st, benchmarks as bm

def barra(nombre='viga_test.stl', L=40.0, b=5.0, h=5.0):
    return fx.guardar(M.Manifold.cube([L, b, h]), nombre)
from tests._marcas import pesada

@pesada
class SinModelo(unittest.TestCase):
    def test_pieza_sin_modelo_validado_devuelve_no_validado(self):
        r = st.evaluate_structure('bloque_vecino')
        self.assertEqual(r['estado'], 'ok'); self.assertEqual(r['status'], 'no_validado')
        self.assertIsNone(r['margen_min']); self.assertIsNone(r['flecha_mm']); self.assertEqual(r['casos'], {})
        self.assertIn('motivo', r); self.assertIsInstance(r['masa_g'], float)     # la masa sí es medida
    def test_geometria_arbitraria_no_validado(self):
        self.assertEqual(st.evaluate_structure(fx.cubo(10))['status'], 'no_validado')
    def test_nunca_inventa_un_margen(self):
        for p in ('bloque_vecino', 'linea_base:placa_soporte', 'zzz_inexistente'):
            if p.startswith('zzz'): continue
            r = st.evaluate_structure(p)
            if r['status'] == 'no_validado': self.assertIsNone(r['margen_min'])
    def test_error_pieza(self): self.assertEqual(st.evaluate_structure('zzz')['codigo'], 'pieza_no_encontrada')

@pesada
class ConModeloRegistrado(unittest.TestCase):
    def setUp(self):
        st.registrar_modelo('viga_test', st.modelo_voladizo_x(P=10.0), valid_for=['voladizo empotrado en x mín, carga en x máx'], casos=['punta'])
    def tearDown(self): st.MODELOS.pop('viga_test', None)
    def test_flecha_contra_analitica_con_fidelity(self):
        ruta = barra()
        ref = bm.viga_referencia(40, 5, 5, bm.E_PETG, bm.NU_PETG, 10.0)['timoshenko_mm']
        r = st.evaluate_structure(ruta, fidelity=0.625)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['fidelity']['paso_mm'], 0.625)
        self.assertGreater(r['fidelity']['elementos'], 1000)
        self.assertAlmostEqual(r['flecha_mm'], ref, delta=ref * bm.TOLERANCIAS['viga_fino']['error_rel'])
        self.assertTrue(r['valid_for'])
    def test_fidelity_gruesa_avisa(self):
        r = st.evaluate_structure(barra(), fidelity=2.5)
        self.assertTrue(any('paso' in a for a in r['advertencias']))
    def test_la_flecha_converge_con_el_paso(self):
        ref = bm.viga_referencia(40, 5, 5, bm.E_PETG, bm.NU_PETG, 10.0)['timoshenko_mm']
        e = [abs(st.evaluate_structure(barra(), fidelity=p)['flecha_mm'] - ref) for p in (2.5, 1.25, 0.625)]
        self.assertTrue(e[0] > e[1] > e[2])
    def test_caso_desconocido(self):
        r = st.evaluate_structure(barra(), cases=['no_existe'])
        self.assertEqual((r['estado'], r['codigo']), ('error', 'caso_desconocido'))
    def test_fidelity_invalida(self):
        self.assertEqual(st.evaluate_structure(barra(), fidelity=-1)['codigo'], 'parametro_invalido')

@pesada
class PlacaDeclarada(unittest.TestCase):
    def test_modelo_declarado_en_agentcad_toml(self):
        r = st.evaluate_structure('placa_soporte', fidelity=2.0)
        self.assertEqual(r['status'], 'ok')
        self.assertIsInstance(r['margen_min'], float); self.assertGreater(r['margen_min'], 0)
        self.assertIsInstance(r['flecha_mm'], float)
        self.assertEqual(r['fidelity']['paso_mm'], 2.0)
        self.assertTrue(r['valid_for']); self.assertTrue(r['no_valido_para'])
        self.assertEqual(r['nivel_validacion'], 'digital')
        self.assertIn('carga', r['casos'])
        self.assertTrue(any('paso' in a for a in r['advertencias']))      # 2 mm no resuelve el paso recomendado de 0,8 mm

@pesada
class F4PasoRecomendadoPorDefecto(unittest.TestCase):
    """F4/F5: un modelo registrado por código SIN recomendado_mm también informa y avisa del paso grueso (ahora con la resolución verificada)."""
    def setUp(self): st.registrar_modelo('viga_sin_rec', st.modelo_voladizo_x(P=10.0), valid_for=['voladizo'], casos=['punta'])
    def tearDown(self): st.MODELOS.pop('viga_sin_rec', None)
    def test_informa_el_recomendado_y_su_origen(self):
        r = st.evaluate_structure(barra('viga_sin_rec.stl'), fidelity=0.625)
        self.assertAlmostEqual(r['fidelity']['recomendado_mm'], 5 / 6, places=3)      # canto menor 5 mm / 6 elementos (n para <=5 % verificado)
        self.assertEqual(r['fidelity']['origen_recomendado'], 'verificacion_fem')
        self.assertFalse(any('recomendado' in a for a in r['advertencias']))
    def test_avisa_con_paso_grueso(self):
        r = st.evaluate_structure(barra('viga_sin_rec.stl'), fidelity=2.5)
        self.assertTrue(any('recomendado 0.8333' in a for a in r['advertencias']), r['advertencias'])
    def test_el_modelo_manda_si_declara_recomendado(self):
        st.MODELOS['viga_sin_rec']['recomendado_mm'] = 0.5
        r = st.evaluate_structure(barra('viga_sin_rec.stl'), fidelity=0.625)
        self.assertEqual(r['fidelity']['recomendado_mm'], 0.5); self.assertEqual(r['fidelity']['origen_recomendado'], 'modelo')
        self.assertTrue(any('recomendado 0.5' in a for a in r['advertencias']))

@pesada
class F5ToleranciaMedida(unittest.TestCase):
    """F5: evaluate_structure advierte con el error MEDIDO en la suite de verificación (validacion/), no con una cifra fija."""
    def tearDown(self): st.MODELOS.pop('viga_tol', None)
    def reg(self, **kw): st.registrar_modelo('viga_tol', st.modelo_voladizo_x(P=10.0), valid_for=['voladizo'], casos=['punta'], **kw)
    def test_paso_grueso_informa_el_error_medido_y_avisa(self):
        self.reg(); r = st.evaluate_structure(barra('viga_tol.stl'), fidelity=2.5)
        em = r['fidelity']['error_medido']
        self.assertEqual(em['elementos_por_canto'], 2.0); self.assertLess(em['error_rel'], -0.15)      # -17,2 % del voladizo a 2 elementos por canto
        self.assertIn('verificado numéricamente', em['etiqueta']); self.assertIn('no validado físicamente', em['etiqueta'])
        self.assertTrue(any('error medido' in a and 'solución analítica' in a for a in r['advertencias']), r['advertencias'])
    def test_paso_fino_no_avisa_del_error(self):
        self.reg(); r = st.evaluate_structure(barra('viga_tol.stl'), fidelity=0.3125 * 2)
        self.assertFalse(any('error medido' in a for a in r['advertencias']), r['advertencias'])
        self.assertLess(abs(r['fidelity']['error_medido']['error_rel']), 0.05)
    def test_tipo_declarado_usa_su_curva(self):
        self.reg(tipo_validacion='traccion'); r = st.evaluate_structure(barra('viga_tol.stl'), fidelity=2.5)
        self.assertEqual(r['fidelity']['error_medido']['tipo'], 'traccion'); self.assertGreater(r['fidelity']['error_medido']['error_rel'], -0.05)
    def test_tipo_desconocido_falla(self):
        with self.assertRaises(ValueError): self.reg(tipo_validacion='inexistente')
    def test_fuera_de_rango_se_marca(self):
        self.assertTrue(st.error_medido('viga_flexion', 1.0)['fuera_de_rango'])
        self.assertTrue(st.error_medido('viga_flexion', 100.0)['fuera_de_rango'])
        self.assertFalse(st.error_medido('viga_flexion', 4.0)['fuera_de_rango'])
    def test_sin_tipo_es_la_envolvente_del_peor_caso(self):
        e = st.error_medido(None, 2.0); self.assertLessEqual(e['error_rel'], st.error_medido('torsion', 2.0)['error_rel'] + 1e-12)
if __name__ == '__main__': unittest.main()
