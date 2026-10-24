"""Prueba de contrato del bloque render_gcode (sin modo simulado propio: se ejecuta de verdad sobre un gcode SINTÉTICO en un directorio temporal)
+ comportamiento real: rutas de salida, errores, caché por contenido, gcode sin segmentos y el ejemplo del proyecto."""
import importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from PIL import Image
from tests.bloques import contrato
from agentcad import bloques, cache, pipeline as pl
from agentcad.bloques._base import MAX_SALIDA

GCODE = """G90
M83
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X0 Y0 F9000
G1 X10 Y0 E0.5
G1 X10 Y10 E0.5
;TYPE:Sparse infill
G1 X0 Y10 E0.3
"""
GCODE_MAS = GCODE + "G1 X0 Y0 E0.3\n"
GCODE_SIN_SEGMENTOS = "G90\nM83\n;TYPE:Outer wall\nG1 X10 Y0\nG1 Z0.4\n"
RAIZ_EJEMPLO = Path(__file__).resolve().parents[2] / 'ejemplos' / 'soporte_simple'


def _entradas(**kw):
    """Entradas completas con los defaults del MANIFIESTO (como las pone el ejecutor)."""
    m = bloques.cargar()['render_gcode'].MANIFIESTO
    return {**{k: v['default'] for k, v in m['entradas'].items() if 'default' in v}, **kw}


class Contrato(contrato.ContratoBloque):
    NOMBRE = 'render_gcode'

    def entradas_ejemplo(self, proyecto):
        (proyecto.raiz / 'g.gcode').write_text(GCODE, encoding='utf-8')
        return dict(archivo='g.gcode')

    def test_catalogo_lo_lista_cacheable_y_sin_pesado_ni_deshacer(self):
        lineas = bloques.catalogo().splitlines()
        self.assertTrue(any(l.startswith('render_gcode [C] ') for l in lineas), bloques.catalogo())


class Real(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.r = Path(self.t.name)
        env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_LOCK_HELD': '1', 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo')})
        env.start(); self.addCleanup(env.stop)
        self.ctx = dict(raiz=str(self.r)); (self.r / 'gcode').mkdir()
        self.mod = bloques.cargar()['render_gcode']

    def escribir(self, nombre, texto):
        (self.r / 'gcode' / nombre).write_text(texto, encoding='utf-8'); return f'gcode/{nombre}'

    def correr(self, archivo, **kw): return pl.ejecutar_bloque('render_gcode', dict(archivo=archivo, **kw), self.ctx)

    def test_salida_por_defecto_en_trabajo_render(self):
        r = self.correr(self.escribir('a.gcode', GCODE))
        self.assertTrue(r['ok'], r['mensaje'])
        self.assertEqual(Path(r['png']), Path('trabajo') / 'render' / 'a_gcode.png')
        _png_valido(self, self.r / r['png'], r)

    def test_salida_explicita(self):
        r = self.correr(self.escribir('b.gcode', GCODE), salida='salidas/mi_dibujo.png')
        self.assertEqual(Path(r['png']), Path('salidas') / 'mi_dibujo.png')
        self.assertTrue((self.r / 'salidas' / 'mi_dibujo.png').is_file())

    def test_salida_fuera_de_las_raices_es_error(self):
        otra = tempfile.TemporaryDirectory(); self.addCleanup(otra.cleanup)
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'):
            self.correr(self.escribir('c.gcode', GCODE), salida=str(Path(otra.name) / 'x.png'))

    def test_extension_distinta_de_png_es_error(self):
        with self.assertRaisesRegex(ValueError, 'png'):
            self.correr(self.escribir('d.gcode', GCODE), salida='salidas/x.jpg')

    def test_archivo_inexistente(self):
        with self.assertRaises(FileNotFoundError): self.correr('gcode/no_existe.gcode')

    def test_vistas_invalidas_se_rechazan_antes_de_leer(self):
        with self.assertRaisesRegex(ValueError, 'superior'):
            self.correr('gcode/no_existe.gcode', vistas='frontal')

    def test_submuestreo_y_maximo_de_segmentos(self):
        a = self.escribir('e.gcode', GCODE_MAS)
        with self.assertRaises(ValueError): self.correr(a, submuestreo=0)
        with self.assertRaises(ValueError): self.correr(a, max_segmentos=999)
        r = self.correr(a, submuestreo=3)
        self.assertGreaterEqual(r['submuestreo'], 3)

    def test_gcode_grande_queda_acotado(self):
        lineas = ['G90', 'M83', ';TYPE:Outer wall', ';LAYER_CHANGE', ';Z:0.2'] + [f'G1 X{i + 1} Y0 E0.01' for i in range(3000)]
        r = self.correr(self.escribir('grande.gcode', '\n'.join(lineas) + '\n'), max_segmentos=1000)
        self.assertTrue(r['ok']); self.assertEqual(r['segmentos'], 3000)
        self.assertLessEqual(r['dibujados'], 2 * 1000); self.assertGreaterEqual(r['submuestreo'], 2)

    def test_cache_acierto_no_reescribe_el_png(self):
        a = self.escribir('f.gcode', GCODE); r1 = self.correr(a)
        png = self.r / r1['png']; os.utime(png, ns=(10 ** 9, 10 ** 9))
        r2 = self.correr(a)
        self.assertEqual(r2, r1)
        self.assertEqual(png.stat().st_mtime_ns, 10 ** 9)               # el acierto de caché no vuelve a dibujar

    def test_si_se_borra_el_png_se_regenera(self):
        a = self.escribir('g.gcode', GCODE); r1 = self.correr(a)
        png = self.r / r1['png']; png.unlink()
        r2 = self.correr(a)
        self.assertTrue(r2['ok']); self.assertTrue(png.is_file())

    def test_cambiar_el_gcode_cambia_la_clave_de_cache(self):
        a = self.escribir('h.gcode', GCODE)
        e = _entradas(archivo=a)
        k1 = cache.clave(self.mod, e, self.ctx)
        self.escribir('h.gcode', GCODE_MAS)
        k2 = cache.clave(self.mod, e, self.ctx)
        self.assertNotEqual(k1, k2)
        self.assertEqual(self.correr(a)['segmentos'], 4)

    def test_gcode_sin_segmentos_es_ok_falso_sin_png(self):
        r = self.correr(self.escribir('vacio.gcode', GCODE_SIN_SEGMENTOS))
        self.assertFalse(r['ok']); self.assertTrue(r['mensaje']); self.assertEqual(r['png'], '')
        self.assertEqual(r['segmentos'], 0)
        self.assertFalse((self.r / 'trabajo' / 'render' / 'vacio_gcode.png').exists())

    def test_huella_nunca_lanza(self):
        h = self.mod.huella(_entradas(archivo='no_existe.gcode'), self.ctx)
        self.assertIsInstance(h, dict); self.assertIn('error', h)

    def test_ejemplo_del_proyecto_tiene_muro_y_relleno(self):
        spec = importlib.util.spec_from_file_location('generar_gcode_ej', RAIZ_EJEMPLO / 'generar_gcode.py')
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        r = self.correr(self.escribir('ejemplo.gcode', m.generar()))
        self.assertTrue(r['ok'], r['mensaje'])
        self.assertIn('Outer wall', r['tipos']); self.assertIn('Sparse infill', r['tipos'])
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False).encode()), MAX_SALIDA)


def _png_valido(prueba, ruta, r):
    with Image.open(ruta) as im:
        prueba.assertEqual(im.format, 'PNG'); prueba.assertEqual(im.size, (r['ancho_px'], r['alto_px']))


if __name__ == '__main__': unittest.main()
