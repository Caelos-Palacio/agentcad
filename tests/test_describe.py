"""R1 «alucinación geométrica»: describe_part solo devuelve lo medido, contra geometría de verdad conocida."""
import math, unittest
from tests import fixtures as fx
from agentcad import describe

class VerdadConocida(unittest.TestCase):
    def test_cubo(self):
        r = describe.describe_part(fx.cubo(10))
        self.assertEqual(r['estado'], 'ok')
        self.assertAlmostEqual(r['volumen_mm3'], 1000.0, delta=0.01)
        self.assertEqual(r['componentes'], 1)
        self.assertEqual(len(r['agujeros_cilindricos']), 0)
        self.assertEqual(r['bbox_mm']['tamano'], [10.0, 10.0, 10.0])
        self.assertTrue(r['malla_cerrada'])

    def test_masa_cubo_perfil_print(self):
        # perfil por defecto (3 perímetros, 15 %): cáscara = min(V, A*3*0.45)=min(1000, 600*1.35=810) ; resto al 15 %
        r = describe.describe_part(fx.cubo(10))
        esperado = 1.27e-3 * (810 + (1000 - 810) * 0.15)
        self.assertAlmostEqual(r['masa_estimada_g'], esperado, delta=0.01)
        self.assertEqual(r['perfil_impresion']['origen'], 'por_defecto')

    def test_masa_perfil_override(self):
        r = describe.describe_part(fx.cubo(10), perfil=dict(walls=1, infill=100))
        self.assertAlmostEqual(r['masa_estimada_g'], 1.27, delta=0.001)   # sólido: 1000 mm3 * 1.27e-3

    def test_dos_componentes(self):
        self.assertEqual(describe.describe_part(fx.dos_cubos())['componentes'], 2)

    def test_agujero_cilindrico_exacto(self):
        r = describe.describe_part(fx.bloque_con_agujero(30, 30, 10, r=3.0, segs=64))
        self.assertAlmostEqual(r['volumen_mm3'], 30 * 30 * 10 - fx.vol_prisma_regular(3.0, 64, 10), delta=0.01)
        ag = r['agujeros_cilindricos']
        self.assertEqual(len(ag), 1)
        self.assertAlmostEqual(ag[0]['radio_mm'], 3.0, delta=0.01)
        self.assertEqual(ag[0]['eje'], 'z')
        self.assertAlmostEqual(ag[0]['centro_mm'][0], 15.0, delta=0.01)
        self.assertAlmostEqual(ag[0]['centro_mm'][1], 15.0, delta=0.01)
        self.assertAlmostEqual(ag[0]['profundidad_mm'], 10.0, delta=0.01)
        self.assertTrue(ag[0]['recorre_bbox'])

    def test_ventanas_hexagonales_no_son_agujeros_cilindricos(self):
        ruta, n, vol = fx.placa_ventanas()
        r = describe.describe_part(ruta)
        self.assertGreater(n, 10)
        self.assertAlmostEqual(r['volumen_mm3'], vol, delta=0.05)
        self.assertEqual(len(r['agujeros_cilindricos']), 0)

    def test_placa_con_agujeros_y_pilares(self):
        r = describe.describe_part(fx.placa_con_pilares())
        # 4 agujeros pasantes de r 1.6 que atraviesan placa y pilar (un solo cilindro por esquina)
        self.assertEqual(len(r['agujeros_cilindricos']), 4)
        for a in r['agujeros_cilindricos']: self.assertAlmostEqual(a['radio_mm'], 1.6, delta=0.01)
        # los pilares exteriores se informan aparte
        self.assertEqual(len(r['salientes_cilindricos']), 4)

    def test_pieza_inexistente_error_estructurado(self):
        r = describe.describe_part('no_existe_xyz')
        self.assertEqual(r['estado'], 'error')
        self.assertEqual(r['codigo'], 'pieza_no_encontrada')

    def test_todo_numero_es_medido_y_serializable(self):
        import json
        json.dumps(describe.describe_part(fx.cubo(10)))

class PiezaReal(unittest.TestCase):
    def test_placa_del_ejemplo(self):
        r = describe.describe_part('placa_soporte')
        self.assertEqual(r['estado'], 'ok')
        self.assertEqual(r['bbox_mm']['tamano'], [60.0, 40.0, 9.0])
        self.assertEqual(r['componentes'], 1)
        self.assertGreater(len(r['agujeros_cilindricos']), 3)
        self.assertEqual(r['perfil_impresion']['origen'], 'agentcad.toml')
        vecinas = {v['id'] for v in r['vecinas']}
        self.assertEqual(vecinas, {'vecino'})       # el bloque de referencia del ensamblaje del ejemplo
        for v in r['vecinas']: self.assertGreaterEqual(v['distancia_min_mm'], 0.0)

    def test_zonas_protegidas_del_archivo_configurado(self):
        z = describe.describe_part('placa_soporte')['zonas_protegidas']
        self.assertEqual(z['fuente'], 'zonas.json'); self.assertEqual(z['total'], 2)
        self.assertFalse(describe.describe_part('bloque_vecino')['zonas_protegidas']['disponible'])

    def test_baseline_prefijo(self):
        a = describe.describe_part('placa_soporte'); b = describe.describe_part('linea_base:placa_soporte')
        self.assertGreater(b['volumen_mm3'], a['volumen_mm3'])      # la línea base no tiene ventanas

if __name__ == '__main__':
    unittest.main()
