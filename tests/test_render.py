"""Pruebas del núcleo de dibujo agentcad/render.py: colores por tipo de extrusión, lectura en STREAMING de gcode (segmentos y submuestreo acotado),
dibujo de gcode y de STL. Todo es SINTÉTICO, generado en el propio test: ninguna prueba toca una impresora, un laminador ni un proyecto real."""
import os, tempfile, unittest
from pathlib import Path
import numpy as np
import trimesh
from PIL import Image
from agentcad import render


def _escribir(directorio, nombre, texto):
    ruta = Path(directorio) / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding='utf-8')
    return ruta


def _comprobar_png(prueba, ruta, r):
    """El fichero es un PNG real y su tamaño coincide con el devuelto por el dibujo."""
    with Image.open(ruta) as im:
        prueba.assertEqual(im.format, 'PNG')
        prueba.assertEqual(im.size, (r['ancho_px'], r['alto_px']))
    prueba.assertGreater(os.path.getsize(ruta), 0)


# gcode estilo Orca: ;LAYER_CHANGE, ;Z:, ;TYPE:, G1 con E relativa (M83)
ORCA = """G90
M83
;LAYER_CHANGE
;Z:0.2
;HEIGHT:0.2
;TYPE:Outer wall
G1 X10 Y10 F9000
G1 X20 Y10 E0.5 F1800
G1 X20 Y20 E0.5
;TYPE:Sparse infill
G1 X10 Y20 E0.3
;LAYER_CHANGE
;Z:0.4
;HEIGHT:0.2
;TYPE:Outer wall
G1 X10 Y10 E0.4
"""

# gcode con E ABSOLUTA (M82) y G92 E que reinicia el extrusor
M82 = """G90
M82
G92 E0
G1 X0 Y0 E0
G1 X10 Y0 E1.0
G92 E0
G1 X20 Y0 E0.5
G1 X30 Y0 E0.3
G1 X40 Y0 E0.8
"""

# desplazamientos sin extrusión (travel) y retracciones (E negativa): no son segmentos
TRAYECTO = """G90
M83
;TYPE:Outer wall
G1 X10 Y0 F9000
G1 X10 Y0 E-0.8
G1 X20 Y0 E0
G1 Z0.6
G1 X30 Y0 E1.0
G1 E-0.3
"""

ARCOS = "G90\nM83\nG2 X10 Y0 I5 J0 E0.5\nG3 X0 Y0 I-5 J0 E0.5\n"

# sin ;Z: ni ;LAYER_CHANGE: la Z sale de los movimientos Z
SIN_Z = """M83
;TYPE:Outer wall
G1 Z0.2 F600
G1 X10 Y0 E0.5
G1 Z0.4
G1 X10 Y10 E0.5
G1 Z0.6
G1 X0 Y10 E0.5
"""

# gcode con soportes para el dibujo: dos tipos de soporte y un tipo de relleno en la capa 2
MIXTO = """G90
M83
;LAYER_CHANGE
;Z:0.2
;TYPE:Outer wall
G1 X0 Y0 F9000
G1 X10 Y0 E0.5
G1 X10 Y10 E0.5
;TYPE:Support interface
G1 X0 Y10 E0.4
;TYPE:Support
G1 X0 Y0 E0.4
;LAYER_CHANGE
;Z:0.4
;TYPE:Sparse infill
G1 X10 Y5 E0.5
"""


def _gcode_largo(n):
    """n segmentos de extrusión consecutivos (X crece 1 mm en cada uno), todos del mismo tipo y capa."""
    lineas = ['G90', 'M83', ';TYPE:Outer wall', ';LAYER_CHANGE', ';Z:0.2']
    lineas += [f'G1 X{i + 1} Y0 E0.01' for i in range(n)]
    return '\n'.join(lineas) + '\n'


class ColorDeTipo(unittest.TestCase):
    MODELO = ['Outer wall', 'Inner wall', 'Overhang wall', 'Sparse infill', 'Internal solid infill', 'Solid infill', 'Top surface',
              'Bottom surface', 'Internal bridge', 'Bridge', 'Gap infill', 'Skirt', 'Brim', 'Custom']

    def test_insensible_a_mayusculas(self):
        self.assertEqual(render.color_de_tipo('Outer wall'), render.color_de_tipo('outer wall'))
        self.assertEqual(render.color_de_tipo('OUTER WALL'), '#0072B2')

    def test_colores_fijos_de_la_tabla(self):
        casos = {'Inner wall': '#56B4E9', 'Overhang wall': '#882255', 'Sparse infill': '#009E73', 'Internal solid infill': '#7A7A7A',
                 'Solid infill': '#7A7A7A', 'Top surface': '#E69F00', 'Bottom surface': '#8C510A', 'Internal bridge': '#CC79A7',
                 'Bridge': '#CC79A7', 'Gap infill': '#44AA99', 'Skirt': '#BBBBBB', 'Brim': '#BBBBBB', 'Custom': '#999999'}
        for tipo, color in casos.items(): self.assertEqual(render.color_de_tipo(tipo), color, tipo)

    def test_prefijos(self):
        self.assertEqual(render.color_de_tipo('Bridge infill'), '#CC79A7')          # 'bridge' por prefijo
        self.assertEqual(render.color_de_tipo('Skirt/Brim'), '#BBBBBB')             # 'skirt' por prefijo
        self.assertEqual(render.color_de_tipo('Outer wall extra'), '#0072B2')       # prefijo, no igualdad exacta

    def test_support_interface_gana_a_support(self):
        self.assertEqual(render.color_de_tipo('Support interface'), '#8B1A1A')
        self.assertEqual(render.color_de_tipo('Support interface'), render.COLORES['support interface'])
        self.assertNotEqual(render.color_de_tipo('Support interface'), render.color_de_tipo('Support'))
        self.assertEqual(render.color_de_tipo('Support'), '#D55E00')
        self.assertEqual(render.color_de_tipo('Support material'), '#D55E00')       # cualquier otro que empiece por support

    def test_soportes_distintos_de_todo_tipo_del_modelo(self):
        del_modelo = {render.color_de_tipo(t) for t in self.MODELO}
        self.assertNotIn(render.color_de_tipo('Support'), del_modelo)
        self.assertNotIn(render.color_de_tipo('Support interface'), del_modelo)
        self.assertNotIn(render.color_de_tipo('Support material'), del_modelo)

    def test_desconocido_es_gris(self):
        self.assertEqual(render.color_de_tipo('Tipo raro'), '#666666')
        self.assertEqual(render.color_de_tipo(''), '#666666')


class LeerSegmentos(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.d = Path(self.t.name)

    def leer(self, texto, nombre='g.gcode', **kw):
        return render.leer_segmentos(_escribir(self.d, nombre, texto), **kw)

    def test_estilo_orca_recuento_tipos_capas_y_bbox(self):
        r = self.leer(ORCA)
        self.assertEqual((r['total'], r['dibujados'], r['submuestreo'], r['capas']), (4, 4, 1, 2))
        self.assertEqual(r['tipos'], ['Outer wall', 'Sparse infill'])
        np.testing.assert_array_equal(r['tipo'], [0, 0, 1, 0])
        np.testing.assert_allclose(r['x0'], [10, 20, 20, 10], atol=1e-5)
        np.testing.assert_allclose(r['y0'], [10, 10, 20, 20], atol=1e-5)
        np.testing.assert_allclose(r['x1'], [20, 20, 10, 10], atol=1e-5)
        np.testing.assert_allclose(r['y1'], [10, 20, 20, 10], atol=1e-5)
        np.testing.assert_allclose(r['z'], [0.2, 0.2, 0.2, 0.4], atol=1e-5)
        np.testing.assert_allclose(r['bbox'], (10, 20, 10, 20, 0.4), atol=1e-5)
        self.assertEqual(r['arcos_ignorados'], 0)
        self.assertEqual(r['x0'].dtype, np.float32); self.assertEqual(r['tipo'].dtype, np.uint16)

    def test_estilo_m82_absoluta_con_g92(self):
        r = self.leer(M82)
        self.assertEqual(r['total'], 3)                              # el reinicio G92 E0 hace contar el segundo movimiento
        self.assertEqual(r['tipos'], ['sin tipo'])
        self.assertEqual(r['capas'], 1)
        np.testing.assert_allclose(r['x0'], [0, 10, 30], atol=1e-5)
        np.testing.assert_allclose(r['x1'], [10, 20, 40], atol=1e-5)

    def test_travel_y_retraccion_no_cuentan(self):
        r = self.leer(TRAYECTO)
        self.assertEqual((r['total'], r['dibujados']), (1, 1))
        np.testing.assert_allclose(r['x0'], [20], atol=1e-5)
        np.testing.assert_allclose(r['z'], [0.6], atol=1e-5)          # z de la posición tras G1 Z0.6

    def test_arcos_se_cuentan_y_no_dibujan(self):
        r = self.leer(ARCOS)
        self.assertEqual((r['arcos_ignorados'], r['total'], r['dibujados']), (2, 0, 0))
        self.assertIsNone(r['bbox'])

    def test_gcode_vacio_no_es_excepcion(self):
        r = self.leer('')
        self.assertEqual((r['total'], r['dibujados'], r['capas'], r['tipos']), (0, 0, 0, []))
        self.assertIsNone(r['bbox']); self.assertEqual(len(r['x0']), 0)

    def test_sin_capas_la_z_sale_de_los_movimientos(self):
        r = self.leer(SIN_Z)
        np.testing.assert_allclose(r['z'], [0.2, 0.4, 0.6], atol=1e-5)
        self.assertEqual(r['capas'], 3)

    def test_submuestreo_acotado_por_max_segmentos(self):
        r = self.leer(_gcode_largo(5000), max_segmentos=50)
        self.assertEqual(r['total'], 5000)                            # el total es exacto, aunque se submuestree
        self.assertLessEqual(r['dibujados'], 2 * 50)
        self.assertGreaterEqual(r['dibujados'], 50)
        self.assertGreater(r['submuestreo'], 1)
        self.assertAlmostEqual(float(r['bbox'][1]), 5000.0, places=2)  # el bbox cubre todo lo extruido, no solo lo guardado

    def test_submuestreo_explicito_se_respeta(self):
        r = self.leer(_gcode_largo(10), submuestreo=3)
        self.assertGreaterEqual(r['submuestreo'], 3)
        self.assertEqual((r['total'], r['dibujados']), (10, 4))      # índices 0, 3, 6 y 9

    def test_lectura_por_lineas_con_gcode_grande(self):
        r = self.leer(_gcode_largo(50000), max_segmentos=1000)
        self.assertEqual(r['total'], 50000)
        self.assertLessEqual(r['dibujados'], 2 * 1000)                # la memoria no crece con el tamaño del fichero

    def test_max_segmentos_no_valido(self):
        with self.assertRaises(ValueError): self.leer(ORCA, max_segmentos=0)


class DibujarGcode(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.d = Path(self.t.name)
        self.datos = render.leer_segmentos(_escribir(self.d, 'mixto.gcode', MIXTO))

    def test_png_valido_con_las_dimensiones_devueltas(self):
        p = self.d / 'out' / 'mixto.png'
        r = render.dibujar_gcode(self.datos, p, vistas=('superior', 'lateral'), dpi=110, titulo='prueba')
        _comprobar_png(self, p, r)
        self.assertEqual(r['vistas'], ['superior', 'lateral'])

    def test_crea_la_carpeta_padre(self):
        p = self.d / 'nueva' / 'anidada' / 'x.png'
        render.dibujar_gcode(self.datos, p)
        self.assertTrue(p.is_file())

    def test_tipos_devueltos_son_los_presentes(self):
        r = render.dibujar_gcode(self.datos, self.d / 'a.png')
        self.assertEqual(r['tipos'], {'Outer wall': 2, 'Support interface': 1, 'Support': 1, 'Sparse infill': 1})

    def test_determinismo_byte_a_byte(self):
        a = render.dibujar_gcode(self.datos, self.d / 'x' / 'a.png', titulo='t')
        b = render.dibujar_gcode(self.datos, self.d / 'y' / 'b.png', titulo='t')
        self.assertEqual((self.d / 'x' / 'a.png').read_bytes(), (self.d / 'y' / 'b.png').read_bytes())
        self.assertEqual((a['ancho_px'], a['alto_px']), (b['ancho_px'], b['alto_px']))

    def test_vista_superior_y_lateral_difieren(self):
        render.dibujar_gcode(self.datos, self.d / 's.png', vistas=('superior',))
        render.dibujar_gcode(self.datos, self.d / 'l.png', vistas=('lateral',))
        self.assertNotEqual((self.d / 's.png').read_bytes(), (self.d / 'l.png').read_bytes())

    def test_una_sola_vista_es_mas_estrecha(self):
        una = render.dibujar_gcode(self.datos, self.d / 'u.png', vistas=('superior',))
        dos = render.dibujar_gcode(self.datos, self.d / 'd.png', vistas=('superior', 'lateral'))
        self.assertEqual(una['vistas'], ['superior'])
        self.assertGreater(dos['ancho_px'], una['ancho_px'])

    def test_vistas_como_texto(self):
        r = render.dibujar_gcode(self.datos, self.d / 't.png', vistas='superior,lateral')
        self.assertEqual(r['vistas'], ['superior', 'lateral'])

    def test_vista_desconocida_es_error_con_la_lista_valida(self):
        with self.assertRaisesRegex(ValueError, 'superior'):
            render.dibujar_gcode(self.datos, self.d / 'f.png', vistas=('frontal',))

    def test_sin_segmentos_no_dibuja(self):
        vacio = render.leer_segmentos(_escribir(self.d, 'vacio.gcode', 'G90\nM83\nG1 X10 Y0\n'))
        with self.assertRaises(ValueError): render.dibujar_gcode(vacio, self.d / 'v.png')
        self.assertFalse((self.d / 'v.png').exists())

    def test_leyenda_ordena_por_colores_y_marca_soportes(self):
        leyenda = render._leyenda(['Support', 'Outer wall', 'Support interface'])
        self.assertEqual([t for t, _, _ in leyenda], ['Outer wall', 'Support interface', 'Support'])
        self.assertEqual(leyenda[2][2], 'Support (soporte)')
        self.assertEqual(leyenda[0][2], 'Outer wall')

    def test_datos_submuestreados_se_dibujan(self):
        grande = render.leer_segmentos(_escribir(self.d, 'grande.gcode', _gcode_largo(3000)), max_segmentos=50)
        r = render.dibujar_gcode(grande, self.d / 'g.png')
        _comprobar_png(self, self.d / 'g.png', r)
        self.assertLessEqual(r['tipos']['Outer wall'], 2 * 50)


class DibujarStl(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.d = Path(self.t.name)
        self.cubo = self.d / 'cubo.stl'; trimesh.creation.box(extents=(10, 20, 5)).export(str(self.cubo))
        self.esfera_malla = trimesh.creation.icosphere(subdivisions=4)
        self.esfera = self.d / 'esfera.stl'; self.esfera_malla.export(str(self.esfera))

    def test_leer_stl_devuelve_la_malla(self):
        m = render.leer_stl(self.cubo)
        self.assertEqual(len(m.faces), 12)

    def test_cubo_dimensiones_y_png(self):
        p = self.d / 'out' / 'cubo.png'
        r = render.dibujar_stl(self.cubo, p)
        _comprobar_png(self, p, r)
        self.assertAlmostEqual(r['dx_mm'], 10.0, places=4)
        self.assertAlmostEqual(r['dy_mm'], 20.0, places=4)
        self.assertAlmostEqual(r['dz_mm'], 5.0, places=4)
        self.assertEqual((r['triangulos'], r['dibujados']), (12, 12))
        self.assertEqual(r['vistas'], ['superior', 'frontal', 'lateral'])

    def test_malla_grande_se_submuestrea_de_forma_determinista(self):
        r = render.dibujar_stl(self.esfera, self.d / 'e.png', max_triangulos=300)
        self.assertEqual(r['triangulos'], len(self.esfera_malla.faces))
        self.assertLessEqual(r['dibujados'], 300)
        self.assertEqual(r['dibujados'], 300)
        _comprobar_png(self, self.d / 'e.png', r)
        render.dibujar_stl(self.esfera, self.d / 'e2.png', max_triangulos=300)
        self.assertEqual((self.d / 'e.png').read_bytes(), (self.d / 'e2.png').read_bytes())

    def test_determinismo_byte_a_byte(self):
        render.dibujar_stl(self.cubo, self.d / 'a.png', titulo='cubo')
        render.dibujar_stl(self.cubo, self.d / 'sub' / 'b.png', titulo='cubo')
        self.assertEqual((self.d / 'a.png').read_bytes(), (self.d / 'sub' / 'b.png').read_bytes())

    def test_vistas_distintas_producen_imagenes_distintas(self):
        render.dibujar_stl(self.cubo, self.d / 's.png', vistas=('superior',))
        render.dibujar_stl(self.cubo, self.d / 'f.png', vistas=('frontal',))
        self.assertNotEqual((self.d / 's.png').read_bytes(), (self.d / 'f.png').read_bytes())

    def test_vista_desconocida_es_error(self):
        with self.assertRaisesRegex(ValueError, 'superior'):
            render.dibujar_stl(self.cubo, self.d / 'x.png', vistas=('oblicua',))

    def test_archivo_inexistente(self):
        with self.assertRaises(FileNotFoundError): render.leer_stl(self.d / 'no_existe.stl')


if __name__ == '__main__': unittest.main()
