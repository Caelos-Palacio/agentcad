"""Prueba de contrato del bloque puerta_margen_fem + comportamiento sobre config.json de la copia (incumplimiento conocido visible, estados)."""
import json, unittest
from tests.bloques import contrato
from agentcad import pipeline as pl

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'puerta_margen_fem'

    def _cfg(self): return json.loads(self.p.leer('config.json'))
    def _guardar(self, cfg): (self.p.raiz / 'config.json').write_text(json.dumps(cfg))
    def _ej(self, pieza): return dict(config='config.json', pieza=pieza)

    def test_incumplimiento_conocido_no_se_oculta(self):
        s = pl.ejecutar_bloque(self.NOMBRE, self._ej('placa'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['estado'], 'validado_digital')
        self.assertTrue(s['incumple_criterio']); self.assertEqual((s['base'], s['candidato']), (0.34, 0.68))
        self.assertIn('conocido', s['nota'])

    def test_candidato_igual_o_mejor_cumple(self):
        s = pl.ejecutar_bloque(self.NOMBRE, self._ej('soporte'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertFalse(s['incumple_criterio'])

    def test_candidato_peor_que_base_falla(self):
        cfg = self._cfg(); cfg['piezas']['soporte']['fem']['cand'] = 1.0; self._guardar(cfg)
        s = pl.ejecutar_bloque(self.NOMBRE, self._ej('soporte'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['estado'], 'peor_que_base')

    def test_pieza_sin_fem_no_validada(self):
        cfg = self._cfg(); del cfg['piezas']['tapa']['fem']; self._guardar(cfg)
        s = pl.ejecutar_bloque(self.NOMBRE, self._ej('tapa'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['estado'], 'no_validado'); self.assertFalse(s['incumple_criterio'])

    def test_mallas_distintas_no_comparables(self):
        cfg = self._cfg(); cfg['piezas']['soporte']['fem']['malla_base_mm'] = 0.5; self._guardar(cfg)
        s = pl.ejecutar_bloque(self.NOMBRE, self._ej('soporte'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertEqual(s['estado'], 'no_comparable')

if __name__ == '__main__': unittest.main()
