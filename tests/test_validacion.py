"""F5: la suite de verificación numérica (validacion/) y la tabla de tolerancias medidas que lee evaluate_structure.
Etiqueta: verificado numéricamente contra solución analítica (no validado físicamente con ensayos)."""
import json, math, unittest
from pathlib import Path
from validacion import casos as C
from agentcad import structure as st
from tests._marcas import pesada

TABLA = Path(st.__file__).resolve().parent / 'validacion_fem.json'

class Referencias(unittest.TestCase):
    def test_j_saint_venant_cuadrado(self): self.assertAlmostEqual(C.j_saint_venant(1, 1), 0.140577, places=5)
    def test_j_saint_venant_rectangulo_2_a_1(self): self.assertAlmostEqual(C.j_saint_venant(2, 1), 0.4573, delta=0.001)
    def test_peterson_limites(self):
        self.assertAlmostEqual(C.kt_peterson_neto(0.0), 3.0)
        self.assertAlmostEqual(C.kt_bruto_peterson(0.2), (3 - 0.628 + 0.14668 - 0.012216) / 0.8, places=3)
    def test_orden_observado_sintetico(self):
        # v(n) = 1 - 1/n^2 converge con orden 2 a 1
        o = C.orden_observado([2, 4, 8], [1 - 1 / 4, 1 - 1 / 16, 1 - 1 / 64], ref=1.0)
        self.assertAlmostEqual(o[0]['orden_richardson'], 2.0, places=6); self.assertAlmostEqual(o[0]['extrapolado'], 1.0, places=6)
    def test_orden_no_asintotico_se_descarta(self):
        self.assertEqual(C.orden_observado([4, 8, 16], [2.1, 2.4, 2.9]), [])

@pesada
class CasosRapidos(unittest.TestCase):
    def test_traccion_ideal_es_exacta(self):
        for x in C.traccion(ns=(1, 2))['ideal']: self.assertLess(abs(x['error_rel']), 1e-9); self.assertLess(abs(x['error_tension_rel']), 1e-9)
    def test_traccion_empotrada_converge_por_exceso_de_rigidez(self):
        e = [x['error_rel'] for x in C.traccion(ns=(1, 2))['empotrada']]
        self.assertTrue(all(v < 0 for v in e)); self.assertGreater(abs(e[0]), abs(e[1]))
    def test_voladizo_mas_rigido_que_timoshenko_y_converge(self):
        r = C.voladizo(ns=(2, 4)); self.assertLess(r[0]['error_rel'], r[1]['error_rel'] - 0.05); self.assertLess(r[1]['error_rel'], 0)
    def test_flexion_3_puntos_converge(self):
        r = C.flexion_3_puntos(ns=(2, 4)); self.assertLess(abs(r[1]['error_rel']), abs(r[0]['error_rel'])); self.assertLess(abs(r[1]['error_tension_rel']), 0.08)
    def test_torsion_converge_a_saint_venant(self):
        r = C.torsion(ns=(2, 4)); self.assertLess(abs(r[1]['error_rel']), 0.06); self.assertLess(r[1]['error_rel'], 0)
    def test_placa_agujero_subestima_el_pico_y_mejora(self):
        r = C.placa_agujero(nds=(4, 8)); self.assertLess(r[0]['error_rel'], r[1]['error_rel']); self.assertLess(r[1]['error_rel'], 0)
        self.assertGreater(r[1]['fem'], 2.0)

class TablaPublicada(unittest.TestCase):
    def setUp(self): self.t = json.loads(TABLA.read_text(encoding='utf-8'))
    def test_etiqueta_y_tipos(self):
        self.assertIn('verificado numéricamente', self.t['etiqueta']); self.assertIn('NO validado físicamente', self.t['etiqueta'])
        for k in ('viga_flexion', 'traccion', 'torsion', 'placa_flexion', 'placa_agujero'): self.assertIn(k, self.t['tipos'])
    def test_cada_curva_es_creciente_en_n_y_acota_el_error(self):
        for tipo, d in self.t['tipos'].items():
            ns = [x['n'] for x in d['curva']]; self.assertEqual(ns, sorted(ns))
            if d['n_para_5pct']: self.assertTrue(all(abs(x['error_rel']) <= 0.05 for x in d['curva'] if x['n'] >= d['n_para_5pct']), tipo)
    @pesada
    def test_la_tabla_coincide_con_una_nueva_medida(self):
        r = C.voladizo(ns=(2, 4)); cv = {x['n']: x['error_rel'] for x in self.t['tipos']['viga_flexion']['curva']}
        self.assertAlmostEqual(r[0]['error_rel'], -0.17199, places=3)
        self.assertLessEqual(abs(cv[2]), 0.1721)      # el peor caso de la curva incluye voladizo (-17,2 %)

if __name__ == '__main__': unittest.main()
