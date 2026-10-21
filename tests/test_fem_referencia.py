"""R2: el FEM voxel contra soluciones analíticas. Las tolerancias son las DECLARADAS en agentcad/benchmarks.py (TOLERANCIAS)."""
import json, unittest
from agentcad import benchmarks as bm
from tests._marcas import pesada

@pesada
class VigaVoladizo(unittest.TestCase):
    def test_referencia_analitica_conocida(self):
        # P L^3 /(3 E I) con L=40, b=h=5, E=1900, P=10: I=52.0833 -> 40^3*10/(3*1900*52.0833)=2.1558 mm (EB)
        ref = bm.viga_referencia(L=40, b=5, h=5, E=1900, nu=0.38, P=10)
        self.assertAlmostEqual(ref['euler_bernoulli_mm'], 2.1558, delta=1e-3)
        self.assertGreater(ref['timoshenko_mm'], ref['euler_bernoulli_mm'])
    def test_error_a_varias_resoluciones_y_convergencia(self):
        res = bm.viga_error_vs_paso(pasos=(2.5, 1.25, 0.625))
        errs = [abs(r['error_rel']) for r in res]
        print('\nviga voladizo, error relativo vs Timoshenko por paso:', {r['paso_mm']: round(r['error_rel'], 4) for r in res})
        self.assertGreater(errs[0], errs[1]); self.assertGreater(errs[1], errs[2])      # converge monotónicamente
        self.assertLessEqual(errs[2], bm.TOLERANCIAS['viga_fino']['error_rel'])
        self.assertLessEqual(errs[0], bm.TOLERANCIAS['viga_grueso']['error_rel'])
        self.assertLess(res[2]['flecha_fem_mm'], res[2]['referencia_mm'] * 1.01)         # el hexaedro lineal nunca es más flexible que la teoría
    def test_el_error_grueso_es_conocido_y_grande(self):
        # a 2 elementos por canto el bloqueo por cortante hace al modelo mucho más rígido: se documenta, no se oculta
        r = bm.viga_error_vs_paso(pasos=(2.5,))[0]
        self.assertLess(r['flecha_fem_mm'], r['referencia_mm'])

@pesada
class PlacaApoyada(unittest.TestCase):
    def test_placa_cuadrada_apoyada_carga_central(self):
        res = bm.placa_error_vs_paso(pasos=(2.5, 1.25))
        print('\nplaca apoyada, error relativo vs Kirchhoff+Mindlin por paso:', {r['paso_mm']: round(r['error_rel'], 4) for r in res})
        self.assertLess(abs(res[1]['error_rel']), abs(res[0]['error_rel']))
        self.assertLessEqual(abs(res[1]['error_rel']), bm.TOLERANCIAS['placa_fino']['error_rel'])

@pesada
class Informe(unittest.TestCase):
    def test_informe_validacion_serializable(self):
        inf = bm.informe_validacion()
        json.dumps(inf)
        self.assertIn('viga_voladizo', inf); self.assertIn('placa_apoyada', inf); self.assertIn('tolerancias', inf)
if __name__ == '__main__': unittest.main()
