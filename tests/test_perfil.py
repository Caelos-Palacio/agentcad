"""Perfilado de pipelines: el ejecutor registra por paso tiempo, CPU, memoria pico, caché y espera de cola en el diario; agentcad/perfil.py construye el informe
(tabla por tiempo, cuellos de botella, % por bloque, caché) en JSON y Markdown pequeños y compara dos corridas; `agentcad perfilar` lo expone por CLI."""
import contextlib, copy, io, json, os, tempfile, time, unittest
from pathlib import Path
from agentcad import bloques, cache, instr, perfil, pipeline as pl
from tests.test_pipeline import Falso, pipe, Base

def paso(bloque, seg, pico=100.0, cache_=None, h='a' * 64, etapas=None, cpu=None, espera=0.0, estado='ok', top=None, **extra):
    p = dict(bloque=bloque, estado=estado, top=top or 'x', entradas={}, salidas={'ok': True}, segundos=seg + espera,
             procedencia=dict(bloque_sha256='b' * 64, entradas_sha256=h, agentcad='0.4.0'),
             perfil=dict(seg=seg + espera, cpu_s=seg if cpu is None else cpu, cpu_hijos_s=0.0, rss_ini_mib=pico - 10, rss_pico_mib=pico, rss_fin_mib=pico - 5, sin_instrumentar_s=0.0, etapas=etapas or [], intentos=1,
                         **({'espera_cola_s': espera} if espera else {}), **extra))
    if cache_: p['cache'] = cache_
    return p

def diario(pasos, nombre='pp', corrida='1', estado='ok', **kw):
    d = dict(nombre=nombre, corrida=corrida, modo='simulado', estado=estado, params={}, pasos={}, diario=[], rollbacks=0, rollback_piezas=[], inicio='2026-10-23T10:00:00')
    for sid, p in pasos.items(): p['top'] = sid; d['pasos'][sid] = p
    d.update(kw); return d

def et(nombre, excl, seg=None, llamadas=1, **tam): return dict(etapa=nombre, llamadas=llamadas, seg=seg or excl, excl_seg=excl, cpu_s=excl, rss_pico_mib=50.0, tam=tam, hijos=0)

class Ejemplo(unittest.TestCase):
    def setUp(self):
        self.d = diario({
            'construir': paso('build', 2.0, pico=300.0),
            'pared': paso('puerta_pared_min', 6.0, pico=800.0, cache_='fallo', h='1' * 64, etapas=[et('fem_factorizacion', 4.0, n_dof=50000), et('fem_ensamblado', 1.0)]),
            'interf': paso('puerta_interferencia', 1.5, pico=200.0, cache_='acierto', h='2' * 64, seg_ahorrados=3.0),
            'imprim': paso('puerta_imprimibilidad', 0.5, pico=150.0, cache_='fallo', espera=2.0, h='3' * 64, etapas=[et('fem_factorizacion', 0.2)]),
        })

class Informe(Ejemplo):
    def test_estructura_y_totales(self):
        p = perfil.construir(self.d)
        self.assertEqual((p['esquema'], p['pipeline'], p['corrida'], p['estado']), ('agentcad.perfil/1', 'pp', '1', 'ok'))
        self.assertAlmostEqual(p['total']['seg'], 10.0, places=3)                 # trabajo = pared menos espera de cola (2 + 6 + 1,5 + 0,5)
        self.assertAlmostEqual(p['total']['espera_cola_s'], 2.0, places=3); self.assertEqual(p['total']['rss_pico_mib'], 800.0); self.assertEqual(p['total']['pasos'], 4)

    def test_tabla_ordenada_por_tiempo_y_porcentajes(self):
        p = perfil.construir(self.d); ids = [x['id'] for x in p['pasos']]
        self.assertEqual(ids, ['pared', 'construir', 'interf', 'imprim'])
        self.assertAlmostEqual(sum(x['pct'] for x in p['pasos']), 100.0, delta=0.3); self.assertAlmostEqual(p['pasos'][0]['pct'], 60.0, delta=0.1)
        self.assertEqual(p['pasos'][0]['entradas_sha256'], '1' * 12); self.assertEqual(p['pasos'][2]['seg_ahorrados'], 3.0)

    def test_por_bloque(self):
        self.d['pasos']['pared2'] = paso('puerta_pared_min', 2.0, top='pared2'); p = perfil.construir(self.d)
        pb = {x['bloque']: x for x in p['por_bloque']}; self.assertEqual(pb['puerta_pared_min']['pasos'], 2); self.assertAlmostEqual(pb['puerta_pared_min']['seg'], 8.0, places=3)
        self.assertEqual(p['por_bloque'][0]['bloque'], 'puerta_pared_min')

    def test_etapas_internas_agregadas_entre_pasos(self):
        p = perfil.construir(self.d); e = {x['etapa']: x for x in p['etapas']}
        self.assertEqual(e['fem_factorizacion']['llamadas'], 2); self.assertAlmostEqual(e['fem_factorizacion']['excl_seg'], 4.2, places=3); self.assertAlmostEqual(e['fem_factorizacion']['pct'], 42.0, delta=0.1)
        self.assertEqual(p['etapas'][0]['etapa'], 'fem_factorizacion')

    def test_cuellos_de_botella(self):
        p = perfil.construir(self.d); c = p['cuellos']
        self.assertEqual((c[0]['tipo'], c[0]['nombre']), ('paso', 'pared')); self.assertIn(('etapa', 'fem_factorizacion'), [(x['tipo'], x['nombre']) for x in c])
        self.assertNotIn('imprim', [x['nombre'] for x in c if x['tipo'] == 'paso'])           # 5 %: no es cuello

    def test_cache(self):
        c = perfil.construir(self.d)['cache']
        self.assertEqual((c['cacheables'], c['aciertos'], c['fallos']), (3, 1, 2)); self.assertAlmostEqual(c['tasa_acierto'], 1 / 3, places=3); self.assertEqual(c['seg_ahorrados'], 3.0)

    def test_sin_cache_declarada(self):
        d = diario({'a': paso('x', 1.0)}); c = perfil.construir(d)['cache']; self.assertEqual((c['cacheables'], c['tasa_acierto']), (0, None))

    def test_resumen_corto(self):
        r = perfil.construir(self.d)['resumen']; self.assertLessEqual(len(r), 600)
        for s in ('pp#1', 'pared', 'fem_factorizacion', '800', 'caché'): self.assertIn(s, r)

    def test_omitidos_y_sin_perfil_no_rompen(self):
        d = copy.deepcopy(self.d); d['pasos']['salt'] = dict(bloque='x', estado='omitido', top='salt', salidas={})
        d['pasos']['viejo'] = dict(bloque='y', estado='ok', top='viejo', salidas={}, segundos=1.0)             # diario de 0.3.0: solo `segundos`
        p = perfil.construir(d); ids = {x['id']: x for x in p['pasos']}
        self.assertNotIn('salt', ids); self.assertAlmostEqual(ids['viejo']['seg'], 1.0); self.assertIsNone(ids['viejo']['rss_pico_mib'])
        self.assertTrue(any('sin perfil de memoria' in n for n in p['notas']))

    def test_pasos_de_bucle_se_agrupan_por_bloque(self):
        d = diario({f'h[{i}]': paso('puerta_masa', 0.5, top='l') for i in range(4)}); p = perfil.construir(d)
        self.assertEqual(len(p['pasos']), 4); self.assertEqual(p['por_bloque'][0]['pasos'], 4)

    def test_pasos_descartados_por_rollback_y_reintentos(self):
        d = diario({'a': paso('x', 1.0, seg_reintentos=0.7)}, perfil_corrida=dict(descartado_seg=3.0, descartados=2, seg_correr=5.0)); p = perfil.construir(d)
        self.assertEqual(p['total']['descartado_seg'], 3.0); self.assertTrue(any('rollback' in n for n in p['notas'])); self.assertTrue(any('reintentos' in n for n in p['notas']))

    def test_corrida_en_curso_se_avisa(self):
        d = diario({'a': paso('x', 1.0), 'b': dict(bloque='y', estado='corriendo', top='b')}, estado='corriendo'); p = perfil.construir(d)
        self.assertEqual(p['estado'], 'corriendo'); self.assertTrue(any('en curso' in n for n in p['notas'])); self.assertEqual([x['id'] for x in p['pasos']], ['a'])

    def test_fallo_y_corrida_vacia(self):
        p = perfil.construir(diario({}, estado='nuevo')); self.assertEqual(p['total']['pasos'], 0); self.assertEqual(p['cuellos'], []); json.dumps(p)

    def test_json_serializable_y_pequeno(self):
        s = json.dumps(perfil.construir(self.d)); self.assertLess(len(s), 6000)

    def test_top_limita_etapas_y_cuellos(self):
        d = diario({'a': paso('x', 3.0, etapas=[et(f'e{i}', 1.0 - i * 0.05) for i in range(10)])}); self.assertEqual(len(perfil.construir(d, top=3)['etapas']), 3)

class Texto(Ejemplo):
    def test_texto_corto_con_tabla_cuellos_y_cache(self):
        t = perfil.formato_texto(perfil.construir(self.d))
        self.assertLessEqual(len(t.splitlines()), 30)
        lineas = t.splitlines(); i_pared = next(i for i, l in enumerate(lineas) if l.lstrip().startswith('pared')); i_const = next(i for i, l in enumerate(lineas) if l.lstrip().startswith('construir'))
        self.assertLess(i_pared, i_const)                                                  # ordenado por tiempo
        for s in ('puerta_pared_min', 'fem_factorizacion', 'caché', 'cuello'): self.assertIn(s, t)
    def test_markdown_pequeno(self):
        m = perfil.formato_md(perfil.construir(self.d)); self.assertTrue(m.startswith('# Perfil')); self.assertIn('| paso |', m); self.assertLess(len(m), 4000)

class Generar(Ejemplo):
    def setUp(self):
        super().setUp(); self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.raiz = Path(self.t.name)
        r = pl.ruta_diario(self.raiz, 'pp', '1'); r.parent.mkdir(parents=True); r.write_text(json.dumps(self.d))
    def test_escribe_json_y_md_por_ruta(self):
        p, rutas = perfil.generar(self.raiz, 'pp', '1')
        self.assertEqual(rutas['json'], 'build/perfiles/pp.1.perfil.json'); self.assertEqual(rutas['md'], 'build/perfiles/pp.1.perfil.md')
        self.assertEqual(json.loads((self.raiz / rutas['json']).read_text())['pipeline'], 'pp'); self.assertTrue((self.raiz / rutas['md']).read_text().startswith('# Perfil'))
    def test_diario_inexistente(self):
        with self.assertRaises(perfil.PerfilError) as c: perfil.generar(self.raiz, 'pp', 'no')
        self.assertIn('no existe', str(c.exception))
    def test_idempotente(self):
        a = perfil.generar(self.raiz, 'pp', '1')[0]; b = perfil.generar(self.raiz, 'pp', '1')[0]; a.pop('generado', None); b.pop('generado', None); self.assertEqual(a, b)

class Comparar(unittest.TestCase):
    def setUp(self):
        self.a = diario({'construir': paso('build', 2.0), 'pared': paso('puerta_pared_min', 10.0, pico=900.0, cache_='fallo', h='1' * 64, etapas=[et('fem_factorizacion', 8.0)]),
                         'interf': paso('puerta_interferencia', 1.0, h='2' * 64), 'viejo': paso('informe', 0.2)}, corrida='r1')
        self.b = diario({'construir': paso('build', 2.02), 'pared': paso('puerta_pared_min', 5.5, pico=600.0, cache_='fallo', h='1' * 64, etapas=[et('fem_factorizacion', 4.0)]),
                         'interf': paso('puerta_interferencia', 3.0, h='9' * 64), 'nuevo': paso('puerta_masa', 0.1)}, corrida='r2')
    def test_deltas_por_paso_y_veredicto(self):
        c = perfil.comparar(perfil.construir(self.a), perfil.construir(self.b)); por = {x['id']: x for x in c['pasos']}
        self.assertEqual(por['pared']['veredicto'], 'mas_rapido'); self.assertAlmostEqual(por['pared']['delta_seg'], -4.5, places=3); self.assertAlmostEqual(por['pared']['delta_pct'], -45.0, delta=0.1)
        self.assertEqual(por['construir']['veredicto'], 'sin_cambio')                      # 20 ms (1 %) es ruido
        self.assertEqual(por['interf']['veredicto'], 'mas_lento'); self.assertEqual(por['nuevo']['veredicto'], 'nuevo'); self.assertEqual(por['viejo']['veredicto'], 'desaparecido')
        self.assertEqual(c['pasos'][0]['id'], 'interf' if abs(por['interf']['delta_seg']) > abs(por['pared']['delta_seg']) else 'pared')   # ordenados por |delta|

    def test_causa_probable(self):
        c = perfil.comparar(perfil.construir(self.a), perfil.construir(self.b)); por = {x['id']: x for x in c['pasos']}
        self.assertEqual(por['pared']['entradas'], 'iguales'); self.assertEqual(por['interf']['entradas'], 'distintas'); self.assertIn('entradas distintas', por['interf']['causa'])
        self.assertIn('mismas entradas', por['pared']['causa'])

    def test_bloque_modificado_y_cambio_de_cache(self):
        self.b['pasos']['pared']['procedencia']['bloque_sha256'] = 'c' * 64; self.b['pasos']['pared']['cache'] = 'acierto'
        c = perfil.comparar(perfil.construir(self.a), perfil.construir(self.b)); por = {x['id']: x for x in c['pasos']}
        self.assertIn('bloque modificado', por['pared']['causa']); self.assertIn('caché', por['pared']['causa']); self.assertEqual(por['pared']['cache'], 'fallo->acierto')

    def test_totales_y_etapas(self):
        c = perfil.comparar(perfil.construir(self.a), perfil.construir(self.b))
        self.assertAlmostEqual(c['total']['delta_seg'], (2.02 + 5.5 + 3.0 + 0.1) - (2.0 + 10.0 + 1.0 + 0.2), places=3)
        e = {x['etapa']: x for x in c['etapas']}; self.assertAlmostEqual(e['fem_factorizacion']['delta_pct'], -50.0, delta=0.1)
        self.assertEqual(c['pasos'][0]['id'] in ('interf', 'pared'), True)

    def test_texto_y_md(self):
        c = perfil.comparar(perfil.construir(self.a), perfil.construir(self.b)); t = perfil.formato_texto_comparacion(c)
        for s in ('r1', 'r2', 'pared', '-45', 'mas_rapido', 'fem_factorizacion'): self.assertIn(s, t)
        self.assertLessEqual(len(t.splitlines()), 30); self.assertIn('| paso |', perfil.formato_md_comparacion(c)); json.dumps(c)

    def test_pipelines_distintos_se_avisan(self):
        b = copy.deepcopy(self.b); b['nombre'] = 'otro'; c = perfil.comparar(perfil.construir(self.a), perfil.construir(b)); self.assertTrue(any('pipelines distintos' in n for n in c['notas']))

    def test_generar_comparacion_escribe_archivos(self):
        with tempfile.TemporaryDirectory() as t:
            for d in (self.a, self.b): r = pl.ruta_diario(t, 'pp', d['corrida']); r.parent.mkdir(parents=True, exist_ok=True); r.write_text(json.dumps(d))
            c, rutas = perfil.generar_comparacion(t, 'pp', 'r1', 'r2')
            self.assertEqual(rutas['json'], 'build/perfiles/pp.r1_vs_r2.comparacion.json'); self.assertTrue((Path(t) / rutas['md']).is_file())

class EjecutorRegistraPerfil(Base):
    def test_cada_paso_lleva_perfil_con_tiempo_memoria_y_hash(self):
        def lento(e, c):
            with instr.etapa('trabajo_interno', n=5): time.sleep(0.05)
            return {'ok': True}
        self.inyectar(Falso('fk_p', fn=lento)); instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        d = self.ejecutor(pipe([{'id': 'p', 'bloque': 'fk_p'}])).correr(); st = d['pasos']['p']; pf = st['perfil']
        self.assertGreaterEqual(pf['seg'], 0.05); self.assertGreater(pf['rss_pico_mib'], 0); self.assertIn('cpu_s', pf); self.assertEqual(pf['intentos'], 1)
        self.assertEqual(pf['etapas'][0]['etapa'], 'trabajo_interno'); self.assertEqual(pf['etapas'][0]['tam'], {'n': 5})
        self.assertEqual(len(st['procedencia']['entradas_sha256']), 64); self.assertIn('segundos', st)       # la clave histórica sigue
        self.assertGreater(d['perfil_corrida']['seg_correr'], 0.05)

    def test_desactivada_el_diario_queda_como_en_0_3_0(self):
        self.inyectar(Falso('fk_p')); instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=False)
        d = self.ejecutor(pipe([{'id': 'p', 'bloque': 'fk_p'}])).correr(); self.assertNotIn('perfil', d['pasos']['p']); self.assertNotIn('perfil_corrida', d); self.assertIn('segundos', d['pasos']['p'])

    def test_toml_del_proyecto_desactiva(self):
        self.inyectar(Falso('fk_p')); instr.restablecer(); self.addCleanup(instr.restablecer)
        (self.raiz / 'agentcad.toml').write_text('[instrumentacion]\nactiva = false\n')
        d = self.ejecutor(pipe([{'id': 'p', 'bloque': 'fk_p'}])).correr(); self.assertNotIn('perfil', d['pasos']['p'])

    def test_cache_acierto_registra_segundos_ahorrados(self):
        f = self.inyectar(Falso('fk_c', {'x': {'type': 'integer'}}, fn=lambda e, c: (time.sleep(0.06), {'ok': True})[1])); f.MANIFIESTO['determinista'] = True
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        p = pipe([{'id': 'c', 'bloque': 'fk_c', 'entradas': {'x': 1}}])
        d1 = self.ejecutor(p, corrida='a').correr(); d2 = self.ejecutor(p, corrida='b').correr()
        self.assertEqual((d1['pasos']['c']['cache'], d2['pasos']['c']['cache']), ('fallo', 'acierto'))
        self.assertGreaterEqual(d2['pasos']['c']['perfil']['seg_ahorrados'], 0.05); self.assertLess(d2['pasos']['c']['perfil']['seg'], 0.05)
        self.assertEqual(d1['pasos']['c']['procedencia']['entradas_sha256'], d2['pasos']['c']['procedencia']['entradas_sha256'])
        self.assertNotIn('seg_ahorrados', d1['pasos']['c']['perfil'])

    def test_reintentos_se_acumulan(self):
        n = []; self.inyectar(Falso('fk_r', fn=lambda e, c: (time.sleep(0.03), {'ok': bool(n.append(1)) or len(n) >= 2})[1]))
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        d = self.ejecutor(pipe([{'id': 'r', 'bloque': 'fk_r', 'en_fallo': 'reintentar'}])).correr(); pf = d['pasos']['r']['perfil']
        self.assertEqual(pf['intentos'], 2); self.assertGreaterEqual(pf['seg_reintentos'], 0.03)

    def test_espera_de_cola_se_separa_del_trabajo(self):
        import fcntl, threading
        from unittest import mock
        self.inyectar(Falso('fk_h', pesado=True, fn=lambda e, c: (time.sleep(0.02), {'ok': True})[1]))
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        lock = self.raiz / 'cola.lock'
        with mock.patch.dict(os.environ, {'AGENTCAD_LOCK': str(lock), 'AGENTCAD_PROYECTO': str(self.raiz), 'AGENTCAD_PERMITIR_REAL': '1'}):
            os.environ.pop('AGENTCAD_LOCK_HELD', None)
            fd = os.open(lock, os.O_RDWR | os.O_CREAT); fcntl.flock(fd, fcntl.LOCK_EX)
            threading.Timer(0.25, lambda: (fcntl.flock(fd, fcntl.LOCK_UN), os.close(fd))).start()
            d = self.ejecutor(pipe([{'id': 'h', 'bloque': 'fk_h'}]), simulado=False).correr()
        pf = d['pasos']['h']['perfil']; self.assertEqual(d['estado'], 'ok', d)
        self.assertGreaterEqual(pf['espera_cola_s'], 0.2); self.assertLess(pf['seg'] - pf['espera_cola_s'], 0.2)

    def test_para_cada_y_omitidos(self):
        self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}})); instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        d = self.ejecutor(pipe([{'id': 'l', 'para_cada': ['p', 'q'], 'como': 'x', 'pasos': [{'id': 'h', 'bloque': 'fk_b', 'entradas': {'ruta': '$x'}}]},
                                {'id': 'o', 'bloque': 'fk_b', 'entradas': {'ruta': 'z'}, 'si': False}])).correr()
        self.assertIn('perfil', d['pasos']['h[p]']); self.assertIn('perfil', d['pasos']['h[q]']); self.assertNotIn('perfil', d['pasos']['o'])

    def test_rollback_descarta_pasos_y_los_cuenta(self):
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        estado = {'n': 0}
        def cambia(e, c): time.sleep(0.04); return {'ok': True}
        def puerta(e, c): time.sleep(0.04); estado['n'] += 1; return {'ok': estado['n'] > 1}
        self.inyectar(Falso('fk_cambia', fn=cambia, deshacer=lambda e, c: {'ok': True})); self.inyectar(Falso('fk_puerta', fn=puerta))
        p = pipe([{'id': 'cambia', 'bloque': 'fk_cambia'}, {'id': 'puerta', 'bloque': 'fk_puerta', 'en_fallo': {'accion': 'rollback', 'paso': 'cambia', 'repetir_desde': 'cambia'}}])
        d = self.ejecutor(p).correr(); self.assertEqual(d['estado'], 'ok'); self.assertEqual(d['rollbacks'], 1)
        self.assertGreaterEqual(d['perfil_corrida']['descartado_seg'], 0.04); self.assertGreaterEqual(d['perfil_corrida']['descartados'], 1)

class Cli(unittest.TestCase):
    def run_cli(self, *a):
        from agentcad.__main__ import main
        o, e = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): rc = main(list(a))
        return rc, o.getvalue(), e.getvalue()
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.raiz = Path(self.t.name)
        E = Ejemplo(); E.setUp()
        for c in ('r1', 'r2'):
            d = copy.deepcopy(E.d); d['corrida'] = c; d['nombre'] = 'pp'
            if c == 'r2': d['pasos']['pared']['perfil']['seg'] = 3.0
            r = pl.ruta_diario(self.raiz, 'pp', c); r.parent.mkdir(parents=True, exist_ok=True); r.write_text(json.dumps(d))
        self.pipeline_json = self.raiz / 'pp.json'; self.pipeline_json.write_text(json.dumps(pipe([{'id': 'a', 'bloque': 'puerta_masa', 'entradas': {'base_g': 1}}], nombre='pp')))
    def test_perfilar_imprime_tabla_corta_y_rutas(self):
        rc, o, _ = self.run_cli('perfilar', str(self.pipeline_json), 'r1', '--raiz', str(self.raiz)); self.assertEqual(rc, 0, o)
        self.assertIn('puerta_pared_min', o); self.assertIn('build/perfiles/pp.r1.perfil.json', o); self.assertIn('build/perfiles/pp.r1.perfil.md', o); self.assertLessEqual(len(o.splitlines()), 34)
        self.assertTrue((self.raiz / 'build/perfiles/pp.r1.perfil.json').is_file())
    def test_perfilar_json(self):
        rc, o, _ = self.run_cli('perfilar', str(self.pipeline_json), 'r1', '--raiz', str(self.raiz), '--json'); d = json.loads(o)
        self.assertEqual((rc, d['ruta_json'], d['cuello']['nombre']), (0, 'build/perfiles/pp.r1.perfil.json', 'pared')); self.assertIn('resumen', d); self.assertLess(len(o), 1500)
    def test_perfilar_corrida_inexistente(self):
        rc, _, e = self.run_cli('perfilar', str(self.pipeline_json), 'nada', '--raiz', str(self.raiz)); self.assertEqual(rc, 2); self.assertIn('no existe', e)
    def test_comparar(self):
        rc, o, _ = self.run_cli('perfilar', str(self.pipeline_json), '--comparar', 'r1', 'r2', '--raiz', str(self.raiz)); self.assertEqual(rc, 0, o)
        self.assertIn('mas_rapido', o); self.assertIn('pp.r1_vs_r2.comparacion.json', o); self.assertTrue((self.raiz / 'build/perfiles/pp.r1_vs_r2.comparacion.md').is_file())
    def test_comparar_con_forma_nombre_corrida(self):
        rc, o, _ = self.run_cli('perfilar', '--comparar', 'pp:r1', 'pp:r2', '--raiz', str(self.raiz)); self.assertEqual(rc, 0, o); self.assertIn('mas_rapido', o)
    def test_uso_incorrecto(self):
        rc, _, e = self.run_cli('perfilar', '--raiz', str(self.raiz)); self.assertEqual(rc, 2)

if __name__ == '__main__': unittest.main()
