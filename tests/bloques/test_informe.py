"""Prueba de contrato del bloque informe (+ comportamiento: secciones obligatorias, incumplimientos conocidos visibles, aviso de simulado)."""
import json, unittest
from tests.bloques import contrato
from agentcad import pipeline as pl

DIARIO = dict(nombre='integrar_variante', corrida='t', modo='simulado', estado='corriendo', rollbacks=1,
    rollback_piezas=[dict(pieza='soporte', motivo='pared[soporte]', salida={})],
    pasos={'fem[placa]': dict(bloque='puerta_margen_fem', estado='ok', entradas={'pieza': 'placa'}, salidas=dict(ok=True, base=0.34, candidato=0.68, incumple_criterio=True, estado='validado_digital', nota='margen 0,68 < 2')),
           'fem[tapa]': dict(bloque='puerta_margen_fem', estado='ok', entradas={'pieza': 'tapa'}, salidas=dict(ok=False, base=0.0, candidato=0.0, incumple_criterio=False, estado='no_validado', nota='sin FEM')),
           'construir': dict(bloque='build', estado='ok', salidas={})})

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'informe'
    def _diario(self, d=DIARIO):
        (self.p.raiz / 'build/pipelines').mkdir(parents=True, exist_ok=True); (self.p.raiz / 'build/pipelines/d.json').write_text(json.dumps(d)); return 'build/pipelines/d.json'
    def entradas_ejemplo(self, p): return dict(etiqueta='v2', diario=self._diario())
    def test_informe_no_oculta_incumplimientos_ni_no_validado(self):
        s = pl.ejecutar_bloque('informe', dict(etiqueta='v2', diario=self._diario()), self.p.ctx); t = self.p.leer('build/INFORME_v2.md')
        self.assertEqual(s['incumplimientos'], 1); self.assertEqual(s['revertidas'], ['soporte'])
        for frag in ('MODO SIMULADO', 'placa', '0.68', 'no_validado', 'tapa', 'soporte', 'Digital vs físico'): self.assertIn(frag, t)
    def test_modo_real_no_lleva_aviso_de_simulado(self):
        s = pl.ejecutar_bloque('informe', dict(etiqueta='v3', diario=self._diario({**DIARIO, 'modo': 'real'})), self.p.ctx)
        self.assertNotIn('MODO SIMULADO', self.p.leer('build/INFORME_v3.md'))
if __name__ == '__main__': unittest.main()
