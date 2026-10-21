"""Adaptadores de integraciones/ probados con DOBLES: ninguna de las tres librerías (Snakemake, LangGraph, Airflow) está instalada ni se instala.
Verifican la lógica del adaptador (entradas, salida JSON, fallo por puerta en rojo, reanudación), NO que la API real de cada librería lo acepte sin cambios."""
import importlib.util, json, os, sys, tempfile, types, unittest
from pathlib import Path
from types import SimpleNamespace
from agentcad import sim_fixture
from tests import EJEMPLO

INT = Path(__file__).resolve().parents[1] / 'integraciones'

def cargar(nombre, ruta):
    sys.path.insert(0, str(INT)); sys.path.insert(0, str(INT / ruta.split('/')[0]))
    spec = importlib.util.spec_from_file_location(nombre, INT / ruta); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

comun = cargar('comun', 'comun.py'); sys.modules['comun'] = comun      # los adaptadores hacen `import comun`: la misma clase PuertaEnRojo
snk = cargar('agentcad_snakemake', 'snakemake/agentcad_snakemake.py')
lg = cargar('agentcad_langgraph', 'langgraph/agentcad_langgraph.py')
af = cargar('agentcad_airflow', 'airflow/agentcad_airflow.py')

class Comun(unittest.TestCase):
    def test_bloque_en_verde_devuelve_salidas(self):
        s = comun.ejecutar_bloque('puerta_pared_min', {'pieza': 'placa_soporte'}); self.assertTrue(s['ok']); self.assertIn('pared_min_mm', s)
    def test_bloque_en_rojo_lanza_con_el_resultado(self):
        with self.assertRaises(comun.PuertaEnRojo) as cm: comun.ejecutar_bloque('puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': 50.0})
        self.assertFalse(cm.exception.resultado['ok'])
    def test_fallar_si_rojo_false_devuelve_el_rojo(self):
        self.assertFalse(comun.ejecutar_bloque('puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': 50.0}, fallar_si_rojo=False)['ok'])
    def test_bloque_inexistente(self):
        with self.assertRaises(Exception): comun.ejecutar_bloque('no_existe', {})
    def test_pipeline_simulado(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p')
        d = comun.ejecutar_pipeline('integrar_variante', dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g']), 'k1', info['raiz'], simulado=True); self.assertEqual(d['estado'], 'ok')
    def test_pipeline_en_fallo_lanza(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p')
        with self.assertRaises(comun.PuertaEnRojo) as cm: comun.ejecutar_pipeline('integrar_variante', dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=1.0), 'k2', info['raiz'], simulado=True)
        self.assertEqual(cm.exception.resultado['fallo'], 'masa')

class Snakemake(unittest.TestCase):
    def setUp(self): self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.out = Path(self.t.name) / 'r' / 'x.json'
    def test_regla_escribe_el_json_de_salida(self):
        s = snk.regla_bloque(self.out, 'puerta_pared_min', {'pieza': 'placa_soporte'}); self.assertEqual(json.loads(self.out.read_text()), s)
    def test_regla_en_rojo_escribe_y_falla(self):
        with self.assertRaises(comun.PuertaEnRojo): snk.regla_bloque(self.out, 'puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': 50.0})
        self.assertFalse(json.loads(self.out.read_text())['ok'])
    def test_error_de_bloque_deja_rastro(self):
        with self.assertRaises(Exception): snk.regla_bloque(self.out, 'no_existe', {})
        self.assertIn('error', json.loads(self.out.read_text()))
    def test_regla_pipeline(self):
        info = sim_fixture.crear(Path(self.t.name) / 'p'); p = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g'])
        d = snk.regla_pipeline(self.out, 'integrar_variante', p, 'sk', info['raiz'], simulado=True); self.assertEqual(json.loads(self.out.read_text())['estado'], 'ok')
    def test_el_snakefile_de_ejemplo_apunta_a_bloques_y_funciones_reales(self):
        from agentcad import bloques
        txt = (INT / 'snakemake' / 'Snakefile').read_text(); B = bloques.cargar()
        for linea in [l.strip() for l in txt.splitlines() if l.strip().startswith('run:')]:
            self.assertIn('agentcad_snakemake.regla_bloque', linea)
            ns = dict(agentcad_snakemake=snk, output=[str(self.out)], wildcards=SimpleNamespace(pieza='placa_soporte')); exec(linea[len('run:'):].strip(), ns)      # ejecuta la línea `run:` con dobles de output/wildcards
            self.assertTrue(self.out.is_file()); self.out.unlink()
        for b in ('puerta_pared_min', 'puerta_interferencia'): self.assertIn(b, B)

class Grafo:
    """Doble mínimo de StateGraph: nodos secuenciales + una arista condicional. Aplica las actualizaciones al estado como hace LangGraph."""
    def __init__(self): self.nodos = {}; self.orden = []; self.cond = None
    def run(self, estado, nodos):
        for n in nodos: estado = {**estado, **self.nodos[n](estado)}
        return estado

class LangGraph(unittest.TestCase):
    def test_nodo_actualiza_el_estado(self):
        nodo = lg.nodo_bloque('puerta_pared_min', {'pieza': ('estado', 'pieza')}); r = nodo({'pieza': 'placa_soporte'})
        self.assertTrue(r['resultados']['puerta_pared_min']['ok']); self.assertEqual(r['rojas'], []); self.assertEqual(nodo.__name__, 'agentcad_puerta_pared_min')
    def test_nodo_en_rojo_no_lanza_registra_roja(self):
        r = lg.nodo_bloque('puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': lambda e: 50.0})({}); self.assertEqual(r['rojas'], ['puerta_pared_min'])
    def test_arista_condicional(self):
        self.assertEqual(lg.arista_si_ok({'rojas': []}), 'ok'); self.assertEqual(lg.arista_si_ok({'rojas': ['x']}), 'rojo'); self.assertEqual(lg.arista_si_ok({}), 'ok')
    def test_grafo_de_dos_nodos_con_doble(self):
        g = Grafo(); g.nodos['a'] = lg.nodo_bloque('puerta_pared_min', {'pieza': 'placa_soporte'}); g.nodos['b'] = lg.nodo_bloque('puerta_interferencia', {'pieza': 'placa_soporte'})
        e = g.run({}, ['a', 'b']); self.assertEqual(set(e['resultados']), {'puerta_pared_min', 'puerta_interferencia'}); self.assertEqual(lg.arista_si_ok(e), 'ok')
    def test_nodo_pipeline(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p')
        r = lg.nodo_pipeline('integrar_variante', dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g']), 'lg', raiz=info['raiz'], simulado=True)({})
        self.assertEqual(r['diario']['estado'], 'ok'); self.assertEqual(r['rojas'], [])
    def test_el_grafo_de_ejemplo_exige_langgraph(self):
        ge = cargar('grafo_ejemplo', 'langgraph/grafo_ejemplo.py')
        if importlib.util.find_spec('langgraph') is None:
            with self.assertRaises(ImportError): ge.construir()
        else: self.skipTest('langgraph está instalado: prueba real fuera de alcance')

class Airflow(unittest.TestCase):
    def test_tarea_devuelve_xcom(self): self.assertTrue(af.ejecutar_bloque_tarea('puerta_pared_min', {'pieza': 'placa_soporte'}, run_id='x')['ok'])
    def test_puerta_en_rojo_falla_la_tarea(self):
        with self.assertRaises(comun.PuertaEnRojo): af.ejecutar_bloque_tarea('puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': 50.0})
    def test_con_airflow_se_usa_airflowfailexception(self):
        class Fallo(Exception): pass
        mods = {'airflow': types.ModuleType('airflow'), 'airflow.exceptions': types.ModuleType('airflow.exceptions')}; mods['airflow.exceptions'].AirflowFailException = Fallo
        sys.modules.update(mods); self.addCleanup(lambda: [sys.modules.pop(k, None) for k in mods])
        with self.assertRaises(Fallo): af.ejecutar_bloque_tarea('puerta_pared_min', {'pieza': 'placa_soporte', 'umbral_mm': 50.0})
    def test_tarea_bloque_crea_un_operador_con_los_kwargs(self):
        creados = []
        class Op:
            def __init__(self, **kw): creados.append(kw)
        m1, m2, m3 = types.ModuleType('airflow'), types.ModuleType('airflow.operators'), types.ModuleType('airflow.operators.python'); m3.PythonOperator = Op
        mods = {'airflow': m1, 'airflow.operators': m2, 'airflow.operators.python': m3}; sys.modules.update(mods); self.addCleanup(lambda: [sys.modules.pop(k, None) for k in mods])
        af.tarea_bloque('dag', 't1', 'puerta_pared_min', {'pieza': 'placa_soporte'}); k = creados[0]
        self.assertEqual((k['task_id'], k['dag'], k['python_callable']), ('t1', 'dag', af.ejecutar_bloque_tarea)); self.assertEqual(k['op_kwargs'], dict(bloque='puerta_pared_min', entradas={'pieza': 'placa_soporte'}))
    def test_pipeline_usa_run_id_como_corrida_y_reanuda(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p')
        p = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g'])
        r = af.ejecutar_pipeline_tarea('integrar_variante', p, raiz=info['raiz'], simulado=True, run_id='manual__2026-10-21T10:00:00+00:00')
        self.assertEqual(r['estado'], 'ok'); self.assertNotIn(':', r['corrida']); self.assertTrue((Path(info['raiz']) / 'build' / 'pipelines' / f"integrar_variante.{r['corrida']}.json").is_file())
    def test_el_dag_de_ejemplo_se_importa_sin_airflow(self):
        sys.path.insert(0, str(INT / 'airflow')); m = cargar('dag_ejemplo', 'airflow/dag_ejemplo.py')
        if importlib.util.find_spec('airflow') is None: self.assertIsNone(m.dag)
if __name__ == '__main__': unittest.main()
