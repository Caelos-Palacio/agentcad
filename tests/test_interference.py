import unittest, numpy as np, trimesh, manifold3d as M
from tests import fixtures as fx
from agentcad import interference, geom

class Puro(unittest.TestCase):
    def test_solape_exacto(self):
        a = M.Manifold.cube([10, 10, 10]); b = M.Manifold.cube([10, 10, 10]).translate([8, 0, 0])
        self.assertAlmostEqual(interference.volumen_interferencia(a, b), 200.0, delta=1e-3)
    def test_tangentes_y_separados(self):
        a = M.Manifold.cube([10, 10, 10])
        self.assertAlmostEqual(interference.volumen_interferencia(a, a.translate([10, 0, 0])), 0.0, delta=1e-6)
        self.assertEqual(interference.volumen_interferencia(a, a.translate([50, 0, 0])), 0.0)

class Herramienta(unittest.TestCase):
    def test_placa_del_ejemplo_sin_interferencia(self):
        r = interference.check_interference('placa_soporte')
        self.assertEqual(r['estado'], 'ok'); self.assertEqual(r['veredicto'], 'sin_interferencia')
        self.assertLessEqual(r['volumen_total_mm3'], r['umbral_mm3'])
    def test_pose_desconocida(self):
        r = interference.check_interference('placa_soporte', pose='no_existe')
        self.assertEqual((r['estado'], r['codigo']), ('error', 'pose_desconocida'))
    def test_pose_dict_y_nombre(self):
        self.assertEqual(interference.check_interference('placa_soporte', pose={'giro': 10})['estado'], 'ok')
        self.assertEqual(interference.check_interference('placa_soporte', pose='girado')['pose'], 'girado')
    def test_pose_angulo_no_numerico(self):
        self.assertEqual(interference.check_interference('placa_soporte', pose={'giro': 'x'})['codigo'], 'pose_invalida')
    def test_taco_que_invade_la_base(self):
        m = geom.cargar(geom.resolver('placa_soporte')['ruta'])
        taco = trimesh.creation.box([10, 10, 6]); taco.apply_translation([66, 20, 3])      # invade el bloque vecino (x de 62 a 82)
        mf = geom.a_manifold(m) + geom.a_manifold(taco)
        d = fx._TMP / 'placa_mod'; d.mkdir(exist_ok=True)
        ruta = d / 'placa_soporte.stl'; geom.de_manifold(mf).export(str(ruta))
        r = interference.check_interference(str(ruta))
        self.assertEqual(r['veredicto'], 'interfiere')
        self.assertTrue(any(i['con'] == 'vecino' and i['volumen_mm3'] > 1 for i in r['interferencias']))
    def test_pose_girada_interfiere_con_el_vecino(self):
        r = interference.check_interference('placa_soporte', pose='girado')
        self.assertEqual(r['veredicto'], 'interfiere'); self.assertEqual(r['interferencias'][0]['con'], 'vecino'); self.assertGreater(r['volumen_total_mm3'], 1)
    def test_pieza_fuera_del_ensamblaje(self):
        r = interference.check_interference(fx.cubo(10))
        self.assertEqual(r['estado'], 'ok'); self.assertEqual(r['veredicto'], 'no_evaluable')
if __name__ == '__main__': unittest.main()
