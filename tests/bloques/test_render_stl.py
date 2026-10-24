"""Prueba de contrato del bloque render_stl (sin modo simulado propio: se ejecuta de verdad sobre un STL SINTÉTICO generado en un directorio temporal)
+ comportamiento real: dimensiones del cuadro delimitador, submuestreo, rutas, errores, caché y catálogo."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import trimesh
from PIL import Image
from tests.bloques import contrato
from agentcad import bloques, cache, pipeline as pl
from agentcad.bloques._base import MAX_SALIDA


def _entradas(**kw):
    """Entradas completas con los defaults del MANIFIESTO (como las pone el ejecutor)."""
    m = bloques.cargar()['render_stl'].MANIFIESTO
    return {**{k: v['default'] for k, v in m['entradas'].items() if 'default' in v}, **kw}


def _cubo(ruta):
    trimesh.creation.box(extents=(10, 20, 5)).export(str(ruta))
    return ruta


class Contrato(contrato.ContratoBloque):
    NOMBRE = 'render_stl'

    def entradas_ejemplo(self, proyecto):
        _cubo(proyecto.raiz / 'pieza.stl')
        return dict(archivo='pieza.stl')

    def test_catalogo_lo_lista_cacheable_y_sin_pesado_ni_deshacer(self):
        lineas = bloques.catalogo().splitlines()
        self.assertTrue(any(l.startswith('render_stl [C] ') for l in lineas), bloques.catalogo())


class Real(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.r = Path(self.t.name)
        env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_LOCK_HELD': '1', 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo')})
        env.start(); self.addCleanup(env.stop)
        self.ctx = dict(raiz=str(self.r)); (self.r / 'stl').mkdir()
        self.mod = bloques.cargar()['render_stl']

    def correr(self, archivo, **kw): return pl.ejecutar_bloque('render_stl', dict(archivo=archivo, **kw), self.ctx)

    def test_salida_por_defecto_y_dimensiones_del_cubo(self):
        _cubo(self.r / 'stl' / 'cubo.stl')
        r = self.correr('stl/cubo.stl')
        self.assertTrue(r['ok'])
        self.assertEqual(Path(r['png']), Path('trabajo') / 'render' / 'cubo_stl.png')
        self.assertAlmostEqual(r['dx_mm'], 10.0, places=4); self.assertAlmostEqual(r['dy_mm'], 20.0, places=4); self.assertAlmostEqual(r['dz_mm'], 5.0, places=4)
        self.assertEqual((r['triangulos'], r['dibujados']), (12, 12))
        _png_valido(self, self.r / r['png'], r)

    def test_salida_explicita_y_vistas(self):
        _cubo(self.r / 'stl' / 'c.stl')
        r = self.correr('stl/c.stl', salida='salidas/c.png', vistas='superior,lateral')
        self.assertEqual(Path(r['png']), Path('salidas') / 'c.png')
        _png_valido(self, self.r / r['png'], r)

    def test_max_triangulos_acota_lo_dibujado(self):
        trimesh.creation.icosphere(subdivisions=4).export(str(self.r / 'stl' / 'esf.stl'))
        r = self.correr('stl/esf.stl', max_triangulos=40)
        self.assertEqual(r['triangulos'], 5120)
        self.assertLessEqual(r['dibujados'], 40)
        with self.assertRaises(ValueError): self.correr('stl/esf.stl', max_triangulos=0)

    def test_salida_fuera_de_las_raices_es_error(self):
        _cubo(self.r / 'stl' / 'c.stl'); otra = tempfile.TemporaryDirectory(); self.addCleanup(otra.cleanup)
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'):
            self.correr('stl/c.stl', salida=str(Path(otra.name) / 'x.png'))

    def test_extension_distinta_de_png_es_error(self):
        _cubo(self.r / 'stl' / 'c.stl')
        with self.assertRaisesRegex(ValueError, 'png'):
            self.correr('stl/c.stl', salida='salidas/x.svg')

    def test_archivo_inexistente(self):
        with self.assertRaises(FileNotFoundError): self.correr('stl/no_existe.stl')

    def test_vista_invalida_es_error(self):
        _cubo(self.r / 'stl' / 'c.stl')
        with self.assertRaisesRegex(ValueError, 'superior'): self.correr('stl/c.stl', vistas='oblicua')

    def test_cache_acierto_no_reescribe_el_png(self):
        _cubo(self.r / 'stl' / 'c.stl')
        r1 = self.correr('stl/c.stl'); png = self.r / r1['png']
        os.utime(png, ns=(10 ** 9, 10 ** 9))
        r2 = self.correr('stl/c.stl')
        self.assertEqual(r2, r1); self.assertEqual(png.stat().st_mtime_ns, 10 ** 9)

    def test_si_se_borra_el_png_se_regenera(self):
        _cubo(self.r / 'stl' / 'c.stl')
        r1 = self.correr('stl/c.stl'); png = self.r / r1['png']; png.unlink()
        self.assertTrue(self.correr('stl/c.stl')['ok']); self.assertTrue(png.is_file())

    def test_cambiar_el_stl_cambia_la_clave_de_cache(self):
        ruta = _cubo(self.r / 'stl' / 'c.stl'); e = _entradas(archivo='stl/c.stl')
        k1 = cache.clave(self.mod, e, self.ctx)
        trimesh.creation.box(extents=(3, 3, 3)).export(str(ruta))
        self.assertNotEqual(k1, cache.clave(self.mod, e, self.ctx))
        self.assertAlmostEqual(self.correr('stl/c.stl')['dx_mm'], 3.0, places=4)

    def test_huella_nunca_lanza(self):
        h = self.mod.huella(_entradas(archivo='no_existe.stl'), self.ctx)
        self.assertIsInstance(h, dict); self.assertIn('error', h)

    def test_salida_cabe_en_el_limite_de_bloque(self):
        _cubo(self.r / 'stl' / 'c.stl')
        r = self.correr('stl/c.stl')
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), MAX_SALIDA)


def _png_valido(prueba, ruta, r):
    with Image.open(ruta) as im:
        prueba.assertEqual(im.format, 'PNG'); prueba.assertEqual(im.size, (r['ancho_px'], r['alto_px']))


if __name__ == '__main__': unittest.main()
