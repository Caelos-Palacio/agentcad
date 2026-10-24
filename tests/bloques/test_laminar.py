"""Prueba de contrato del bloque laminar (modo simulado = laminador FALSO) + comportamiento con el laminador falso en modo real + prueba OPCIONAL con el laminador real.
Todo digital: el laminador falso escribe gcode SINTÉTICO. La clase `Real` solo corre con AGENTCAD_LAMINADOR_REAL=<ruta del laminador> (requiere laminador instalado y su datadir)."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import trimesh
from tests.bloques import contrato
from agentcad import pipeline as pl, laminador


def stl_placa(ruta, n=2, sep=25.0):
    partes = []
    for i in range(n):
        b = trimesh.creation.box(extents=(20, 20, 8)); b.apply_translation((10 + i * (20 + sep), 10, 4)); partes.append(b)
    trimesh.util.concatenate(partes).export(ruta); return ruta

TOML_FALSO = '''[gcode]
perfil = "demo"
[gcode.perfiles.demo]
cama_x_mm = 220.0
cama_y_mm = 220.0
z_max_mm = 250.0
caudal_max_mm3_s = 12.0
[laminar]
perfil = "falso"
[laminar.perfiles.falso]
comando = ["@falso"]
cama_x_mm = 220.0
cama_y_mm = 220.0
z_max_mm = 250.0
[laminar.perfiles.pequeno]
comando = ["@falso"]
cama_x_mm = 50.0
cama_y_mm = 50.0
z_max_mm = 250.0
'''


class Contrato(contrato.ContratoBloque):
    NOMBRE = 'laminar'
    def entradas_ejemplo(self, proyecto):
        stl_placa(proyecto.raiz / 'placa.stl'); return dict(placa='placa.stl')

    def test_pesado_y_cacheable(self):
        self.assertTrue(self.mod.MANIFIESTO['pesado']); self.assertTrue(self.mod.MANIFIESTO['determinista']); self.assertFalse(self.mod.MANIFIESTO['deshacible'])
    def test_simulado_marca_la_salida_como_sintetica(self):
        r = pl.ejecutar_bloque(self.NOMBRE, self.entradas_ejemplo(self.p), self.p.ctx)
        self.assertTrue(r['simulado']); self.assertTrue(r['ok'], r['diagnostico']); self.assertTrue((self.p.raiz / r['gcode']).is_file())
    def test_unidades_declaradas(self):
        s = self.mod.MANIFIESTO['salidas']; self.assertEqual((s['tiempo_min']['unidad'], s['filamento_g']['unidad']), ('min', 'g'))


class ConFalso(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.r = Path(self.t.name).resolve(); (self.r / 'agentcad.toml').write_text(TOML_FALSO)
        env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_LOCK_HELD': '1', 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo')}); env.start(); self.addCleanup(env.stop)
        os.environ.pop('AGENTCAD_FALSO_CHOQUE', None); stl_placa(self.r / 'placa.stl'); self.ctx = dict(raiz=str(self.r))
    def lam(self, **e): return pl.ejecutar_bloque('laminar', dict(placa='placa.stl', **e), self.ctx)

    def test_modo_real_con_laminador_falso_deja_gcode_y_manifiesto(self):
        r = self.lam(); self.assertTrue(r['ok'], r['diagnostico']); self.assertTrue(r['simulado']); self.assertEqual(r['objetos'], 2)
        self.assertTrue((self.r / r['gcode']).is_file()); self.assertFalse(Path(r['gcode']).is_absolute()); m = json.loads((self.r / r['manifiesto']).read_text())
        self.assertEqual(m['unidades']['tiempo_min'], 'min'); self.assertLessEqual(len(json.dumps(r)), 4096)

    def test_resultado_encaja_con_check_gcode_y_render(self):
        r = self.lam(); c = pl.ejecutar_bloque('check_gcode', dict(archivo=r['gcode']), self.ctx)
        self.assertTrue(c['ok'], c['mensajes']); self.assertEqual(c['islas'], 0); self.assertEqual(c['capas'], r['capas'])

    def test_cache_acierta_y_se_recalcula_si_falta_el_gcode(self):
        with mock.patch.object(laminador, 'laminar', wraps=laminador.laminar) as m:
            a = self.lam(); b = self.lam(); self.assertEqual(m.call_count, 1); self.assertEqual(a, b)
            (self.r / a['gcode']).unlink(); c = self.lam(); self.assertEqual(m.call_count, 2); self.assertTrue((self.r / c['gcode']).is_file())
            self.lam(ajustes={'*': {'wall_loops': 4}}); self.assertEqual(m.call_count, 3)                  # otros ajustes = otra clave

    def test_perfil_declarado_y_cama_pequena(self):
        with self.assertRaisesRegex(ValueError, 'cama'): self.lam(perfil='pequeno')
    def test_perfil_desconocido(self):
        with self.assertRaisesRegex(ValueError, 'no declarado'): self.lam(perfil='zzz')
    def test_rutas_fuera_de_la_raiz_o_tipo_incorrecto(self):
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'): pl.ejecutar_bloque('laminar', dict(placa='/etc/passwd'), self.ctx)
        (self.r / 'a.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'stl'): pl.ejecutar_bloque('laminar', dict(placa='a.txt'), self.ctx)
        with self.assertRaises(FileNotFoundError): pl.ejecutar_bloque('laminar', dict(placa='no.stl'), self.ctx)
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'): self.lam(salida='/tmp/agentcad_fuera_de_la_raiz')
    def test_soporte_choca_y_se_resuelve(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_FALSO_CHOQUE': '1'}):
            r = self.lam(ajustes={'*': {'enable_support': 1}}); self.assertTrue(r['ok'], r['diagnostico']); self.assertEqual(r['intentos'], 2)
    def test_fallo_del_laminador_es_ok_false_no_excepcion(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_FALSO_CHOQUE': 'siempre'}):
            r = self.lam(ajustes={'*': {'enable_support': 1}}); self.assertFalse(r['ok']); self.assertEqual(r['gcode'], ''); self.assertTrue((self.r / r['manifiesto']).is_file())

    def test_pipeline_simulado_del_ejemplo(self):
        """El ejemplo autocontenido (laminar -> check_gcode -> render_gcode) en modo simulado, sobre una copia del proyecto de ejemplo."""
        import shutil
        ej = Path(__file__).resolve().parents[2] / 'ejemplos' / 'soporte_simple'; dst = self.r / 'ej'
        shutil.copytree(ej, dst, ignore=shutil.ignore_patterns('build', 'trabajo', 'registro', 'gcode', '__pycache__'))
        pipe = json.loads((dst / 'pipelines' / 'laminar_y_revisar.json').read_text()); self.assertEqual(pl.validar(pipe), [])
        with mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(dst), 'AGENTCAD_TRABAJO_DIR': str(dst / 'trabajo')}):
            d = pl.Ejecutor(pipe, None, 'pruebas', str(dst), simulado=True).correr()
        self.assertEqual(d['estado'], 'ok', d.get('fallo')); self.assertEqual([p['bloque'] for p in d['pasos'].values()][:3], ['laminar', 'check_gcode', 'render_gcode'])
        self.assertTrue(d['pasos']['laminar']['salidas']['simulado']); self.assertTrue((dst / d['pasos']['render']['salidas']['png']).is_file())


REAL = os.environ.get('AGENTCAD_LAMINADOR_REAL')

@unittest.skipUnless(REAL, 'prueba OPCIONAL con el laminador real: exporta AGENTCAD_LAMINADOR_REAL=<ruta del laminador> y AGENTCAD_LAMINADOR_DATADIR=<datadir> (requiere laminador instalado)')
class Real(unittest.TestCase):
    """Una placa pequeña (2 cubos de 20 mm) laminada con el laminador REAL (Anycubic Slicer Next por defecto). Pesada: ejecútala bajo el flock compartido. El datadir real se COPIA."""
    def test_placa_pequena(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t).resolve(); env = os.environ.get
            toml = (f'[laminar]\nperfil = "real"\n[laminar.perfiles.real]\ncomando = ["{REAL}"]\ndatadir = "{env("AGENTCAD_LAMINADOR_DATADIR", "~/.config/AnycubicSlicerNext")}"\n'
                    f'maquina = "{env("AGENTCAD_LAMINADOR_MAQUINA", "Anycubic Kobra 3 0.4 nozzle")}"\nproceso = "{env("AGENTCAD_LAMINADOR_PROCESO", "0.20mm Standard @Anycubic Kobra 3 0.4 nozzle")}"\n'
                    f'filamento = "{env("AGENTCAD_LAMINADOR_FILAMENTO", "Anycubic PETG @Anycubic Kobra 3 0.4 nozzle")}"\ncama_x_mm = 250.0\ncama_y_mm = 250.0\nz_max_mm = 260.0\ntimeout_s = 600\n'
                    '[laminar.perfiles.real.ajustes_proceso]\nline_width = "0.45"\nsparse_infill_density = "15%"\nwall_loops = "3"\nenable_support = "0"\n')
            (r / 'agentcad.toml').write_text(toml); stl_placa(r / 'placa.stl', n=2, sep=20.0)
            with mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(r), 'AGENTCAD_TRABAJO_DIR': str(r / 'trabajo')}):
                o = pl.ejecutar_bloque('laminar', dict(placa='placa.stl'), dict(raiz=str(r)))
            self.assertTrue(o['ok'], o['diagnostico']); self.assertFalse(o['simulado']); self.assertGreater(o['capas'], 10); self.assertGreater(o['tiempo_min'], 1); self.assertGreater(o['filamento_g'], 1)
            g = (r / o['gcode']).read_text(errors='replace'); self.assertIn('EXCLUDE_OBJECT_DEFINE', g); self.assertEqual(o['objetos'], 2)
            self.assertFalse(list((r / 'trabajo').rglob('dd')))                      # la copia temporal del datadir se borró


if __name__ == '__main__': unittest.main()
