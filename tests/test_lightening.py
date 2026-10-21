import json, random, unittest, shutil
from pathlib import Path
from tests import fixtures as fx
from agentcad import lightening as lg, config, geom, describe
from tests._marcas import pesada

@pesada
class Placa(unittest.TestCase):
    def test_volumen_retirado_exacto(self):
        ruta = fx.placa_con_pilares(nombre='placa_a.stl')
        antes = describe.describe_part(ruta)
        r = lg.apply_hex_lightening(ruta, d=6.0, rib=2.0, keep=2.0, t=3.0, fidelity_estructura=2.0)
        self.assertEqual(r['estado'], 'ok'); self.assertGreater(r['n_ventanas'], 3)
        despues = describe.describe_part('copia:' + r['copia']['id'])
        quitado = antes['volumen_mm3'] - despues['volumen_mm3']
        self.assertAlmostEqual(quitado, r['n_ventanas'] * fx.area_hex(6.0) * 3.0, delta=0.5)
        self.assertEqual(len(despues['agujeros_cilindricos']), len(antes['agujeros_cilindricos']))   # agujeros intactos
        self.assertEqual(despues['componentes'], 1)
        self.assertAlmostEqual(r['masa_antes_g'] - r['masa_despues_g'], r['delta_masa_g'], delta=1e-3)
        self.assertGreater(r['delta_masa_g'], 0)
    def test_devuelve_comprobaciones_2_3_4_sobre_la_copia(self):
        r = lg.apply_hex_lightening(fx.placa_con_pilares(nombre='placa_b.stl'), d=6.0, rib=2.0, keep=2.0, t=3.0, fidelity_estructura=2.0)
        self.assertEqual(r['interferencia']['estado'], 'ok')
        self.assertIn('veredicto', r['fabricabilidad']); self.assertIn('status', r['estructura'])
        self.assertTrue(r['copia']['ruta'].endswith('.stl')); self.assertEqual(r['nivel_validacion'], 'digital')
    def test_original_no_se_modifica(self):
        ruta = fx.placa_con_pilares(nombre='placa_c.stl'); h = geom.sha256_fichero(ruta)
        lg.apply_hex_lightening(ruta, d=6.0, rib=2.0, keep=2.0, t=3.0, fidelity_estructura=2.0)
        self.assertEqual(h, geom.sha256_fichero(ruta))
    def test_propiedad_la_masa_nunca_sube(self):
        rng = random.Random(20261020); ruta = fx.placa_con_pilares(nombre='placa_p.stl'); m0 = geom.masa_g(ruta, geom.perfil('placa_p'))
        for _ in range(12):
            d, rib, keep = rng.uniform(3, 12), rng.uniform(1.2, 4.0), rng.uniform(1.0, 4.0)
            r = lg.apply_hex_lightening(ruta, d=d, rib=rib, keep=keep, t=3.0, comprobar=False)
            self.assertEqual(r['estado'], 'ok', (d, rib, keep))
            self.assertLessEqual(r['masa_despues_g'], r['masa_antes_g'] + 1e-9, (d, rib, keep))
            self.assertLessEqual(r['volumen_despues_mm3'], m0['volumen_mm3'] + 1e-6)
    def test_sin_ventanas_deja_la_masa_igual(self):
        r = lg.apply_hex_lightening(fx.placa_con_pilares(nombre='placa_d.stl'), d=40.0, rib=2.0, keep=2.0, t=3.0, comprobar=False)
        self.assertEqual(r['n_ventanas'], 0); self.assertEqual(r['delta_masa_g'], 0.0)
    def test_parametros_invalidos(self):
        r = lg.apply_hex_lightening(fx.cubo(10), d=-1, rib=2, keep=2)
        self.assertEqual(r['codigo'], 'parametro_invalido')
        self.assertEqual(lg.apply_hex_lightening('zzz', d=6, rib=2, keep=2)['codigo'], 'pieza_no_encontrada')

@pesada
class Real(unittest.TestCase):
    def test_aligera_la_placa_de_la_linea_base_del_ejemplo(self):
        antes = describe.describe_part('linea_base:placa_soporte')
        r = lg.apply_hex_lightening('linea_base:placa_soporte', d=6, rib=1.6, keep=1.8, comprobar=False)
        self.assertEqual(r['estado'], 'ok'); self.assertGreater(r['n_ventanas'], 5)
        self.assertLess(r['masa_despues_g'], r['masa_antes_g'])
        despues = describe.describe_part('copia:' + r['copia']['id'])
        self.assertEqual(len(despues['agujeros_cilindricos']), len(antes['agujeros_cilindricos']))      # taladros intactos
        self.assertEqual(len(despues['salientes_cilindricos']), len(antes['salientes_cilindricos']))    # pilares intactos
    def test_el_tipo_anillo_ya_no_existe(self):
        self.assertEqual(lg.apply_hex_lightening('placa_soporte', d=6, rib=1.6, keep=1.8, tipo='anillo')['codigo'], 'parametro_invalido')
if __name__ == '__main__': unittest.main()
