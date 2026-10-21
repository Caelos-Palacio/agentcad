"""Prueba de contrato del bloque puerta_masa + comportamiento sobre la copia simulada (masa frente a la base)."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params, build

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'puerta_masa'

    def _masa_con_flags(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        return build.simular({}, self.p.ctx)['masa_g']

    def test_masa_inferior_a_la_base_cumple(self):
        self._masa_con_flags()
        s = pl.ejecutar_bloque(self.NOMBRE, dict(base_g=self.p.base_g), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['masa_g'], 549.0); self.assertEqual(s['delta_g'], -76.0)

    def test_falla_si_la_base_es_10g_menor(self):
        m = self._masa_con_flags()
        s = pl.ejecutar_bloque(self.NOMBRE, dict(base_g=m - 10), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['delta_g'], 10.0)

    def test_tolerancia_permite_el_exceso(self):
        m = self._masa_con_flags()
        s = pl.ejecutar_bloque(self.NOMBRE, dict(base_g=m - 10, tolerancia_g=10.0), self.p.ctx)
        self.assertTrue(s['ok'])

if __name__ == '__main__': unittest.main()
