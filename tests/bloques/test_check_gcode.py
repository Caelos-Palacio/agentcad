"""Prueba de contrato del bloque check_gcode (modo simulado) + comportamiento real sobre gcode SINTÉTICO generado por código en un directorio temporal."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from tests.bloques import contrato
from tests.test_gcode import make_gcode, capa, solid, fill_square
from agentcad import pipeline as pl

TOML = '''[gcode]
perfil = "demo"
[gcode.perfiles.demo]
cama_x_mm = 200.0
cama_y_mm = 200.0
z_max_mm = 100.0
caudal_max_mm3_s = 8.0
temp_boquilla_max = 250
temp_cama_max = 80
velocidad_max_mm_s = 450
[gcode.perfiles.pequena]
cama_x_mm = 110.0
cama_y_mm = 110.0
z_max_mm = 100.0
'''

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'check_gcode'

    def test_simulado_usa_gcode_de_sim_json(self):
        s = json.loads(self.p.leer('sim.json')); s['gcode'] = dict(ok=False, islas=2); (self.p.raiz / 'sim.json').write_text(json.dumps(s))
        r = pl.ejecutar_bloque(self.NOMBRE, dict(archivo='no_existe.gcode'), self.p.ctx)
        self.assertFalse(r['ok']); self.assertEqual(r['islas'], 2); self.assertIn('simulado', r['mensajes'][0])

    def test_no_es_deshacible(self):
        self.assertFalse(self.mod.MANIFIESTO['deshacible']); self.assertFalse(hasattr(self.mod, 'deshacer'))

class Real(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.r = Path(self.t.name); (self.r / 'agentcad.toml').write_text(TOML)
        (self.r / 'gcode').mkdir(); env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_LOCK_HELD': '1', 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo')}); env.start(); self.addCleanup(env.stop)
        self.ctx = dict(raiz=str(self.r))
    def escribir(self, nombre, gc): (self.r / 'gcode' / nombre).write_text(gc); return f'gcode/{nombre}'
    def correr(self, archivo, **kw): return pl.ejecutar_bloque('check_gcode', dict(archivo=archivo, **kw), self.ctx)

    def test_pieza_limpia(self):
        r = self.correr(self.escribir('a.gcode', make_gcode([capa(k, solid(60, 60, 80, 80)) for k in range(1, 6)])))
        self.assertTrue(r['ok'], r['mensajes']); self.assertEqual((r['islas'], r['fuera_de_cama'], r['errores']), (0, 0, 0)); self.assertEqual(r['capas'], 5); self.assertGreater(r['masa_g'], 0)

    def test_isla_flotante(self):
        capas = [capa(k, solid(60, 60, 80, 80)) for k in range(1, 6)] + [capa(6, solid(60, 60, 80, 80) + [("Sparse infill", fill_square(120, 120, 130, 130))])]
        r = self.correr(self.escribir('b.gcode', make_gcode(capas)))
        self.assertFalse(r['ok']); self.assertGreaterEqual(r['islas'], 1)

    def test_voladizo_apoyado_en_soporte_no_es_isla(self):
        capas = [capa(k, solid(60, 60, 80, 80) + [("Support", fill_square(120, 120, 130, 130))]) for k in range(1, 6)]
        capas.append(capa(6, solid(60, 60, 80, 80) + [("Sparse infill", fill_square(120, 120, 130, 130))]))
        r = self.correr(self.escribir('c.gcode', make_gcode(capas)))
        self.assertEqual((r['islas'], r['soportes_sin_cama']), (0, 0))

    def test_fuera_de_cama_con_el_perfil_pequeno(self):
        a = self.escribir('d.gcode', make_gcode([capa(1, solid(60, 60, 130, 80))]))
        self.assertTrue(self.correr(a)['ok'])                               # cabe en 200 x 200
        r = self.correr(a, perfil='pequena'); self.assertFalse(r['ok']); self.assertGreater(r['fuera_de_cama'], 0)

    def test_guardar_detalle(self):
        r = self.correr(self.escribir('e.gcode', make_gcode([capa(1, solid(60, 60, 80, 80))])), guardar=True)
        self.assertTrue(Path(r['detalle']).is_file()); self.assertIn('floating_islands', json.loads(Path(r['detalle']).read_text()))

    def test_cache_por_contenido_del_gcode(self):
        a = self.escribir('f.gcode', make_gcode([capa(1, solid(60, 60, 80, 80))])); self.correr(a)
        (self.r / a).write_text(make_gcode([capa(1, solid(60, 60, 80, 80)), capa(2, solid(60, 60, 80, 80) + [("Sparse infill", fill_square(120, 120, 130, 130))])]))
        self.assertEqual(self.correr(a)['capas'], 2)                        # distinto contenido = otra clave de caché

    def test_errores_claros(self):
        with self.assertRaises(FileNotFoundError): self.correr('gcode/no_existe.gcode')
        a = self.escribir('g.gcode', make_gcode([capa(1, solid(60, 60, 80, 80))]))
        with self.assertRaisesRegex(ValueError, 'no declarado'): self.correr(a, perfil='zzz')
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'): self.correr('/etc/passwd')

class Ejemplo(unittest.TestCase):
    RAIZ = Path(__file__).resolve().parents[2] / 'ejemplos' / 'soporte_simple'
    def test_gcode_del_ejemplo_es_determinista_y_tiene_un_puente_largo(self):
        import importlib.util
        sp = importlib.util.spec_from_file_location('generar_gcode_ej', self.RAIZ / 'generar_gcode.py'); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
        self.assertEqual(m.generar(), m.generar()); self.assertLess(len(m.generar()), 100_000)
        with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {'AGENTCAD_LOCK_HELD': '1'}):
            (Path(t) / 'agentcad.toml').write_text((self.RAIZ / 'agentcad.toml').read_text()); (Path(t) / 'g.gcode').write_text(m.generar())
            r = pl.ejecutar_bloque('check_gcode', dict(archivo='g.gcode'), dict(raiz=t))
        self.assertTrue(r['ok']); self.assertEqual((r['islas'], r['puentes_largos'], r['capas']), (0, 1, 6))
    def test_pipeline_de_ejemplo_valida(self):
        pipe = json.loads((self.RAIZ / 'pipelines' / 'revisar_laminado.json').read_text())
        self.assertEqual(pl.validar(pipe), [])
        self.assertIn('check_gcode', [p['bloque'] for p in pipe['pasos']])

if __name__ == '__main__': unittest.main()
