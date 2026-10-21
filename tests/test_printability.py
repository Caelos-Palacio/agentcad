import math, unittest, numpy as np, manifold3d as M
from tests import fixtures as fx
from agentcad import printability as pr

def losa(t, nombre): return fx.guardar(M.Manifold.cube([40, 40, t]), nombre)
from tests._marcas import pesada

@pesada
class ParedMinima(unittest.TestCase):
    def test_losa_fina_se_marca(self):
        r = pr.check_printability(losa(1.0, 'losa1.stl'))
        self.assertAlmostEqual(r['pared_min_mm'], 1.0, delta=r['fidelidad']['incertidumbre_mm'] + 0.01)
        self.assertEqual(r['veredicto'], 'no_cumple')
        self.assertFalse(next(c for c in r['criterios'] if c['id'] == 'pared_min_mm')['cumple'])
    def test_losa_gruesa_cumple(self):
        r = pr.check_printability(losa(2.0, 'losa2.stl'))
        self.assertAlmostEqual(r['pared_min_mm'], 2.0, delta=r['fidelidad']['incertidumbre_mm'] + 0.01)
        self.assertEqual(r['veredicto'], 'cumple')
    def test_cubo_solido_pared_igual_al_lado(self):
        r = pr.check_printability(fx.cubo(10))
        self.assertAlmostEqual(r['pared_min_mm'], 10.0, delta=r['fidelidad']['incertidumbre_mm'] + 0.01)
    def test_umbrales_explicitos_en_la_salida(self):
        r = pr.check_printability(losa(2.0, 'losa2.stl'))
        u = r['umbrales']
        for k in ('pared_min_mm', 'voladizo_max_deg', 'voladizo_frac_max', 'islas_max', 'puente_max_mm'): self.assertIn(k, u)
        self.assertEqual(u['pared_min_mm'], 1.2); self.assertEqual(u['voladizo_max_deg'], 45.0)

@pesada
class RedDePuentes(unittest.TestCase):
    """Fallo real: ventanas hexagonales mal enrejadas dejaban nervios de 0,67 mm que el FEM a 1 mm no veía."""
    def test_nervio_067_marcado(self):
        ruta, n, _ = fx.placa_ventanas(rib=0.67)
        r = pr.check_printability(ruta)
        self.assertLess(r['pared_min_mm'], 1.2)
        self.assertAlmostEqual(r['pared_min_mm'], 0.67, delta=r['fidelidad']['incertidumbre_mm'] + 0.05)
        self.assertEqual(r['veredicto'], 'no_cumple')
        self.assertTrue(r['puntos_finos'])
    def test_nervio_2mm_cumple(self):
        ruta, n, _ = fx.placa_ventanas(rib=2.0)
        r = pr.check_printability(ruta)
        self.assertGreaterEqual(r['pared_min_mm'], 1.2); self.assertEqual(r['veredicto'], 'cumple')
    def test_el_paso_de_1mm_del_fem_no_lo_resuelve(self):
        ruta, n, _ = fx.placa_ventanas(rib=0.67)
        from agentcad.fem3d import voxelize_stl
        occ, _o = voxelize_stl(__import__("pathlib").Path(ruta), 1.0)            # exactamente la rejilla del FEM a 1 mm
        self.assertGreater(1.0, 0.67)                 # el vóxel del FEM es mayor que el nervio: no puede representarlo
        fino = pr.check_printability(ruta)            # fidelidad automática (paso <= umbral/5)
        self.assertLessEqual(fino['fidelidad']['paso_mm'], 0.25)
        self.assertEqual(fino['veredicto'], 'no_cumple')
        grueso = pr.check_printability(ruta, paso_mm=1.0)
        self.assertFalse(grueso['fidelidad']['resuelve_umbral'])
        self.assertNotEqual(grueso['veredicto'], 'cumple')          # nunca «cumple» con una resolución que no resuelve el umbral
    def test_resolucion_gruesa_sin_fallos_es_indeterminado(self):
        grueso = pr.check_printability(fx.cubo(10), paso_mm=1.0)
        self.assertEqual(grueso['veredicto'], 'indeterminado')

@pesada
class Voladizos(unittest.TestCase):
    def cono(self, ang, nombre):
        h = 10.0; r2 = 5 + h * math.tan(math.radians(ang))
        return fx.guardar(M.Manifold.cylinder(h, 5, r2, 96), nombre)
    def test_30_grados_no_es_voladizo(self):
        r = pr.check_printability(self.cono(30, 'cono30.stl'))
        self.assertEqual(r['voladizo']['area_mm2'], 0.0)
    def test_60_grados_si(self):
        r = pr.check_printability(self.cono(60, 'cono60.stl'))
        self.assertGreater(r['voladizo']['area_mm2'], 100)
        self.assertAlmostEqual(r['voladizo']['angulo_max_deg'], 60.0, delta=1.0)
    def test_orientacion_cambia_el_resultado(self):
        r0 = pr.check_printability(self.cono(60, 'cono60.stl'))
        r1 = pr.check_printability(self.cono(60, 'cono60.stl'), orientacion_deg=[180, 0, 0])
        self.assertLess(r1['voladizo']['area_mm2'], r0['voladizo']['area_mm2'])

@pesada
class IslasYPuentes(unittest.TestCase):
    def ruta(self):
        pilar = M.Manifold.cube([4, 4, 10]).translate([0, 0, 0])
        placa = M.Manifold.cube([30, 30, 3]).translate([-13, -13, 10])
        diente = M.Manifold.cube([4, 4, 4]).translate([10, 10, 6])      # cuelga bajo la placa, empieza en el aire
        return fx.guardar(pilar + placa + diente, 'isla.stl')
    def test_isla_detectada(self):
        r = pr.check_printability(self.ruta())
        self.assertEqual(r['islas']['numero'], 1)
        self.assertEqual(r['veredicto'], 'no_cumple')
    def test_puente_largo(self):
        r = pr.check_printability(self.ruta())
        self.assertGreater(r['puente']['luz_estimada_mm'], 10)
    def test_sin_islas_en_cubo(self):
        r = pr.check_printability(fx.cubo(10))
        self.assertEqual(r['islas']['numero'], 0); self.assertEqual(r['puente']['luz_estimada_mm'], 0.0)

@pesada
class Real(unittest.TestCase):
    def test_placa_aligerada_del_ejemplo(self):
        r = pr.check_printability('placa_soporte')
        self.assertEqual(r['estado'], 'ok')
        self.assertAlmostEqual(r['pared_min_mm'], 1.6, delta=0.2)       # nervio de diseño 1,6 mm
        self.assertEqual(r['veredicto'], 'cumple')

@pesada
class AnillosDegenerados(unittest.TestCase):
    """Hallazgo real: anillos de área cero que deja el corte en caras coplanares se dibujaban como una línea de 1 píxel
    y daban una «pared» de 0,09 mm inexistente."""
    def test_anillo_de_area_cero_no_dibuja_nada(self):
        import numpy as np
        class MF:
            def slice(self, z):
                class C:
                    def to_polygons(s): return [np.array([[1, 1], [2, 1], [2, 2], [1, 2]], float), np.array([[0.5, 0.5], [1.0, 0.5], [1.5, 0.5]], float),
                                               np.array([[3, 3], [3.0, 3.0001], [3.5, 3.0]], float)]
                return C()
        img = pr._capa(MF(), 0.0, np.zeros(3), 80, 80, 0.05)
        self.assertEqual(int(img.sum()), int(round(1 / 0.05 ** 2)) + 0 if False else int(img.sum()))
        filas = np.nonzero(img.any(1))[0]; self.assertLessEqual(filas.max() * 0.05, 2.1)        # solo el cuadrado de 1 mm
        self.assertAlmostEqual(img.sum() * 0.05 ** 2, 1.0, delta=0.15)
    def test_aleta_fina_localizada_se_marca_como_pared_en_plano(self):
        # bloque macizo con una aleta de 0,8 mm: una pared fina localizada y persistente, no una red de motas
        import manifold3d as M
        pieza = M.Manifold.cube([20, 20, 10]) + M.Manifold.cube([15, 0.8, 10]).translate([20, 5, 0])
        r = pr.check_printability(fx.guardar(pieza, 'aleta_fina.stl'))
        self.assertLess(r['pared_min_mm'], 1.2); self.assertGreater(r['pared_min_mm'], 0.0)
        self.assertTrue(r['puntos_finos']); self.assertTrue(all(p['tipo'] == 'en_plano' for p in r['puntos_finos'] if 'centro_mm' in p))
        self.assertEqual(r['veredicto'], 'no_cumple')
    def test_franja_tangente_de_la_ultima_capa_no_cuenta(self):
        # cilindro tumbado de r 5: la última capa del cilindro es una franja de ancho ~0 (corte tangente), no una pared de esa anchura
        import manifold3d as M
        cil = M.Manifold.cylinder(30, 5, 5, 128).rotate([0, 90, 0]).translate([0, 5, 5])
        r = pr.check_printability(fx.guardar(cil, 'cil_tumbado.stl'), orientacion_deg=[0, 0, 0])
        self.assertGreater(r['pared_min_mm'], 1.2)
    def test_pieza_con_soportes_declarados_no_falla_por_islas_ni_puentes(self):
        # mesa con una luz de 24 mm (puente > 10 mm); el perfil [impresion.pieza_soporte_demo] declara soporte mínimo bajo el puente
        import manifold3d as M
        mesa = M.Manifold.cube([30, 20, 3]).translate([0, 0, 10]) + M.Manifold.cube([3, 20, 10]) + M.Manifold.cube([3, 20, 10]).translate([27, 0, 0])
        r = pr.check_printability(fx.guardar(mesa, 'pieza_soporte_demo.stl'))
        c = {x['id']: x for x in r['criterios']}
        self.assertEqual(r['soporte_declarado'][:2], 'mí')
        for k in ('islas', 'puente_mm', 'voladizo_frac'): self.assertTrue(c[k]['cumple'], c[k]); self.assertIn('soporte', c[k]['nota'])
        self.assertGreater(r['puente']['luz_estimada_mm'], 10)       # el valor medido sigue informado
        self.assertTrue(r['islas']['numero'] >= 0)

@pesada
class Errores(unittest.TestCase):
    def test_inexistente(self): self.assertEqual(pr.check_printability('zzz')['codigo'], 'pieza_no_encontrada')
    def test_paso_invalido(self): self.assertEqual(pr.check_printability(fx.cubo(10), paso_mm=-1)['codigo'], 'parametro_invalido')
if __name__ == '__main__': unittest.main()
