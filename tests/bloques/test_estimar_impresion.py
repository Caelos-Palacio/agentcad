"""Prueba de contrato del bloque estimar_impresion + comportamiento (calibración declarada en [calibracion] de agentcad.toml; sin calibración no hay cifras)."""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock
from tests.bloques import contrato
from agentcad import pipeline as pl

TOML = '''[calibracion]
perfil = "demo"
[calibracion.perfiles.demo]
razon_filamento = 0.8
error_filamento_rel = 0.10
s_por_g = 100.0
error_tiempo_rel = 0.20
n_grupos = 4
origen = "datos sintéticos de la prueba"
'''

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'estimar_impresion'
    def setUp(self):
        super().setUp()
        if self.mod is None: return
        (self.p.raiz / 'agentcad.toml').write_text(TOML); env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.p.raiz)}); env.start(); self.addCleanup(env.stop)

    def test_estima_con_banda_y_aviso_de_pocos_grupos(self):
        r = pl.ejecutar_bloque(self.NOMBRE, dict(masa_g=100.0), self.p.ctx)
        self.assertAlmostEqual(r['filamento_g'], 80.0); self.assertAlmostEqual(r['filamento_min_g'], 72.0); self.assertAlmostEqual(r['filamento_max_g'], 88.0)
        self.assertAlmostEqual(r['tiempo_h'], 100.0 * 100.0 / 3600, places=3); self.assertAlmostEqual(r['tiempo_max_h'], 100.0 * 100.0 / 3600 * 1.2, places=3)
        self.assertFalse(r['fiable']); self.assertIn('4 grupos', r['nota']); self.assertIn('digital', r['nota'])
    def test_sin_calibracion_no_inventa_cifras(self):
        (self.p.raiz / 'agentcad.toml').write_text('[proyecto]\nnombre = "x"\n')
        with self.assertRaisesRegex(ValueError, 'no_calibrado'): pl.ejecutar_bloque(self.NOMBRE, dict(masa_g=100.0), self.p.ctx)
    def test_perfil_desconocido(self):
        with self.assertRaisesRegex(ValueError, 'no_calibrado'): pl.ejecutar_bloque(self.NOMBRE, dict(masa_g=100.0, perfil='zzz'), self.p.ctx)
    def test_masa_no_positiva(self):
        with self.assertRaisesRegex(ValueError, 'masa_g'): pl.ejecutar_bloque(self.NOMBRE, dict(masa_g=0.0), self.p.ctx)
    def test_no_es_deshacible(self): self.assertFalse(hasattr(self.mod, 'deshacer'))

if __name__ == '__main__': unittest.main()
