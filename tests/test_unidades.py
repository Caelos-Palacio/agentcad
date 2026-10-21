"""Unidades tipadas (mm, g, MPa...) en los esquemas de bloques y parámetros de pipelines; comprobación de compatibilidad en el dry-run."""
import unittest
from agentcad import bloques, pipeline as pl, unidades

class Tabla(unittest.TestCase):
    def test_familias(self):
        self.assertEqual(unidades.familia('mm'), 'longitud'); self.assertEqual(unidades.familia('MPa'), 'presion'); self.assertEqual(unidades.familia('g'), 'masa')
        self.assertIsNone(unidades.familia('parsec'))
    def test_iguales_o_sin_declarar_son_compatibles(self):
        self.assertIsNone(unidades.comprobar('mm', 'mm')); self.assertIsNone(unidades.comprobar(None, 'mm')); self.assertIsNone(unidades.comprobar('mm', None))
    def test_magnitud_distinta_es_error(self):
        m = unidades.comprobar('mm', 'g'); self.assertIn('longitud', m); self.assertIn('masa', m)
    def test_misma_magnitud_otra_unidad_exige_conversion_explicita(self):
        m = unidades.comprobar('m', 'mm'); self.assertIn('convierte', m); self.assertIn('1000', m)
        self.assertIn('0.001', unidades.comprobar('g', 'kg').replace(',', '.'))
    def test_factor(self):
        self.assertEqual(unidades.factor('m', 'mm'), 1000.0); self.assertAlmostEqual(unidades.factor('kg', 'g'), 1000.0); self.assertEqual(unidades.factor('GPa', 'MPa'), 1000.0)
        with self.assertRaises(ValueError): unidades.factor('mm', 'g')
    def test_convertir(self):
        self.assertEqual(unidades.convertir(2.0, 'm', 'mm'), 2000.0)

class Manifiestos(unittest.TestCase):
    def test_unidad_desconocida_invalida_el_manifiesto(self):
        m = dict(bloques.cargar()['puerta_masa'].MANIFIESTO); m['entradas'] = {'x': {'type': 'number', 'unidad': 'parsec'}}
        self.assertTrue(any('unidad' in e for e in bloques.validar_manifiesto(m)))
    def test_unidad_en_campo_no_numerico_invalida(self):
        m = dict(bloques.cargar()['puerta_masa'].MANIFIESTO); m['entradas'] = {'x': {'type': 'string', 'unidad': 'mm'}}
        self.assertTrue(any('unidad' in e for e in bloques.validar_manifiesto(m)))
    def test_bloques_de_agentcad_declaran_unidades(self):
        B = bloques.cargar()
        self.assertEqual(B['puerta_pared_min'].MANIFIESTO['entradas']['umbral_mm']['unidad'], 'mm')
        self.assertEqual(B['puerta_pared_min'].MANIFIESTO['salidas']['pared_min_mm']['unidad'], 'mm')
        self.assertEqual(B['puerta_masa'].MANIFIESTO['entradas']['base_g']['unidad'], 'g')
        self.assertEqual(B['puerta_interferencia'].MANIFIESTO['salidas']['volumen_mm3']['unidad'], 'mm3')
        self.assertEqual(B['build'].MANIFIESTO['salidas']['masa_g']['unidad'], 'g')
    def test_catalogo_muestra_unidades(self): self.assertIn('[mm]', bloques.catalogo())

def _pipe(parametros, pasos): return dict(esquema='agentcad.pipeline/1', nombre='unid', descripcion='x', parametros=parametros, pasos=pasos)

class DryRun(unittest.TestCase):
    def errs(self, parametros, pasos, params=None): return pl.validar(_pipe(parametros, pasos), params)
    PASO_MASA = {'id': 'm', 'bloque': 'puerta_masa', 'entradas': {'base_g': '$p'}}
    def test_parametro_con_unidad_compatible(self):
        self.assertEqual(self.errs({'p': {'type': 'number', 'unidad': 'g'}}, [self.PASO_MASA]), [])
    def test_parametro_con_magnitud_distinta_falla(self):
        e = ' '.join(self.errs({'p': {'type': 'number', 'unidad': 'mm'}}, [self.PASO_MASA])); self.assertIn('base_g', e); self.assertIn('longitud', e)
    def test_parametro_con_otra_unidad_de_la_misma_magnitud_falla(self):
        e = ' '.join(self.errs({'p': {'type': 'number', 'unidad': 'kg'}}, [self.PASO_MASA])); self.assertIn('convierte', e)
    def test_salida_a_entrada_con_magnitud_distinta_falla(self):
        pasos = [{'id': 'pared', 'bloque': 'puerta_pared_min', 'entradas': {'pieza': 'x'}}, {'id': 'm', 'bloque': 'puerta_masa', 'entradas': {'base_g': '$pared.pared_min_mm'}}]
        e = ' '.join(self.errs({}, pasos)); self.assertIn('pared_min_mm', e); self.assertIn('masa', e)
    def test_salida_a_entrada_con_misma_unidad_pasa(self):
        pasos = [{'id': 'c', 'bloque': 'build'}, {'id': 'm', 'bloque': 'puerta_masa', 'entradas': {'base_g': '$c.masa_g'}}]
        self.assertEqual(self.errs({}, pasos), [])
    def test_sin_unidad_declarada_no_se_comprueba(self):
        self.assertEqual(self.errs({'p': {'type': 'number'}}, [self.PASO_MASA]), [])
    def test_pipelines_incluidos_son_validos_con_unidades(self):
        self.assertEqual(pl.validar(pl.cargar_pipeline('integrar_variante'), dict(etiqueta='v2', etiqueta_anterior='v1', config='c.json', base_g=600.0)), [])
        p = pl.cargar_pipeline('integrar_variante'); self.assertEqual(p['parametros']['base_g']['unidad'], 'g'); self.assertEqual(p['parametros']['pared_min_mm']['unidad'], 'mm')
    def test_unidad_de_parametro_desconocida(self):
        self.assertTrue(any('unidad' in e for e in self.errs({'p': {'type': 'number', 'unidad': 'parsec'}}, [self.PASO_MASA])))
if __name__ == '__main__': unittest.main()
