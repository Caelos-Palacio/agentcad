"""Prueba de contrato del bloque puerta_interferencia + comportamiento en modo simulado (volumen conocido, flag a 0)."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'puerta_interferencia'

    def _proyecto(self, fallos=None):
        self.p = contrato.Proyecto(fallos=fallos); self.addCleanup(self.p.limpiar)

    def test_interferencia_activa_falla(self):
        self._proyecto({'soporte': {'interferencia_mm3': 5.0}})
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['estado'], 'interfiere'); self.assertEqual(s['volumen_mm3'], 5.0)

    def test_volumen_conocido_lo_permite(self):
        self._proyecto({'soporte': {'interferencia_mm3': 5.0}})
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte', conocido_mm3=5.0), self.p.ctx)
        self.assertTrue(s['ok'])

    def test_sin_fallo_no_interfiere(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['estado'], 'sin_interferencia')

    def test_con_flag_a_cero_mide_la_base(self):
        self._proyecto({'soporte': {'interferencia_mm3': 5.0}})          # sin aplicar flags: base sin interferencia
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['volumen_mm3'], 0.0)

if __name__ == '__main__': unittest.main()
