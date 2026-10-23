"""Prueba de contrato del bloque perfilar_pipeline + comportamiento: informe corto desde el diario, rutas, caché, ausencia de diario y uso dentro de un pipeline."""
import json, unittest
from pathlib import Path
from tests.bloques import contrato
from tests.test_perfil import diario, paso, et
from agentcad import bloques, cache, pipeline as pl

def escribir(raiz, d):
    f = pl.ruta_diario(raiz, d['nombre'], d['corrida']); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d)); return f

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'perfilar_pipeline'
    def setUp(self):
        super().setUp()
        if self.mod is not None:
            self.d = diario({'construir': paso('build', 2.0), 'pared': paso('puerta_pared_min', 6.0, pico=800.0, cache_='fallo', etapas=[et('fem_factorizacion', 4.0)]), 'interf': paso('puerta_interferencia', 1.0, cache_='acierto', seg_ahorrados=2.5)}, nombre='pp', corrida='c1')
    def test_diario_inexistente_da_ok_falso_y_motivo_sin_romper_el_contrato(self):
        s = pl.ejecutar_bloque(self.NOMBRE, dict(pipeline='pp', corrida='nada'), self.p.ctx)
        self.assertFalse(s['ok']); self.assertIn('no existe', s['resumen']); self.assertEqual((s['total_s'], s['ruta_json']), (0.0, ''))
    def test_informe_desde_el_diario(self):
        escribir(self.p.raiz, self.d); s = pl.ejecutar_bloque(self.NOMBRE, dict(pipeline='pp', corrida='c1'), self.p.ctx)
        self.assertTrue(s['ok']); self.assertAlmostEqual(s['total_s'], 9.0, places=2); self.assertEqual(s['cuello_paso'], 'pared'); self.assertAlmostEqual(s['cuello_fraccion'], 6 / 9, places=2)
        self.assertEqual(s['rss_pico_mib'], 800.0); self.assertEqual(s['ruta_json'], 'build/perfiles/pp.c1.perfil.json'); self.assertEqual(s['ruta_md'], 'build/perfiles/pp.c1.perfil.md')
        self.assertIn('pared', s['resumen']); self.assertIn('fem_factorizacion', s['resumen'])
        self.assertEqual(json.loads(self.p.leer(s['ruta_json']))['pipeline'], 'pp'); self.assertTrue(self.p.leer(s['ruta_md']).startswith('# Perfil'))
        self.assertLess(len(json.dumps(s)), 1200)                                   # un agente lo lee sin abrir ningún log
    def test_top_se_respeta(self):
        escribir(self.p.raiz, self.d); s = pl.ejecutar_bloque(self.NOMBRE, dict(pipeline='pp', corrida='c1', top=1), self.p.ctx)
        self.assertEqual(len(json.loads(self.p.leer(s['ruta_json']))['etapas']), 1)
    def test_nombres_peligrosos_se_rechazan(self):
        for malo in ('../x', 'a/b', ''):
            with self.assertRaises(Exception): pl.ejecutar_bloque(self.NOMBRE, dict(pipeline=malo, corrida='c1'), self.p.ctx)
        with self.assertRaises(Exception): pl.ejecutar_bloque(self.NOMBRE, dict(pipeline='pp', corrida='../c1'), self.p.ctx)
    def test_cacheable_y_la_clave_sigue_al_diario_y_a_los_ficheros_de_salida(self):
        f = escribir(self.p.raiz, self.d); mod = bloques.cargar()[self.NOMBRE]; self.assertTrue(mod.MANIFIESTO['determinista'])
        e = dict(pipeline='pp', corrida='c1', top=5); k1 = cache.clave(mod, e, self.p.ctx)
        s = pl.ejecutar_bloque(self.NOMBRE, e, self.p.ctx); self.assertEqual(cache.clave(mod, e, self.p.ctx), cache.clave(mod, e, self.p.ctx))
        k2 = cache.clave(mod, e, self.p.ctx); self.assertNotEqual(k1, k2)                 # ya existen los ficheros de salida: la huella lo recoge
        _, estado = cache.con_cache(mod, e, self.p.ctx, lambda: mod.ejecutar(e, self.p.ctx)); self.assertEqual(estado, 'fallo')
        self.assertEqual(cache.con_cache(mod, e, self.p.ctx, lambda: 1 / 0)[1], 'acierto')
        self.p.raiz.joinpath(s['ruta_json']).unlink(); self.assertNotEqual(cache.clave(mod, e, self.p.ctx), k2)           # si se borran las salidas, no sirve el acierto antiguo
        d2 = json.loads(f.read_text()); d2['pasos']['pared']['perfil']['seg'] = 7.0; f.write_text(json.dumps(d2)); self.assertNotEqual(cache.clave(mod, e, self.p.ctx), k2)
    def test_se_puede_usar_como_ultimo_paso_de_un_pipeline_sobre_su_propia_corrida(self):
        from tests.test_pipeline import Falso
        B = bloques.cargar(); f = Falso('fk_t', fn=lambda e, c: (__import__('time').sleep(0.03), {'ok': True})[1]); B['fk_t'] = f; self.addCleanup(B.pop, 'fk_t', None)
        p = dict(esquema='agentcad.pipeline/1', nombre='autoperfil', descripcion='x', parametros={},
                 pasos=[{'id': 'a', 'bloque': 'fk_t'}, {'id': 'b', 'bloque': 'fk_t'}, {'id': 'perfil', 'bloque': 'perfilar_pipeline', 'entradas': {'pipeline': 'autoperfil', 'corrida': '$_corrida'}}])
        self.assertEqual(pl.validar(p), []); d = pl.Ejecutor(p, {}, 'k1', self.p.raiz, simulado=True).correr()
        self.assertEqual(d['estado'], 'ok', d); sal = d['pasos']['perfil']['salidas']; self.assertTrue(sal['ok']); self.assertGreaterEqual(sal['total_s'], 0.05)
        self.assertEqual(json.loads(self.p.leer(sal['ruta_json']))['total']['pasos'], 2)       # cubre los pasos ya terminados; el suyo propio aún corre
if __name__ == '__main__': unittest.main()
