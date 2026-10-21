"""agentcad.calibracion: ajuste de una razón y = r x por error relativo y validación cruzada por grupos (datos SINTÉTICOS; el uso real está en validacion/laminador)."""
import unittest
from agentcad import calibracion as cal

class Razon(unittest.TestCase):
    def test_recupera_la_razon_exacta(self):
        self.assertAlmostEqual(cal.ajustar_razon([10, 20, 40], [8, 16, 32]), 0.8, places=12)
    def test_minimiza_el_error_relativo_no_el_absoluto(self):
        # razones y/x de 1,1 y 0,9: el mínimo de sum(((r x - y)/y)^2) es r = sum(x/y)/sum((x/y)^2) = 0,98019 (el absoluto, que pesaría el punto grande, daría ~1,098)
        self.assertAlmostEqual(cal.ajustar_razon([1000.0, 10.0], [1100.0, 9.0]), 0.980198, places=5)
    def test_rechaza_datos_invalidos(self):
        for x, y in (([], []), ([1, 2], [1]), ([0, 0], [1, 1]), ([1, 2], [0, 1]), ([1, 2], [-1, 1])):
            with self.assertRaises(ValueError): cal.ajustar_razon(x, y)

class ValidacionCruzada(unittest.TestCase):
    def test_datos_exactos_error_cero(self):
        r = cal.validacion_cruzada([1, 2, 3, 4], [2, 4, 6, 8], ['a', 'a', 'b', 'b']); self.assertAlmostEqual(r['mape'], 0.0, places=12); self.assertEqual(r['n_grupos'], 2)
    def test_error_relativo_conocido(self):
        # grupo a: razón 1,0; grupo b: razón 2,0 -> al dejar fuera b se predice con r=1: error relativo (1-2)/2 = -0,5 ; al dejar fuera a, r=2: (2-1)/1 = +1
        r = cal.validacion_cruzada([1, 1], [1, 2], ['a', 'b']); self.assertEqual(sorted(round(e, 6) for e in r['errores_rel']), [-0.5, 1.0]); self.assertAlmostEqual(r['max_abs'], 1.0)
    def test_un_solo_grupo_no_se_puede_validar(self):
        with self.assertRaises(ValueError): cal.validacion_cruzada([1, 2], [1, 2], ['a', 'a'])

class Calibrar(unittest.TestCase):
    FILAS = [dict(p=1, x=100, y=80), dict(p=2, x=50, y=41), dict(p=3, x=200, y=158), dict(p=4, x=30, y=25)]
    def test_resumen_con_aviso_de_pocos_grupos(self):
        r = cal.calibrar(self.FILAS, 'x', 'y', 'p'); self.assertEqual(r['n'], 4); self.assertEqual(r['n_grupos'], 4); self.assertAlmostEqual(r['razon'], 0.8, delta=0.03)
        self.assertFalse(r['fiable']); self.assertIn('solo 4 grupos', r['nota']); self.assertLess(r['cv']['mape'], 0.1)
    def test_muchos_grupos_se_consideran_fiables(self):
        filas = [dict(p=i, x=10 + i, y=0.8 * (10 + i)) for i in range(12)]; self.assertTrue(cal.calibrar(filas, 'x', 'y', 'p')['fiable'])
    def test_estimar_aplica_razon_y_error_declarado(self):
        e = cal.estimar(100.0, razon=0.8, error_rel=0.12); self.assertAlmostEqual(e['valor'], 80.0); self.assertAlmostEqual(e['min'], 80 * 0.88); self.assertAlmostEqual(e['max'], 80 * 1.12)

if __name__ == '__main__': unittest.main()
