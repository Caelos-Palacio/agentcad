"""Pruebas del EJECUTOR de pipelines (TDD): validación/dry-run con tipos, semántica de pasos (si, para_cada, en_fallo), checkpoints, reanudación,
rollback por pieza, cola pesada (flock), contrato de salidas, modo real protegido y segundo plano. Bloques falsos para la mecánica; integrar_variante sobre copia simulada."""
import copy, fcntl, json, os, tempfile, time, unittest
from pathlib import Path
from agentcad import bloques, pipeline as pl, sim_fixture
from agentcad.bloques import _base

class Falso:
    """Bloque falso inyectable en el registro (no pasa por disco)."""
    def __init__(self, nombre, entradas=None, salidas=None, fn=None, pesado=False, deshacer=None):
        self.MANIFIESTO = dict(nombre=nombre, descripcion='falso para pruebas', entradas=entradas or {}, salidas=salidas or {'ok': {'type': 'boolean'}}, precondiciones=[], efectos=[],
                               pesado=pesado, deshacible=deshacer is not None, honestidad='prueba')
        self.llamadas = []; self._fn = fn or (lambda e, ctx: {'ok': True})
        if deshacer: self.deshacer = deshacer
    def ejecutar(self, e, ctx): self.llamadas.append(dict(e)); return self._fn(e, ctx)

def pipe(pasos, parametros=None, nombre='prueba'):
    return dict(esquema='agentcad.pipeline/1', nombre=nombre, descripcion='x', parametros=parametros or {}, pasos=pasos)

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.raiz = Path(self.tmp.name)
        self.B = bloques.cargar(); self._inyectados = []
    def inyectar(self, f):
        self.B[f.MANIFIESTO['nombre']] = f; self._inyectados.append(f.MANIFIESTO['nombre']); self.addCleanup(self.B.pop, f.MANIFIESTO['nombre'], None); return f
    def ejecutor(self, p, params=None, corrida='c1', **kw): return pl.Ejecutor(p, params or {}, corrida, self.raiz, **kw)

class Validacion(Base):
    def setUp(self):
        super().setUp(); self.inyectar(Falso('fk_a', {'x': {'type': 'integer'}, 'm': {'type': 'string', 'default': 'u'}}, {'ok': {'type': 'boolean'}, 'n': {'type': 'integer'}, 'ruta': {'type': 'string'}}))
        self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}}, {'ok': {'type': 'boolean'}}))
        self.inyectar(Falso('fk_nodesh', {}, {'ok': {'type': 'boolean'}}))
    def errs(self, pasos, params=None, parametros=None): return pl.validar(pipe(pasos, parametros), params)
    def test_pipeline_valido(self):
        self.assertEqual(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}, {'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.ruta'}}]), [])
    def test_bloque_desconocido(self): self.assertIn('bloque desconocido', ' '.join(self.errs([{'id': 'a', 'bloque': 'nada'}])))
    def test_entrada_requerida_ausente(self): self.assertIn('falta la entrada x', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_a'}])))
    def test_entrada_desconocida(self): self.assertIn('entrada desconocida zz', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1, 'zz': 2}}])))
    def test_literal_de_tipo_incorrecto(self): self.assertIn('a.x', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 'texto'}}])))
    def test_tipo_de_referencia_no_encaja(self):
        e = ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}, {'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.n'}}]))   # integer -> string
        self.assertIn('no encaja', e)
    def test_referencia_a_salida_inexistente(self):
        self.assertIn('referencia desconocida', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}, {'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.zzz'}}])))
    def test_referencia_hacia_adelante_es_error(self):          # DAG: solo hacia atrás
        self.assertIn('desconocida o posterior', ' '.join(self.errs([{'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.ruta'}}, {'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}])))
    def test_id_duplicado(self): self.assertIn('id duplicado', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}}, {'id': 'a', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}}])))
    def test_despues_hacia_adelante(self): self.assertIn('despues', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}, 'despues': ['z']}])))
    def test_parametros_tipados(self):
        par = {'n': {'type': 'integer'}}; paso = [{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': '$n'}}]
        self.assertEqual(self.errs(paso, {'n': 3}, par), []); self.assertIn('parámetro n', ' '.join(self.errs(paso, {'n': 'tres'}, par)))
        self.assertIn('requerido sin valor', ' '.join(self.errs(paso, {}, par))); self.assertIn('parámetro desconocido', ' '.join(self.errs(paso, {'n': 1, 'otro': 2}, par)))
    def test_parametro_con_defecto_no_es_requerido(self): self.assertEqual(self.errs([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}], {}, {'k': {'type': 'integer', 'default': 1}}), [])
    def test_para_cada_exige_lista(self):
        par = {'s': {'type': 'string'}}; b = [{'id': 'l', 'para_cada': '$s', 'como': 'p', 'pasos': [{'id': 'a', 'bloque': 'fk_b', 'entradas': {'ruta': '$p'}}]}]
        self.assertIn('espera una lista', ' '.join(self.errs(b, parametros=par)))
        par = {'s': {'type': 'array'}}; self.assertEqual(self.errs(b, parametros=par), [])
    def test_salidas_internas_del_bucle_no_son_visibles_fuera(self):
        b = [{'id': 'l', 'para_cada': ['u'], 'como': 'p', 'pasos': [{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 1}}]}, {'id': 'z', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.ruta'}}]
        self.assertIn('desconocida', ' '.join(self.errs(b)))
    def test_rollback_exige_bloque_deshacible(self):
        b = [{'id': 'n', 'bloque': 'fk_nodesh'}, {'id': 'c', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}, 'en_fallo': {'accion': 'rollback', 'paso': 'n', 'repetir_desde': 'n'}}]
        self.assertIn('no es deshacible', ' '.join(self.errs(b)))
    def test_rollback_sobre_paso_posterior(self):
        self.inyectar(Falso('fk_d', {}, {'ok': {'type': 'boolean'}}, deshacer=lambda e, c: {}))
        b = [{'id': 'c', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}, 'en_fallo': {'accion': 'rollback', 'paso': 'd', 'repetir_desde': 'c'}}, {'id': 'd', 'bloque': 'fk_d'}]
        self.assertIn('inexistente o posterior', ' '.join(self.errs(b)))
    def test_esquema_rechaza_campos_desconocidos(self):
        p = pipe([{'id': 'a', 'bloque': 'fk_b', 'entradas': {'ruta': 'r'}, 'raro': 1}]); self.assertTrue(pl.validar(p))
    def test_bloque_borrador_rechazado(self):
        f = self.inyectar(Falso('fk_bor')); f.MANIFIESTO['estado'] = 'borrador'; self.assertIn('borrador', ' '.join(self.errs([{'id': 'a', 'bloque': 'fk_bor'}])))
    def test_integrar_variante_valida_contra_los_bloques_reales(self):
        p = pl.cargar_pipeline('integrar_variante'); self.assertEqual(pl.validar(p, dict(etiqueta='v2', etiqueta_anterior='v1', config='c.json', base_g=600.0)), [])
    def test_integrar_variante_detecta_tipo_erroneo_de_parametro(self):
        p = pl.cargar_pipeline('integrar_variante'); self.assertTrue(pl.validar(p, dict(etiqueta='v2', etiqueta_anterior='v1', config='c.json', base_g='mucho')))

class Mecanica(Base):
    def test_orden_y_salidas_por_referencia(self):
        a = self.inyectar(Falso('fk_a', {'x': {'type': 'integer'}}, {'ok': {'type': 'boolean'}, 'ruta': {'type': 'string'}}, lambda e, c: {'ok': True, 'ruta': f"/r/{e['x']}.stl"}))
        b = self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}}))
        d = self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a', 'entradas': {'x': 7}}, {'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.ruta'}}])).correr()
        self.assertEqual(d['estado'], 'ok'); self.assertEqual(b.llamadas, [{'ruta': '/r/7.stl'}])
    def test_defectos_de_manifiesto_aplicados(self):
        a = self.inyectar(Falso('fk_a', {'m': {'type': 'string', 'default': 'u'}})); self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a'}])).correr(); self.assertEqual(a.llamadas, [{'m': 'u'}])
    def test_si_falso_omite_el_paso(self):
        a = self.inyectar(Falso('fk_a')); d = self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a', 'si': '$activo'}], {'activo': {'type': 'boolean'}}), {'activo': False}).correr()
        self.assertEqual(a.llamadas, []); self.assertEqual(d['pasos']['a']['estado'], 'omitido')
    def test_si_con_operadores(self):
        a = self.inyectar(Falso('fk_a')); par = {'u': {'type': 'integer'}, 'v': {'type': 'boolean'}}
        self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a', 'si': {'y': [{'igual': ['$u', 3]}, {'no': '$v'}]}}], par), {'u': 3, 'v': False}).correr(); self.assertEqual(len(a.llamadas), 1)
        self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a', 'si': {'o': [{'menor': ['$u', 3]}, '$v']}}], par), {'u': 5, 'v': False}, corrida='c2').correr(); self.assertEqual(len(a.llamadas), 1)
    def test_para_cada_itera_y_registra_ids_con_el_elemento(self):
        a = self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}})); par = {'l': {'type': 'array'}}
        d = self.ejecutor(pipe([{'id': 'l1', 'para_cada': '$l', 'como': 'x', 'pasos': [{'id': 'h', 'bloque': 'fk_b', 'entradas': {'ruta': '$x'}}]}], par), {'l': ['p', 'q']}).correr()
        self.assertEqual([c['ruta'] for c in a.llamadas], ['p', 'q']); self.assertIn('h[q]', d['pasos'])
    def test_abortar_por_defecto(self):
        f = self.inyectar(Falso('fk_f', fn=lambda e, c: {'ok': False})); g = self.inyectar(Falso('fk_g'))
        d = self.ejecutor(pipe([{'id': 'f', 'bloque': 'fk_f'}, {'id': 'g', 'bloque': 'fk_g'}])).correr()
        self.assertEqual((d['estado'], d['fallo']), ('fallo', 'f')); self.assertEqual(g.llamadas, [])
    def test_saltar_continua(self):
        self.inyectar(Falso('fk_f', fn=lambda e, c: {'ok': False})); g = self.inyectar(Falso('fk_g'))
        d = self.ejecutor(pipe([{'id': 'f', 'bloque': 'fk_f', 'en_fallo': 'saltar'}, {'id': 'g', 'bloque': 'fk_g'}])).correr()
        self.assertEqual(d['estado'], 'ok'); self.assertEqual(d['pasos']['f']['estado'], 'saltado'); self.assertEqual(len(g.llamadas), 1)
    def test_reintentar_se_recupera(self):
        n = []; self.inyectar(Falso('fk_r', fn=lambda e, c: {'ok': bool(n.append(1)) or len(n) >= 2}))
        d = self.ejecutor(pipe([{'id': 'r', 'bloque': 'fk_r', 'en_fallo': 'reintentar'}])).correr(); self.assertEqual(d['estado'], 'ok'); self.assertEqual(len(n), 2)
    def test_reintentar_con_maximo(self):
        n = []; self.inyectar(Falso('fk_r', fn=lambda e, c: {'ok': bool(n.append(1)) and False}))
        d = self.ejecutor(pipe([{'id': 'r', 'bloque': 'fk_r', 'en_fallo': {'accion': 'reintentar', 'max': 2}}])).correr(); self.assertEqual(d['estado'], 'fallo'); self.assertEqual(len(n), 3)
    def test_excepcion_del_bloque_es_fallo_con_mensaje(self):
        def boom(e, c): raise RuntimeError('rompe')
        self.inyectar(Falso('fk_x', fn=boom)); d = self.ejecutor(pipe([{'id': 'x', 'bloque': 'fk_x'}])).correr()
        self.assertEqual(d['estado'], 'fallo'); self.assertIn('rompe', d['pasos']['x']['salidas']['error'])
    def test_referencia_sin_resolver_en_ejecucion_es_fallo_no_cuelgue(self):
        self.inyectar(Falso('fk_a', {'m': {'type': 'string'}}, {'ok': {'type': 'boolean'}, 'ruta': {'type': 'string'}}))
        d = self.ejecutor(pipe([{'id': 'o', 'bloque': 'fk_a', 'entradas': {'m': 'x'}, 'si': False}, {'id': 'z', 'bloque': 'fk_a', 'entradas': {'m': '$o.ruta'}}])).correr()
        self.assertEqual(d['estado'], 'fallo')
    def test_salida_no_declarada_rompe_el_contrato(self):
        self.inyectar(Falso('fk_x', fn=lambda e, c: {'ok': True, 'extra': 1})); d = self.ejecutor(pipe([{'id': 'x', 'bloque': 'fk_x'}])).correr()
        self.assertEqual(d['estado'], 'fallo'); self.assertIn('no declaradas', d['pasos']['x']['salidas']['error'])
    def test_salida_de_tipo_incorrecto(self):
        self.inyectar(Falso('fk_x', salidas={'ok': {'type': 'boolean'}, 'n': {'type': 'integer'}}, fn=lambda e, c: {'ok': True, 'n': 'no'})); self.assertEqual(self.ejecutor(pipe([{'id': 'x', 'bloque': 'fk_x'}])).correr()['estado'], 'fallo')
    def test_datos_pesados_por_referencia_no_por_contenido(self):
        self.inyectar(Falso('fk_x', salidas={'ok': {'type': 'boolean'}, 'datos': {'type': 'string'}}, fn=lambda e, c: {'ok': True, 'datos': 'x' * 10000}))
        d = self.ejecutor(pipe([{'id': 'x', 'bloque': 'fk_x'}])).correr(); self.assertEqual(d['estado'], 'fallo'); self.assertIn('por referencia', d['pasos']['x']['salidas']['error'])
    def test_checkpoint_en_disco_tras_cada_paso(self):
        self.inyectar(Falso('fk_a')); ex = self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a'}])); ex.correr()
        d = json.loads(ex.ruta.read_text()); self.assertEqual(d['estado'], 'ok'); self.assertEqual(d['pasos']['a']['estado'], 'ok'); self.assertTrue(d['diario'])
        self.assertFalse(ex.ruta.with_suffix('.tmp').exists())

class Reanudar(Base):
    def test_reanuda_desde_el_ultimo_paso_correcto_sin_repetir(self):
        cuenta = {'a': 0, 'b': 0, 'c': 0}; estado = {'corta': True}
        def mk(k, corta=False):
            def fn(e, c):
                cuenta[k] += 1
                if corta and estado['corta']: raise KeyboardInterrupt('corte simulado')       # no es Exception: el ejecutor NO lo captura (como un kill)
                return {'ok': True}
            return fn
        for k in 'abc': self.inyectar(Falso(f'fk_{k}', fn=mk(k, k == 'b')))
        p = pipe([{'id': k, 'bloque': f'fk_{k}'} for k in 'abc'])
        with self.assertRaises(KeyboardInterrupt): self.ejecutor(p).correr()
        d = json.loads((self.raiz / 'build/pipelines/prueba.c1.json').read_text()); self.assertEqual(d['pasos']['a']['estado'], 'ok'); self.assertEqual(d['pasos']['b']['estado'], 'corriendo')
        estado['corta'] = False; d = self.ejecutor(p).correr()
        self.assertEqual(d['estado'], 'ok'); self.assertEqual(cuenta, {'a': 1, 'b': 2, 'c': 1})            # a no se repite; b se reintenta tras el corte
    def test_las_salidas_de_pasos_hechos_se_restauran_al_reanudar(self):
        self.inyectar(Falso('fk_a', {}, {'ok': {'type': 'boolean'}, 'ruta': {'type': 'string'}}, lambda e, c: {'ok': True, 'ruta': 'r1'})); fallar = {'s': True}
        def fb(e, c):
            if fallar['s']: return {'ok': False}
            return {'ok': True}
        b = self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}}, fn=fb)); p = pipe([{'id': 'a', 'bloque': 'fk_a'}, {'id': 'b', 'bloque': 'fk_b', 'entradas': {'ruta': '$a.ruta'}}])
        self.assertEqual(self.ejecutor(p).correr()['estado'], 'fallo'); fallar['s'] = False; self.assertEqual(self.ejecutor(p).correr()['estado'], 'ok'); self.assertEqual(b.llamadas[-1], {'ruta': 'r1'})
    def test_bucle_reanuda_en_el_elemento_pendiente(self):
        vistos = []; fallar = {'q': True}
        def fn(e, c):
            vistos.append(e['ruta'])
            return {'ok': not (e['ruta'] == 'q' and fallar['q'])}
        self.inyectar(Falso('fk_b', {'ruta': {'type': 'string'}}, fn=fn)); par = {'l': {'type': 'array'}}
        p = pipe([{'id': 'l1', 'para_cada': '$l', 'como': 'x', 'pasos': [{'id': 'h', 'bloque': 'fk_b', 'entradas': {'ruta': '$x'}}]}], par)
        self.assertEqual(self.ejecutor(p, {'l': ['p', 'q', 'r']}).correr()['estado'], 'fallo'); fallar['q'] = False
        self.assertEqual(self.ejecutor(p, {'l': ['p', 'q', 'r']}).correr()['estado'], 'ok'); self.assertEqual(vistos, ['p', 'q', 'q', 'r'])
    def test_corrida_distinta_no_reutiliza_checkpoints(self):
        a = self.inyectar(Falso('fk_a')); p = pipe([{'id': 'a', 'bloque': 'fk_a'}]); self.ejecutor(p, corrida='u').correr(); self.ejecutor(p, corrida='v').correr(); self.assertEqual(len(a.llamadas), 2)
    def test_no_mezcla_modos_en_la_misma_corrida(self):
        self.inyectar(Falso('fk_a')); p = pipe([{'id': 'a', 'bloque': 'fk_a'}]); self.ejecutor(p).correr()
        with self.assertRaises(pl.PipelineError): self.ejecutor(p, simulado=False)
    def test_estado_detecta_interrupcion(self):
        self.inyectar(Falso('fk_a', fn=lambda e, c: (_ for _ in ()).throw(KeyboardInterrupt()))); p = pipe([{'id': 'a', 'bloque': 'fk_a'}])
        with self.assertRaises(KeyboardInterrupt): self.ejecutor(p).correr()
        dp = self.raiz / 'build/pipelines/prueba.c1.json'; d = json.loads(dp.read_text()); d['pid'] = 2 ** 22 + 12345; dp.write_text(json.dumps(d))     # pid inexistente
        self.assertEqual(pl.estado(self.raiz, 'prueba', 'c1')['estado'], 'interrumpido'); self.assertEqual(pl.estado(self.raiz, 'prueba', 'zzz')['estado'], 'inexistente')

class Rollback(Base):
    """Rollback por elemento: el elemento que falla se deshace y se repite desde un paso anterior con el resto."""
    def montar(self, malos=('q',)):
        self.activos = ['p', 'q', 'r']; self.build = []; malos = set(malos)
        def aplicar(e, c): return {'ok': True, 'activos': list(self.activos)}
        def deshacer(e, c):
            if e['pieza'] in self.activos: self.activos.remove(e['pieza'])
            return {'activos': list(self.activos)}
        self.inyectar(Falso('fk_apl', {}, {'ok': {'type': 'boolean'}, 'activos': {'type': 'array'}}, aplicar, deshacer=deshacer))
        self.inyectar(Falso('fk_bld', fn=lambda e, c: (self.build.append(list(self.activos)) or {'ok': True})))
        self.gate = self.inyectar(Falso('fk_gate', {'pieza': {'type': 'string'}}, fn=lambda e, c: {'ok': e['pieza'] not in malos}))
        rb = {'accion': 'rollback', 'paso': 'apl', 'entradas': {'pieza': '$x'}, 'repetir_desde': 'bld', 'max': 3}
        return pipe([{'id': 'apl', 'bloque': 'fk_apl'}, {'id': 'bld', 'bloque': 'fk_bld'},
                     {'id': 'lp', 'para_cada': '$apl.activos', 'como': 'x', 'pasos': [{'id': 'g', 'bloque': 'fk_gate', 'entradas': {'pieza': '$x'}, 'en_fallo': rb}]}])
    def test_revierte_la_pieza_que_falla_y_reintenta_con_el_resto(self):
        d = self.ejecutor(self.montar()).correr()
        self.assertEqual(d['estado'], 'ok'); self.assertEqual(self.activos, ['p', 'r']); self.assertEqual(self.build, [['p', 'q', 'r'], ['p', 'r']])
        self.assertEqual([x['pieza'] for x in d['rollback_piezas']], ['q']); self.assertEqual(d['rollbacks'], 1)
        self.assertIn('g[r]', d['pasos']); self.assertNotIn('g[q]', d['pasos'])           # los checkpoints posteriores al rollback se descartan; q ya no se evalúa
    def test_rollback_de_varias_piezas(self):
        d = self.ejecutor(self.montar(('p', 'r'))).correr(); self.assertEqual(d['estado'], 'ok'); self.assertEqual(self.activos, ['q']); self.assertEqual(d['rollbacks'], 2)
    def test_se_detiene_al_agotar_el_maximo(self):
        p = self.montar(('p', 'q', 'r')); p['pasos'][2]['pasos'][0]['en_fallo']['max'] = 2
        d = self.ejecutor(p).correr(); self.assertEqual(d['estado'], 'fallo'); self.assertEqual(d['rollbacks'], 2)
    def test_el_diario_distingue_el_rollback(self):
        d = self.ejecutor(self.montar()).correr(); self.assertTrue(any('ROLLBACK' in l for l in d['diario']))
    def test_reanuda_tras_corte_despues_del_rollback(self):
        p = self.montar(); n = {'cortar': True}; orig = self.B['fk_bld']
        def bld(e, c):
            self.build.append(list(self.activos))
            if len(self.build) == 2 and n['cortar']: raise KeyboardInterrupt()
            return {'ok': True}
        orig._fn = bld
        with self.assertRaises(KeyboardInterrupt): self.ejecutor(p).correr()
        n['cortar'] = False; d = self.ejecutor(p).correr()
        self.assertEqual(d['estado'], 'ok'); self.assertEqual(self.activos, ['p', 'r']); self.assertEqual([x['pieza'] for x in d['rollback_piezas']], ['q'])

class Cola(Base):
    def setUp(self):
        super().setUp(); self.lock = str(self.raiz / 'test.lock'); self._old = {k: os.environ.get(k) for k in ('AGENTCAD_LOCK', 'AGENTCAD_LOCK_HELD')}
        os.environ['AGENTCAD_LOCK'] = self.lock; os.environ.pop('AGENTCAD_LOCK_HELD', None)
        def restaurar():
            for k, v in self._old.items(): os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.addCleanup(restaurar)
    def test_bloque_pesado_toma_el_flock_y_lo_libera(self):
        vistos = []
        def fn(e, c):
            vistos.append(os.environ.get('AGENTCAD_LOCK_HELD')); fd = os.open(self.lock, os.O_RDWR)
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); vistos.append('libre')
            except BlockingIOError: vistos.append('tomado')
            finally: os.close(fd)
            return {'ok': True}
        h = self.inyectar(Falso('fk_h', fn=fn, pesado=True)); ex = self.ejecutor(pipe([{'id': 'h', 'bloque': 'fk_h'}]), simulado=False)
        ex._llamar(h, {}); self.assertEqual(vistos, ['1', 'tomado']); self.assertIsNone(os.environ.get('AGENTCAD_LOCK_HELD'))
        fd = os.open(self.lock, os.O_RDWR); fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); os.close(fd)                       # libre tras la llamada
    def test_cola_ocupada_falla_con_mensaje(self):
        h = self.inyectar(Falso('fk_h', pesado=True)); fd = os.open(self.lock, os.O_RDWR | os.O_CREAT); fcntl.flock(fd, fcntl.LOCK_EX); self.addCleanup(os.close, fd)
        ex = self.ejecutor(pipe([{'id': 'h', 'bloque': 'fk_h'}]), simulado=False, espera_cola=0.3)
        with self.assertRaisesRegex(TimeoutError, 'cola_ocupada'): ex._llamar(h, {})
    def test_bloque_ligero_no_toma_la_cola(self):
        l = self.inyectar(Falso('fk_l')); fd = os.open(self.lock, os.O_RDWR | os.O_CREAT); fcntl.flock(fd, fcntl.LOCK_EX); self.addCleanup(os.close, fd)
        self.ejecutor(pipe([{'id': 'l', 'bloque': 'fk_l'}]), simulado=False, espera_cola=0.2)._llamar(l, {}); self.assertEqual(len(l.llamadas), 1)
    def test_simulado_no_ocupa_la_cola(self):
        h = self.inyectar(Falso('fk_h', pesado=True)); fd = os.open(self.lock, os.O_RDWR | os.O_CREAT); fcntl.flock(fd, fcntl.LOCK_EX); self.addCleanup(os.close, fd)
        d = self.ejecutor(pipe([{'id': 'h', 'bloque': 'fk_h'}]), espera_cola=0.2).correr(); self.assertEqual(d['estado'], 'ok')
    def test_cola_reentrante_con_lock_held(self):
        os.environ['AGENTCAD_LOCK_HELD'] = '1'
        with _base.cola(0.1) as tomada: self.assertFalse(tomada)
    def test_el_modo_real_exige_autorizacion_explicita(self):
        self.inyectar(Falso('fk_a')); os.environ.pop('AGENTCAD_PERMITIR_REAL', None)
        with self.assertRaisesRegex(pl.PipelineError, 'no autorizado'): self.ejecutor(pipe([{'id': 'a', 'bloque': 'fk_a'}]), simulado=False).correr()

class IntegrarVariante(unittest.TestCase):
    """integrar_variante completo en MODO SIMULADO sobre una copia temporal (jamás sobre el proyecto real)."""
    def setUp(self):
        from tests import EJEMPLO
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.real = (EJEMPLO / 'params.scad').read_bytes()
        self.addCleanup(lambda: self.assertEqual((EJEMPLO / 'params.scad').read_bytes(), self.real, 'el pipeline tocó params.scad REAL'))
    def montar(self, fallos=None, corrida='t'):
        self.info = sim_fixture.crear(Path(self.t.name) / 'p', fallos=fallos) if not hasattr(self, 'info') else self.info
        self.raiz = Path(self.info['raiz']); self.params = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=self.info['base_g'])
        return pl.Ejecutor(pl.cargar_pipeline('integrar_variante'), self.params, corrida, self.raiz, True)
    def flags(self): return {p: _base.flag_activo((self.raiz / 'params.scad').read_text(), v[0]) for p, v in sim_fixture.PIEZAS.items()}
    def test_todo_correcto(self):
        d = self.montar().correr(); self.assertEqual(d['estado'], 'ok', d.get('fallo')); self.assertEqual(self.flags(), dict(placa=True, soporte=True, tapa=True)); self.assertEqual(d['rollbacks'], 0)
        t = (self.raiz / 'build/INFORME_v2.md').read_text(); self.assertIn('MODO SIMULADO', t)
        self.assertIn('placa', t.split('## Incumplimientos conocidos')[1].split('##')[0])             # incumplimiento conocido marcado, no oculto
    def test_fallo_a_proposito_revierte_solo_esa_pieza(self):
        d = self.montar({'soporte': {'pared_min_mm': 0.9}}).correr()      # 0,9 mm < 1,2 mm
        self.assertEqual(d['estado'], 'ok', d.get('fallo')); self.assertEqual(self.flags(), dict(placa=True, soporte=False, tapa=True))
        self.assertEqual([x['pieza'] for x in d['rollback_piezas']], ['soporte']); self.assertNotIn('pared[soporte]', d['pasos'])
        self.assertEqual(sum('construir (build)' in l and 'ok' in l for l in d['diario']), 2)                # construyó dos veces: antes y después del rollback
        t = (self.raiz / 'build/INFORME_v2.md').read_text(); self.assertIn('soporte', t.split('## Piezas revertidas')[1].split('##')[0]); self.assertIn('placa', t)
        self.assertEqual(d['pasos']['masa']['salidas']['masa_g'], 625 - 40 - 22)                              # soporte vuelve a su masa base
    def test_fallo_de_cada_puerta_provoca_rollback(self):
        for campo, valor in (('pared_min_mm', 1.0), ('interferencia_mm3', 3.0), ('imprimibilidad_nuevos_fallos', ['islas'])):
            with self.subTest(campo):
                self.__dict__.pop('info', None); self.t.cleanup(); self.t = tempfile.TemporaryDirectory(); d = self.montar({'tapa': {campo: valor}}).correr()
                self.assertEqual(d['estado'], 'ok'); self.assertEqual([x['pieza'] for x in d['rollback_piezas']], ['tapa']); self.assertFalse(self.flags()['tapa'])
    def test_peor_margen_fem_revierte(self):
        self.montar(); cfg = json.loads((self.raiz / 'config.json').read_text()); cfg['piezas']['tapa']['fem']['cand'] = 1.0; (self.raiz / 'config.json').write_text(json.dumps(cfg))
        d = pl.Ejecutor(pl.cargar_pipeline('integrar_variante'), self.params, 'f', self.raiz, True).correr(); self.assertEqual([x['pieza'] for x in d['rollback_piezas']], ['tapa'])
    def test_masa_mayor_que_la_base_aborta(self):
        ex = self.montar(); ex.d['params']['base_g'] = 500.0; ex.vars['base_g'] = 500.0; d = ex.correr(); self.assertEqual((d['estado'], d['fallo']), ('fallo', 'masa'))
        self.assertNotIn('informe', d['pasos'])                         # no se escribe el informe final tras una puerta global en rojo
    def test_reanuda_integrar_variante_tras_corte_en_la_puerta_de_masa(self):
        from agentcad.bloques import puerta_masa
        ex = self.montar(corrida='z'); orig = puerta_masa.ejecutar; cuenta = {'n': 0}
        def corta(e, c):
            cuenta['n'] += 1
            if cuenta['n'] == 1: raise KeyboardInterrupt()
            return orig(e, c)
        puerta_masa.ejecutar = corta; self.addCleanup(setattr, puerta_masa, 'ejecutar', orig)
        with self.assertRaises(KeyboardInterrupt): ex.correr()
        from agentcad.bloques import build
        llamadas = []; ob = build.simular; build.simular = lambda e, c: (llamadas.append(1), ob(e, c))[1]; self.addCleanup(setattr, build, 'simular', ob)
        d = self.montar(corrida='z').correr(); self.assertEqual(d['estado'], 'ok'); self.assertEqual(llamadas, [])      # no reconstruye: reanuda en la puerta de masa
        self.assertTrue((self.raiz / 'build/INFORME_v2.md').is_file())
    def test_real_nunca_sobre_la_copia(self):
        ex = self.montar(); ex.simulado = False
        with self.assertRaises(pl.PipelineError): ex.correr()

class Fondo(unittest.TestCase):
    def test_segundo_plano_con_estado_consultable(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p'); params = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g'])
        pid = pl.lanzar_fondo('integrar_variante', params, 'bg', True, info['raiz']); self.assertGreater(pid, 0)
        for _ in range(120):
            s = pl.estado(info['raiz'], 'integrar_variante', 'bg')
            if s['estado'] in ('ok', 'fallo'): break
            time.sleep(0.25)
        self.assertEqual(s['estado'], 'ok', s); self.assertEqual(s['modo'], 'simulado')
class Cli(unittest.TestCase):
    def run_cli(self, *a):
        import io, contextlib
        from agentcad.__main__ import main
        o = io.StringIO(); e = io.StringIO()
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e): rc = main(list(a))
        return rc, o.getvalue(), e.getvalue()
    def test_catalogo_una_linea_por_bloque(self):
        rc, o, _ = self.run_cli('catalogo'); lineas = [l for l in o.splitlines() if not l.startswith('#')]
        self.assertEqual(rc, 0); self.assertEqual(len(lineas), len(bloques.cargar()))
    def test_ayuda_y_bloque_desconocido(self):
        self.assertEqual(self.run_cli('ayuda', 'puerta_masa')[0], 0); rc, _, e = self.run_cli('ayuda', 'nada'); self.assertEqual(rc, 2); self.assertIn('desconocido', e)
    def test_validar_pipeline(self):
        p = json.dumps(dict(etiqueta='v2', etiqueta_anterior='v1', config='c.json', base_g=600)); self.assertEqual(self.run_cli('validar', 'integrar_variante', '--params', p)[0], 0)
        rc, o, _ = self.run_cli('validar', 'integrar_variante', '--params', '{"etiqueta": 3}'); self.assertEqual(rc, 1); self.assertIn('etiqueta', o)
    def test_ejecutar_primer_plano_y_estado(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); info = sim_fixture.crear(Path(t.name) / 'p'); p = json.dumps(dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g']))
        rc, o, _ = self.run_cli('ejecutar', 'integrar_variante', '--params', p, '--corrida', 'cli', '--raiz', info['raiz'], '--simulado', '--primer-plano'); self.assertEqual(rc, 0, o)
        rc, o, _ = self.run_cli('estado', 'integrar_variante', 'cli', '--raiz', info['raiz']); self.assertEqual(rc, 0); self.assertIn('ok', o)
    def test_real_sin_autorizacion_se_rechaza(self):
        os.environ.pop('AGENTCAD_PERMITIR_REAL', None); p = json.dumps(dict(etiqueta='v2', etiqueta_anterior='v1', config='c.json', base_g=600))
        rc, _, e = self.run_cli('ejecutar', 'integrar_variante', '--params', p, '--corrida', 'r', '--real', '--primer-plano'); self.assertEqual(rc, 1); self.assertIn('no autorizado', e)
if __name__ == '__main__': unittest.main()
