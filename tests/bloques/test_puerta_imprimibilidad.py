"""Prueba de contrato del bloque puerta_imprimibilidad + comportamiento en modo simulado (nuevo fallo, flag a 0)."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'puerta_imprimibilidad'

    def _proyecto(self, fallos=None):
        self.p = contrato.Proyecto(fallos=fallos); self.addCleanup(self.p.limpiar)

    def test_nuevo_fallo_de_imprimibilidad_falla(self):
        self._proyecto({'soporte': {'imprimibilidad_nuevos_fallos': ['islas']}})
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['nuevos_fallos'], ['islas'])

    def test_sin_nuevos_fallos_cumple(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['nuevos_fallos'], [])

    def test_con_flag_a_cero_mide_la_base(self):
        self._proyecto({'soporte': {'imprimibilidad_nuevos_fallos': ['islas']}})   # sin flags: la base no tiene fallos
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pieza='soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['nuevos_fallos'], [])

if __name__ == '__main__': unittest.main()
