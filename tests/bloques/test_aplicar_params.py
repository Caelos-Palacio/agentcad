"""Prueba de contrato del bloque aplicar_params + comportamiento sobre la copia simulada (flags, deshacer, idempotencia)."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params
from agentcad.bloques._base import flag_activo

FLAG = {'placa': 'placa_aligerada', 'soporte': 'soporte_rebaje', 'tapa': 'tapa_aligerada'}

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'aplicar_params'

    def _params(self): return self.p.leer('params.scad')

    def test_activa_los_tres_flags_y_los_lista(self):
        s = pl.ejecutar_bloque(self.NOMBRE, dict(config='config.json'), self.p.ctx)
        for f in FLAG.values(): self.assertTrue(flag_activo(self._params(), f), f)
        self.assertEqual(sorted(s['piezas_activas']), sorted(FLAG))

    def test_deshacer_solo_apaga_la_pieza_indicada(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = aplicar_params.deshacer(dict(config='config.json', pieza='soporte'), self.p.ctx)
        t = self._params()
        self.assertFalse(flag_activo(t, FLAG['soporte']))
        self.assertTrue(flag_activo(t, FLAG['placa'])); self.assertTrue(flag_activo(t, FLAG['tapa']))
        self.assertEqual(sorted(s['piezas_activas']), ['placa', 'tapa'])

    def test_pieza_desconocida_lanza_error(self):
        with self.assertRaises(KeyError):
            aplicar_params.ejecutar(dict(config='config.json', pieza='no_existe'), self.p.ctx)

    def test_idempotente(self):
        e = dict(config='config.json'); aplicar_params.ejecutar(e, self.p.ctx); a = self._params()
        aplicar_params.ejecutar(e, self.p.ctx); self.assertEqual(a, self._params())

if __name__ == '__main__': unittest.main()
