"""Trazabilidad de procedencia: qué versión de spec/STL/solver/código/configuración produjo cada resultado (idea de DVC/MLflow, implementación propia)."""
import json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from agentcad import procedencia, tools, registro, pipeline as pl
from tests import EJEMPLO
from tests.test_pipeline import Falso, Base, pipe
from tests import fixtures as fx

class Piezas(unittest.TestCase):
    def test_base_tiene_version_python_librerias_toml(self):
        b = procedencia.base(); self.assertIn('agentcad', b); self.assertIn('python', b); self.assertIn('numpy', b['librerias'])
        self.assertEqual(len(b['toml_sha256']), 64)
    def test_pieza_lleva_sha256_del_stl(self):
        import hashlib
        p = procedencia.de_pieza('placa_soporte'); self.assertEqual(p['sha256'], hashlib.sha256((EJEMPLO / 'stl' / 'placa_soporte.stl').read_bytes()).hexdigest())
        self.assertEqual(p['modulo'], 'placa_soporte'); self.assertNotIn('/home', p.get('ruta', ''))
    def test_pieza_inexistente_no_rompe(self): self.assertIsNone(procedencia.de_pieza('zzz_no_existe')['sha256'])
    def test_spec_version_y_sha(self):
        s = procedencia.de_spec(dict(pieza='x', version=7, requisitos=[])); self.assertEqual(s['version'], 7); self.assertEqual(len(s['sha256']), 64)
        self.assertNotEqual(s['sha256'], procedencia.de_spec(dict(pieza='x', version=8, requisitos=[]))['sha256'])
    def test_spec_desde_el_directorio_de_specs(self):
        s = procedencia.de_spec(None, pieza='placa_soporte'); self.assertEqual(s['version'], 1); self.assertEqual(len(s['sha256']), 64)
    def test_solver_identificado_por_el_hash_de_su_codigo(self):
        s = procedencia.solver(); self.assertEqual(s['nombre'], 'fem3d'); self.assertIn('hexaedro', s['elemento']); self.assertEqual(len(s['sha256_fem3d']), 64)
    def test_commit_de_un_repositorio_git(self):
        t = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, t)
        self.assertIsNone(procedencia.commit(t))
        subprocess.run(['git', 'init', '-q', t], check=True); (Path(t) / 'a').write_text('x')
        subprocess.run(['git', '-C', t, 'add', 'a'], check=True)
        subprocess.run(['git', '-C', t, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'm'], check=True)
        c = procedencia.commit(t); self.assertEqual(len(c), 40)
        (Path(t) / 'a').write_text('y'); self.assertTrue(procedencia.commit(t, con_sucio=True).endswith('+sucio'))

class Herramientas(unittest.TestCase):
    def test_describe_interferencia_fabricabilidad_llevan_procedencia(self):
        for n, a in [('describe_part', dict(part='placa_soporte', radio_vecinas_mm=0)), ('check_interference', dict(part='placa_soporte')), ('check_printability', dict(part='placa_soporte'))]:
            r = tools.llamar_directo(n, a); self.assertEqual(r['estado'], 'ok'); p = r['procedencia']
            self.assertEqual(p['pieza']['modulo'], 'placa_soporte'); self.assertEqual(len(p['pieza']['sha256']), 64); self.assertIn('agentcad', p)
    def test_estructura_incluye_solver(self):
        r = tools.llamar_directo('evaluate_structure', dict(part='placa_soporte', fidelity=2.0)); self.assertEqual(r['procedencia']['solver']['nombre'], 'fem3d')
    def test_check_spec_incluye_la_spec(self):
        r = tools.llamar_directo('check_spec', dict(part='placa_soporte', fidelity_estructura=2.0)); s = r['procedencia']['spec']; self.assertEqual(s['version'], 1); self.assertEqual(len(s['sha256']), 64)
        self.assertEqual(r['procedencia']['solver']['nombre'], 'fem3d')
    def test_check_spec_en_linea(self):
        spec = dict(pieza='placa_soporte', version=3, requisitos=[dict(id='m', metrica='describe.masa_estimada_g', op='<=', valor=50.0, unidad='g')])
        r = tools.llamar_directo('check_spec', dict(part='placa_soporte', spec=spec)); self.assertEqual(r['procedencia']['spec']['version'], 3)
    def test_un_error_no_lleva_procedencia(self): self.assertNotIn('procedencia', tools.llamar_directo('describe_part', dict(part='zzz_no_existe')))
    def test_cambiar_el_stl_cambia_el_sha(self):
        a = tools.llamar_directo('describe_part', dict(part=fx.cubo(10), radio_vecinas_mm=0)); b = tools.llamar_directo('describe_part', dict(part=fx.cubo(11), radio_vecinas_mm=0))
        self.assertNotEqual(a['procedencia']['pieza']['sha256'], b['procedencia']['pieza']['sha256'])
    def test_el_esquema_de_salida_acepta_procedencia(self):
        from agentcad import schema
        r = tools.llamar_directo('describe_part', dict(part='placa_soporte', radio_vecinas_mm=0)); self.assertEqual(schema.validate(r, tools.TOOLS['describe_part']['outputSchema']), [])

class Registro(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.d); self._old = os.environ.get('AGENTCAD_REGISTRO_DIR'); os.environ['AGENTCAD_REGISTRO_DIR'] = self.d
        self.addCleanup(lambda: os.environ.__setitem__('AGENTCAD_REGISTRO_DIR', self._old) if self._old else os.environ.pop('AGENTCAD_REGISTRO_DIR', None))
    def test_el_registro_guarda_la_procedencia_y_la_cadena_sigue_integra(self):
        r = registro.record_result('describe_part', 'placa_soporte', resultado={'a': 1}); self.assertEqual(r['estado'], 'ok')
        e = json.loads((Path(self.d) / 'registro.jsonl').read_text().splitlines()[-1]); p = e['procedencia']
        self.assertEqual(p['pieza']['modulo'], 'placa_soporte'); self.assertEqual(len(p['pieza']['sha256']), 64); self.assertIn('toml_sha256', p)
        self.assertTrue(registro.verificar_cadena()['integra'])
    def test_manipular_la_procedencia_rompe_la_cadena(self):
        registro.record_result('describe_part', 'placa_soporte', resultado={'a': 1}); f = Path(self.d) / 'registro.jsonl'
        f.write_text(f.read_text().replace(procedencia.de_pieza('placa_soporte')['sha256'], '0' * 64)); self.assertFalse(registro.verificar_cadena()['integra'])

class Pipelines(Base):
    def test_el_diario_guarda_procedencia_por_paso_y_global(self):
        f = self.inyectar(Falso('fk_p', entradas={'x': {'type': 'integer'}})); p = pipe([{'id': 'a', 'bloque': 'fk_p', 'entradas': {'x': 1}}])
        d = pl.Ejecutor(p, {}, 'c1', self.raiz, True).correr(); pp = d['pasos']['a']['procedencia']
        self.assertEqual(len(pp['bloque_sha256']), 64); self.assertEqual(len(pp['entradas_sha256']), 64); self.assertIn('agentcad', d['procedencia'])
        self.assertIn('python', d['procedencia'])
    def test_mismas_entradas_mismo_sha_de_entradas(self):
        self.inyectar(Falso('fk_p', entradas={'x': {'type': 'integer'}})); p = pipe([{'id': 'a', 'bloque': 'fk_p', 'entradas': {'x': 1}}])
        a = pl.Ejecutor(p, {}, 'c1', self.raiz, True).correr()['pasos']['a']['procedencia']['entradas_sha256']
        b = pl.Ejecutor(p, {}, 'c2', self.raiz, True).correr()['pasos']['a']['procedencia']['entradas_sha256']; self.assertEqual(a, b)
if __name__ == '__main__': unittest.main()
