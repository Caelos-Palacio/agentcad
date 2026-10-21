"""Prueba de contrato del bloque build + comportamiento simulado (masa estimada según flags, assembly.json) + ejecución REAL sobre una copia del ejemplo."""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path
from tests import EJEMPLO
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import aplicar_params, build

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'build'

    def test_sin_flags_masa_es_la_base(self):
        s = pl.ejecutar_bloque(self.NOMBRE, {}, self.p.ctx)
        self.assertTrue(s['ok']); self.assertEqual(s['masa_g'], 625.0); self.assertEqual(s['masa_g'], self.p.base_g)

    def test_con_flags_baja_la_masa(self):
        aplicar_params.ejecutar(dict(config='config.json'), self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, {}, self.p.ctx)
        self.assertEqual(s['masa_g'], 549.0)

    def test_escribe_assembly_con_las_piezas(self):
        build.simular({}, self.p.ctx)
        asm = json.loads(self.p.leer('assembly.json'))
        masas = {x['file']: x['mass_g'] for x in asm['parts']}
        self.assertEqual(masas['stl/placa.stl'], 120.0)
        self.assertEqual(masas['stl/soporte.stl'], 95.0)
        self.assertEqual(sum(masas.values()), 625.0)

    def test_build_real_sobre_copia_del_ejemplo(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); raiz = Path(t.name) / 'ej'
        shutil.copytree(EJEMPLO, raiz, ignore=shutil.ignore_patterns('registro', 'trabajo', 'build', '__pycache__'))
        toml = (raiz / 'agentcad.toml').read_text().replace('comando = ["python", "generar_stl.py"]', f'comando = [{json.dumps(sys.executable)}, "generar_stl.py"]')
        (raiz / 'agentcad.toml').write_text(toml)
        os.environ['AGENTCAD_LOCK_HELD'] = '1'; self.addCleanup(os.environ.pop, 'AGENTCAD_LOCK_HELD', None)
        s = pl.ejecutar_bloque('build', {}, dict(raiz=str(raiz), simulado=False))
        self.assertTrue(s['ok'], s); self.assertAlmostEqual(s['masa_g'], 7.57, delta=0.05)         # solo la pieza imprimible del ensamblaje
        self.assertTrue((raiz / 'build' / 'status.json').is_file())

if __name__ == '__main__': unittest.main()
