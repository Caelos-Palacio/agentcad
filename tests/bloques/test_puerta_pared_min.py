"""Prueba de contrato del bloque puerta_pared_min + comportamiento en modo simulado (fallo provocado, umbral, flag a 0)."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'puerta_pared_min'

    def _proyecto(self, fallos=None):
        self.p = contrato.Proyecto(fallos=fallos); self.addCleanup(self.p.limpiar)

    def test_variante_activa_con_pared_fina_falla(self):
        self._proyecto({'soporte': {'pared_min_mm': 0.9}})
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['veredicto'], 'no_cumple'); self.assertEqual(s['pared_min_mm'], 0.9)

    def test_variante_activa_sin_fallo_cumple(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['veredicto'], 'cumple')

    def test_umbral_cambia_el_veredicto(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)     # pared activa 1,5 mm
        self.assertFalse(pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte', umbral_mm=1.6), self.p.ctx)['ok'])
        self.assertTrue(pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte', umbral_mm=1.4), self.p.ctx)['ok'])

    def test_con_flag_a_cero_mide_la_base(self):
        self._proyecto({'soporte': {'pared_min_mm': 0.9}})                # sin aplicar flags: se mide la base (1,6 mm)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['pared_min_mm'], 1.6)

    def test_defecto_preexistente_que_no_empeora_pasa_pero_se_marca(self):
        from agentcad.bloques import puerta_pared_min as m
        r = m._ver(dict(umbral_mm=1.2), 0.16, 0.0, 0.16); self.assertTrue(r['ok']); self.assertTrue(r['preexistente']); self.assertEqual(r['veredicto'], 'preexistente_no_peor')

    def test_defecto_que_empeora_la_base_falla(self):
        from agentcad.bloques import puerta_pared_min as m
        r = m._ver(dict(umbral_mm=1.2), 0.30, 0.0, 0.87); self.assertFalse(r['ok']); self.assertFalse(r['preexistente'])

    def test_base_que_cumple_exige_el_umbral(self):
        from agentcad.bloques import puerta_pared_min as m
        self.assertFalse(m._ver(dict(umbral_mm=1.2), 1.0, 0.0, 1.6)['ok'])

    def test_racha_vertical_de_un_voxel_no_cuenta_pero_se_informa(self):
        from agentcad.bloques import puerta_pared_min as m
        r = dict(pared_min_mm=0.3, fidelidad=dict(espesor_vertical_min_mm=0.3, paso_mm=0.3), puntos_finos=[dict(tipo='en_plano', espesor_mm=0.87)])
        self.assertEqual(m.efectiva(r), (0.87, True))
        r['fidelidad']['espesor_vertical_min_mm'] = 0.9; self.assertEqual(m.efectiva(r), (0.3, False))     # 3 vóxeles: resuelto y cuenta

    def test_sin_puntos_en_plano_la_pared_efectiva_cumple(self):
        from agentcad.bloques import puerta_pared_min as m
        r = dict(pared_min_mm=0.3, fidelidad=dict(espesor_vertical_min_mm=0.3, paso_mm=0.3), puntos_finos=[])
        self.assertGreaterEqual(m.efectiva(r)[0], 1.2)

    def test_ejecucion_real_sobre_el_ejemplo_compara_con_la_linea_base(self):
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='placa_soporte', umbral_mm=1.2), dict(raiz=None, simulado=False))
        self.assertTrue(s['ok']); self.assertEqual(s['veredicto'], 'cumple'); self.assertFalse(s['preexistente'])
        self.assertGreater(s['pared_min_mm'], 1.2)

if __name__ == '__main__': unittest.main()
