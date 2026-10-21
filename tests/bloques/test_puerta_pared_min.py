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

if __name__ == '__main__': unittest.main()
