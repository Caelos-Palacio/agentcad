"""Pruebas de la instrumentación genérica (agentcad/instr.py): tiempo de pared y CPU, memoria pico (muestreo, básica, tracemalloc), etapas anidadas
con tiempo exclusivo, hilos, procesos hijos (sumidero JSONL), desactivación por entorno y por agentcad.toml, y que instrumentar no cambia resultados."""
import json, os, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
import numpy as np
from agentcad import instr
from tests._marcas import pesada

REPO = Path(__file__).resolve().parent.parent

class Base(unittest.TestCase):
    def setUp(self):
        instr.restablecer(); self.addCleanup(instr.restablecer)
        self._env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith('AGENTCAD_INSTR')}
        self.addCleanup(lambda: (os.environ.update(self._env)))
        instr.configurar(activa=True, memoria='muestreo', intervalo_ms=10)

class Etapas(Base):
    def test_registra_tiempo_de_pared_y_cpu(self):
        with instr.etapa('dormir'): time.sleep(0.05)
        with instr.etapa('quemar'):
            t = time.process_time()
            while time.process_time() - t < 0.05: pass
        a, b = instr.registros()
        self.assertEqual((a['etapa'], b['etapa']), ('dormir', 'quemar'))
        self.assertGreaterEqual(a['seg'], 0.05); self.assertLess(a['cpu_s'], 0.03)            # dormir no gasta CPU
        self.assertGreaterEqual(b['cpu_s'], 0.045); self.assertGreaterEqual(b['seg'], b['cpu_s'] - 0.01)

    def test_campos_y_unidades_en_el_nombre(self):
        with instr.etapa('x', n=3) as e: e.fijar(nnz=7)
        r, = instr.registros()
        for k in ('tipo', 'etapa', 'seg', 'excl_seg', 'cpu_s', 'rss_ini_mib', 'rss_pico_mib', 'rss_fin_mib', 'prof', 't_ini_s', 'pid', 'seq'): self.assertIn(k, r)
        self.assertEqual((r['tipo'], r['n'], r['nnz'], r['prof']), ('etapa', 3, 7, 0)); json.dumps(r)

    def test_etapas_anidadas_tiempo_exclusivo(self):
        with instr.etapa('padre'):
            time.sleep(0.03)
            with instr.etapa('hijo'): time.sleep(0.06)
        h, p = instr.registros()                                      # el hijo termina primero
        self.assertEqual((h['etapa'], p['etapa'], h['prof'], p['prof']), ('hijo', 'padre', 1, 0))
        self.assertAlmostEqual(p['seg'] - p['excl_seg'], h['seg'], delta=0.005)
        self.assertGreaterEqual(p['excl_seg'], 0.03); self.assertLess(p['excl_seg'], 0.055)

    def test_la_excepcion_se_propaga_y_se_registra(self):
        with self.assertRaises(ValueError):
            with instr.etapa('falla'): raise ValueError('x')
        r, = instr.registros(); self.assertEqual(r['error'], 'ValueError')

    def test_decorador_conserva_funcion_y_mide(self):
        @instr.medida('suma', meta=lambda a, b: dict(n=a + b))
        def suma(a, b):
            """doc"""
            return a + b
        self.assertEqual(suma(2, 3), 5); self.assertEqual(suma.__name__, 'suma'); self.assertEqual(suma.__doc__, 'doc')
        r, = instr.registros(); self.assertEqual((r['etapa'], r['n']), ('suma', 5))

    def test_meta_numpy_se_serializa(self):
        with instr.etapa('np', n=np.int64(4), x=np.float64(1.5), arr=np.arange(3)): pass
        r, = instr.registros(); json.dumps(r); self.assertEqual(r['n'], 4)

    def test_hilos_tienen_pila_propia(self):
        def trabajo(nombre):
            with instr.etapa(nombre):
                time.sleep(0.03)
                with instr.etapa(nombre + '_in'): time.sleep(0.02)
        ts = [threading.Thread(target=trabajo, args=(f'h{i}',)) for i in range(3)]
        [t.start() for t in ts]; [t.join() for t in ts]
        por = {r['etapa']: r for r in instr.registros()}
        for i in range(3):
            self.assertEqual(por[f'h{i}_in']['prof'], 1); self.assertEqual(por[f'h{i}']['prof'], 0)
            self.assertAlmostEqual(por[f'h{i}']['seg'] - por[f'h{i}']['excl_seg'], por[f'h{i}_in']['seg'], delta=0.005)

    def test_buffer_acotado(self):
        for i in range(instr.MAX_REGISTROS + 50):
            with instr.etapa('x'): pass
        self.assertEqual(len(instr.registros()), instr.MAX_REGISTROS)

    def test_marca_y_desde(self):
        with instr.etapa('a'): pass
        m = instr.marca()
        with instr.etapa('b'): pass
        instr.cache_evento('c', acierto=True)
        self.assertEqual([r['etapa'] for r in instr.desde(m) if r['tipo'] == 'etapa'], ['b']); self.assertEqual(len(instr.desde(m)), 2)

class Memoria(Base):
    def test_muestreo_ve_el_pico_aunque_se_libere_antes_de_salir(self):
        with instr.etapa('pico'):
            a = np.ones(12_000_000)                                  # 96 MB tocados
            time.sleep(0.15); del a                                  # >10 muestreos de 10 ms con el bloque vivo
        r, = instr.registros()
        self.assertGreaterEqual(r['rss_pico_mib'] - r['rss_ini_mib'], 70)
        self.assertLess(r['rss_fin_mib'] - r['rss_ini_mib'], 40)

    def test_basica_ve_el_estado_final(self):
        instr.configurar(memoria='basica')
        with instr.etapa('fin'):
            a = np.ones(12_000_000); time.sleep(0.02)
        r, = instr.registros(); self.assertGreaterEqual(r['rss_fin_mib'] - r['rss_ini_mib'], 70); self.assertGreaterEqual(r['rss_pico_mib'], r['rss_fin_mib'])
        del a

    def test_tracemalloc_mide_asignaciones_de_python(self):
        instr.configurar(memoria='tracemalloc')
        with instr.etapa('tm'):
            with instr.etapa('interna'):
                a = np.ones(6_000_000); del a                        # 48 MB asignados y liberados
        i, p = instr.registros()
        self.assertGreaterEqual(i['py_pico_mib'], 40); self.assertGreaterEqual(p['py_pico_mib'], i['py_pico_mib'] - 0.5)   # el padre ve el pico del hijo

    def test_sin_memoria(self):
        instr.configurar(memoria='no')
        with instr.etapa('x'): pass
        r, = instr.registros(); self.assertNotIn('rss_pico_mib', r)

    def test_memoria_invalida(self):
        with self.assertRaises(ValueError): instr.configurar(memoria='inventada')

class Cache(Base):
    def test_eventos_y_resumen(self):
        instr.cache_evento('orden', acierto=False, n_dof=10); instr.cache_evento('orden', acierto=True); instr.cache_evento('orden', acierto=True)
        self.assertEqual(instr.resumir_cache(instr.registros()), {'orden': {'aciertos': 2, 'fallos': 1}})

class Resumen(Base):
    def test_agrega_por_etapa_y_ordena_por_tiempo_exclusivo(self):
        for _ in range(3):
            with instr.etapa('rapida', n=1): pass
        with instr.etapa('lenta', n_dof=99):
            time.sleep(0.04)
        s = instr.resumir(instr.registros())
        self.assertEqual([x['etapa'] for x in s], ['lenta', 'rapida'])
        self.assertEqual(s[1]['llamadas'], 3); self.assertEqual(s[0]['tam'], {'n_dof': 99}); self.assertGreaterEqual(s[0]['seg'], 0.04)
        self.assertEqual(len(instr.resumir(instr.registros(), top=1)), 1)

class Activacion(Base):
    def test_desactivada_es_nula_y_no_registra(self):
        instr.configurar(activa=False)
        with instr.etapa('x', n=1) as e: e.fijar(y=2)
        instr.cache_evento('c', acierto=True)
        self.assertEqual(instr.registros(), []); self.assertFalse(instr.activa())
        @instr.medida('d')
        def f(): return 7
        self.assertEqual(f(), 7); self.assertEqual(instr.registros(), [])

    def test_variable_de_entorno_manda_sobre_el_toml(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'agentcad.toml').write_text('[instrumentacion]\nactiva = true\n')
            instr.restablecer(); os.environ['AGENTCAD_INSTR'] = '0'; instr.cargar_config(t); self.assertFalse(instr.activa())
            instr.restablecer(); os.environ['AGENTCAD_INSTR'] = '1'; (Path(t) / 'agentcad.toml').write_text('[instrumentacion]\nactiva = false\n'); instr.cargar_config(t); self.assertTrue(instr.activa())
            os.environ.pop('AGENTCAD_INSTR')

    def test_toml_desactiva_y_configura_memoria(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'agentcad.toml').write_text('[instrumentacion]\nactiva = false\n'); instr.restablecer(); instr.cargar_config(t); self.assertFalse(instr.activa())
            (Path(t) / 'agentcad.toml').write_text('[instrumentacion]\nmemoria = "basica"\nintervalo_ms = 20\n'); instr.restablecer(); instr.cargar_config(t)
            self.assertTrue(instr.activa()); self.assertEqual(instr.modo_memoria(), 'basica')

    def test_defecto_activa_con_muestreo(self):
        with tempfile.TemporaryDirectory() as t:
            instr.restablecer(); instr.cargar_config(t); self.assertTrue(instr.activa()); self.assertEqual(instr.modo_memoria(), 'muestreo')

    def test_configurar_manda_sobre_cargar_config(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'agentcad.toml').write_text('[instrumentacion]\nactiva = false\n')
            instr.configurar(activa=True); instr.cargar_config(t); self.assertTrue(instr.activa())

    def test_toml_mal_formado_no_rompe(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'agentcad.toml').write_text('[instrumentacion\n'); instr.restablecer(); instr.cargar_config(t); self.assertTrue(instr.activa())

class Medida(Base):
    def test_medir_paso_agrega_etapas_y_cpu_de_hijos(self):
        with instr.medir_paso() as m:
            with instr.etapa('a'): time.sleep(0.03)
            with instr.etapa('a'): time.sleep(0.02)
            subprocess.run([sys.executable, '-c', 'import time; t=time.process_time()\nwhile time.process_time()-t<0.15: pass'], check=True)
        p = m.perfil
        self.assertGreaterEqual(p['seg'], 0.2); self.assertEqual(p['etapas'][0]['etapa'], 'a'); self.assertEqual(p['etapas'][0]['llamadas'], 2)
        self.assertGreaterEqual(p['cpu_hijos_s'], 0.12); self.assertGreaterEqual(p['sin_instrumentar_s'], 0.1)
        for k in ('rss_ini_mib', 'rss_pico_mib', 'rss_fin_mib', 'cpu_s'): self.assertIn(k, p)
        json.dumps(p)

    def test_pico_de_memoria_del_paso(self):
        with instr.medir_paso() as m:
            a = np.ones(12_000_000); time.sleep(0.1); del a
        self.assertGreaterEqual(m.perfil['rss_pico_mib'] - m.perfil['rss_ini_mib'], 70)

    def test_desactivada_sin_perfil(self):
        instr.configurar(activa=False)
        with instr.medir_paso() as m: pass
        self.assertIsNone(m.perfil)

    def test_recoge_etapas_de_procesos_hijos(self):
        codigo = ("import sys; sys.path.insert(0, %r)\nfrom agentcad import instr\n"
                  "with instr.etapa('en_hijo', n_dof=5):\n    import time; time.sleep(0.05)\n" % str(REPO))
        with instr.medir_paso() as m:
            subprocess.run([sys.executable, '-c', codigo], check=True, env=dict(os.environ, AGENTCAD_INSTR='1'))
        nombres = {e['etapa']: e for e in m.perfil['etapas']}
        self.assertIn('en_hijo', nombres); self.assertTrue(nombres['en_hijo']['hijos']); self.assertGreaterEqual(nombres['en_hijo']['seg'], 0.05)
        self.assertNotIn('AGENTCAD_INSTR_SALIDA', os.environ)                      # el entorno queda restaurado
        self.assertFalse(any(r.get('pid') != os.getpid() for r in instr.registros()))       # el padre no mezcla los registros del hijo en su buffer

    def test_el_padre_no_duplica_sus_propios_registros_en_el_sumidero(self):
        with instr.medir_paso() as m:
            with instr.etapa('solo_padre'): pass
        self.assertEqual([e['llamadas'] for e in m.perfil['etapas'] if e['etapa'] == 'solo_padre'], [1])

class SobrecosteMedido(Base):
    """Cotas holgadas (no el valor medido: ese lo da docs/instrumentacion.md) para que una regresión grosa no pase."""
    def test_etapa_desactivada_es_casi_gratis(self):
        instr.configurar(activa=False); n = 20000; t = time.perf_counter()
        for _ in range(n):
            with instr.etapa('x', n=1): pass
        self.assertLess((time.perf_counter() - t) / n, 5e-6)

    def test_etapa_activa_cuesta_decenas_de_microsegundos(self):
        n = 3000; t = time.perf_counter()
        for _ in range(n):
            with instr.etapa('x', n=1): pass
        self.assertLess((time.perf_counter() - t) / n, 3e-4)

@pesada
class NoCambiaResultados(unittest.TestCase):
    """El mismo problema FEM en dos procesos, con y sin instrumentación, da resultados idénticos bit a bit (las etapas solo envuelven llamadas)."""
    CODE = r'''
import sys, json, numpy as np
sys.path.insert(0, %r)
from agentcad.fem3d import Voxel, voxelize_tris
occ = np.ones((30, 6, 6), bool); occ[10:14, 2:4, :] = False
v = Voxel(occ, 1.0, (0, 0, 0), E=1000.0, nu=0.3)
fixed = np.concatenate([3*v.nodes_where(lambda p: p[:, 0] < 1e-9)+d for d in range(3)])
tip = v.nodes_where(lambda p: p[:, 0] > 30-1e-9); F = np.zeros(3*v.nn); F[3*tip+2] = -1.0/len(tip)
u = v.solve(F, fixed); vm = v.vonmises(v.stress(u))
tris = np.array([[[0, 0, 0], [4, 0, 0], [0, 4, 0]], [[0, 0, 0], [0, 4, 0], [0, 0, 4]]], float)
occ2 = voxelize_tris(tris, 1.0, np.zeros(3), (5, 5, 5))
from agentcad import instr
print(json.dumps(dict(u=u.tolist(), vm=vm.tolist(), occ=occ2.astype(int).ravel().tolist(), ne=int(v.ne), etapas=sorted({r['etapa'] for r in instr.registros() if r['tipo'] == 'etapa'}))))
''' % str(REPO)
    def run_(self, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith('AGENTCAD_INSTR')}; e.update(env)
        with tempfile.TemporaryDirectory() as cwd:
            r = subprocess.run([sys.executable, '-c', self.CODE], capture_output=True, text=True, env=e, cwd=cwd, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-800:]); return json.loads(r.stdout.strip().splitlines()[-1])
    def test_resultados_identicos_y_etapas_fem_presentes(self):
        a = self.run_(AGENTCAD_INSTR='0'); b = self.run_(AGENTCAD_INSTR='1')
        etapas_b = b.pop('etapas'); self.assertEqual(a.pop('etapas'), [])
        self.assertEqual(a, b)
        for f in ('fem_nodos', 'fem_ensamblado', 'fem_factorizacion', 'fem_resolucion', 'fem_tensiones', 'voxelizar_triangulos'): self.assertIn(f, etapas_b)

if __name__ == '__main__': unittest.main()
