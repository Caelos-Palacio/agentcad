"""Caché por hash de entradas para bloques deterministas (idea de Snakemake/DVC, reimplementada): mismas entradas + mismo código + misma huella de ficheros = mismo resultado, sin repetir."""
import json, os, shutil, tempfile, unittest
from pathlib import Path
from unittest import mock
from agentcad import bloques, cache, pipeline as pl
from tests import EJEMPLO
from tests.test_pipeline import Falso, Base, pipe

def falso(nombre, det=True, huella=None, **kw):
    f = Falso(nombre, entradas={'x': {'type': 'integer'}}, salidas={'ok': {'type': 'boolean'}, 'n': {'type': 'integer'}}, fn=lambda e, c: {'ok': True, 'n': e['x'] * 2}, **kw)
    if det: f.MANIFIESTO['determinista'] = True
    if huella: f.huella = huella
    return f

class Mecanica(Base):
    def correr(self, corrida, x=3, **kw):
        p = pipe([{'id': 'a', 'bloque': 'fk_det', 'entradas': {'x': x}}]); return pl.Ejecutor(p, {}, corrida, self.raiz, True, **kw).correr()
    def setUp(self):
        super().setUp(); self.f = self.inyectar(falso('fk_det'))
        self._env = os.environ.pop('AGENTCAD_SIN_CACHE', None); self.addCleanup(lambda: os.environ.__setitem__('AGENTCAD_SIN_CACHE', self._env) if self._env else None)
    def test_determinista_no_se_repite_con_las_mismas_entradas(self):
        d1 = self.correr('c1'); d2 = self.correr('c2')
        self.assertEqual(len(self.f.llamadas), 1); self.assertEqual(d1['pasos']['a'].get('cache'), 'fallo'); self.assertEqual(d2['pasos']['a'].get('cache'), 'acierto')
        self.assertEqual(d2['pasos']['a']['salidas'], d1['pasos']['a']['salidas'])
    def test_entradas_distintas_no_aciertan(self):
        self.correr('c1', x=3); self.correr('c2', x=4); self.assertEqual(len(self.f.llamadas), 2)
    def test_no_determinista_nunca_usa_cache(self):
        g = self.inyectar(falso('fk_nodet', det=False)); p = pipe([{'id': 'a', 'bloque': 'fk_nodet', 'entradas': {'x': 1}}])
        for c in ('c1', 'c2'): d = pl.Ejecutor(p, {}, c, self.raiz, True).correr()
        self.assertEqual(len(g.llamadas), 2); self.assertNotIn('cache', d['pasos']['a'])
    def test_huella_de_ficheros_invalida_la_cache(self):
        fich = self.raiz / 'dato.txt'; fich.write_text('uno')
        self.inyectar(falso('fk_huella', huella=lambda e, ctx: {'dato': fich.read_text()})); g = self.B['fk_huella']; p = pipe([{'id': 'a', 'bloque': 'fk_huella', 'entradas': {'x': 1}}])
        pl.Ejecutor(p, {}, 'c1', self.raiz, True).correr(); pl.Ejecutor(p, {}, 'c2', self.raiz, True).correr(); self.assertEqual(len(g.llamadas), 1)
        fich.write_text('dos'); pl.Ejecutor(p, {}, 'c3', self.raiz, True).correr(); self.assertEqual(len(g.llamadas), 2)
    def test_codigo_distinto_invalida_la_cache(self):
        k1 = cache.clave(self.f, {'x': 1}, dict(raiz=str(self.raiz), simulado=True)); self.f.MANIFIESTO['descripcion'] = 'otra descripcion distinta'
        self.assertNotEqual(k1, cache.clave(self.f, {'x': 1}, dict(raiz=str(self.raiz), simulado=True)))
    def test_modo_real_y_simulado_no_comparten_entradas(self):
        c = dict(raiz=str(self.raiz), simulado=True); self.assertNotEqual(cache.clave(self.f, {'x': 1}, c), cache.clave(self.f, {'x': 1}, dict(c, simulado=False)))
    def test_sin_cache_por_entorno(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_SIN_CACHE': '1'}): self.correr('c1'); d = self.correr('c2')
        self.assertEqual(len(self.f.llamadas), 2); self.assertNotIn('cache', d['pasos']['a'])
    def test_un_fallo_con_excepcion_no_se_cachea(self):
        def mal(e, c): raise RuntimeError('boom')
        g = self.inyectar(Falso('fk_mal', entradas={'x': {'type': 'integer'}}, fn=mal)); g.MANIFIESTO['determinista'] = True; p = pipe([{'id': 'a', 'bloque': 'fk_mal', 'entradas': {'x': 1}}])
        for c in ('c1', 'c2'): pl.Ejecutor(p, {}, c, self.raiz, True).correr()
        self.assertEqual(len(g.llamadas), 2)
    def test_un_resultado_ok_false_si_se_cachea(self):
        g = self.inyectar(Falso('fk_rojo', entradas={'x': {'type': 'integer'}}, fn=lambda e, c: {'ok': False})); g.MANIFIESTO['determinista'] = True
        p = pipe([{'id': 'a', 'bloque': 'fk_rojo', 'entradas': {'x': 1}, 'en_fallo': 'saltar'}])
        for c in ('c1', 'c2'): pl.Ejecutor(p, {}, c, self.raiz, True).correr()
        self.assertEqual(len(g.llamadas), 1)
    def test_ejecutar_bloque_tambien_usa_cache(self):
        ctx = dict(raiz=str(self.raiz), simulado=True); self.B['fk_det']
        pl.ejecutar_bloque('fk_det', {'x': 5}, ctx); pl.ejecutar_bloque('fk_det', {'x': 5}, ctx); self.assertEqual(len(self.f.llamadas), 1)
    def test_limpiar(self):
        self.correr('c1'); self.assertTrue(list((self.raiz / 'build' / 'cache').rglob('*.json'))); cache.limpiar(self.raiz); self.assertFalse(list((self.raiz / 'build' / 'cache').rglob('*.json')))
    def test_la_entrada_en_cache_guarda_clave_entradas_y_huella(self):
        self.correr('c1'); f = next((self.raiz / 'build' / 'cache' / 'fk_det').glob('*.json')); d = json.loads(f.read_text())
        self.assertEqual(d['bloque'], 'fk_det'); self.assertEqual(d['entradas'], {'x': 3}); self.assertIn('clave', d); self.assertIn('huella', d)

class BloquesReales(unittest.TestCase):
    """puerta_pared_min sobre una copia del ejemplo: acierta la segunda vez y se invalida si cambia el STL."""
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.raiz = Path(self.t.name) / 'ej'
        shutil.copytree(EJEMPLO, self.raiz, ignore=shutil.ignore_patterns('registro', 'trabajo', 'build', '__pycache__'))
        p = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.raiz), 'AGENTCAD_LOCK_HELD': '1'}); p.start(); self.addCleanup(p.stop)
        os.environ.pop('AGENTCAD_SIN_CACHE', None); self.ctx = dict(raiz=str(self.raiz), simulado=False)
    def n_cache(self): return len(list((self.raiz / 'build' / 'cache' / 'puerta_pared_min').glob('*.json')))
    def test_acierto_y_invalidacion_por_stl(self):
        a = pl.ejecutar_bloque('puerta_pared_min', dict(pieza='placa_soporte'), self.ctx); self.assertEqual(self.n_cache(), 1)
        with mock.patch('agentcad.printability.check_printability', side_effect=AssertionError('no debía recalcular')):
            b = pl.ejecutar_bloque('puerta_pared_min', dict(pieza='placa_soporte'), self.ctx)
        self.assertEqual(a, b)
        shutil.copy(self.raiz / 'stl_base' / 'placa_soporte.stl', self.raiz / 'stl' / 'placa_soporte.stl')      # otro STL: otra clave
        pl.ejecutar_bloque('puerta_pared_min', dict(pieza='placa_soporte'), self.ctx); self.assertEqual(self.n_cache(), 2)
    def test_huella_incluye_el_toml(self):
        b = bloques.cargar()['puerta_pared_min']; k1 = cache.clave(b, dict(pieza='placa_soporte'), self.ctx)
        t = self.raiz / 'agentcad.toml'; t.write_text(t.read_text() + '\n# cambio\n'); self.assertNotEqual(k1, cache.clave(b, dict(pieza='placa_soporte'), self.ctx))
    def test_los_bloques_con_geometria_son_deterministas(self):
        B = bloques.cargar()
        for n in ('puerta_pared_min', 'puerta_imprimibilidad', 'puerta_interferencia', 'puerta_margen_fem'): self.assertTrue(B[n].MANIFIESTO.get('determinista'), n); self.assertTrue(hasattr(B[n], 'huella'), n)
        for n in ('build', 'backup', 'aplicar_params', 'informe'): self.assertFalse(B[n].MANIFIESTO.get('determinista'), n)
    def test_interferencia_cambia_la_clave_si_cambia_un_vecino(self):
        b = bloques.cargar()['puerta_interferencia']; k1 = cache.clave(b, dict(pieza='placa_soporte'), self.ctx)
        v = self.raiz / 'stl' / 'bloque_vecino.stl'; v.write_bytes(v.read_bytes() + b'\0'); self.assertNotEqual(k1, cache.clave(b, dict(pieza='placa_soporte'), self.ctx))
if __name__ == '__main__': unittest.main()
