"""Pruebas del analizador de gcode genérico (agentcad.gcode.analyze), portadas del analizador determinista del proyecto de origen (16 pruebas) más las de tolerancia
a Orca/Prusa. El gcode es SINTÉTICO, generado por código (todo digital: ninguna prueba toca una impresora ni un laminador).

Convenciones del gcode sintético:
- Capas numeradas desde 1: la capa k tiene z = 0,2 * k.
- Extrusor relativo (M83), posicionamiento absoluto (G90), filamento 1,75 mm.
- E por segmento = longitud * 0,45 * 0,2 / (pi * 0,875**2).
"""
import math
import unittest

from agentcad.gcode import analyze


OBJ = "pieza_1_id_0_copy_0"
MACHINE = {"bed_x": 260.0, "bed_y": 260.0, "z_max": 260.0}
LIMITS = {
    "max_volumetric_mm3_s": 8.0,
    "nozzle_temp_max": 250,
    "bed_temp_max": 80,
    "max_speed_mm_s": 450,
}
ALTURA_CAPA = 0.2
ANCHO = 0.45
FILAMENTO_RADIO = 0.875
DENSIDAD_PLA = 1.27  # g/cm3


def _e_segmento(longitud):
    return longitud * ANCHO * ALTURA_CAPA / (math.pi * FILAMENTO_RADIO ** 2)


def fill_square(x0, y0, x1, y1, paso=0.45):
    """Relleno en zigzag horizontal de un cuadrado, paso 0,45 mm."""
    pts = []
    y = y0
    izq_a_der = True
    while y <= y1 + 1e-9:
        if izq_a_der:
            pts += [(x0, y), (x1, y)]
        else:
            pts += [(x1, y), (x0, y)]
        izq_a_der = not izq_a_der
        y += paso
    return pts


def solid(x0, y0, x1, y1):
    """Pared exterior y relleno de un cuadrado macizo."""
    perimetro = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return [("Outer wall", perimetro), ("Sparse infill", fill_square(x0, y0, x1, y1))]


def capa(k, segs):
    """Capa k (1-based), z = 0.2 * k."""
    return (round(ALTURA_CAPA * k, 3), segs)


def make_gcode(layers, header=True, footer=True, obj=OBJ):
    """Construye G-code sintetico.

    layers: lista de (z, [seg, ...]).
    seg: (tipo, puntos) o (tipo, puntos, opts) con opts = {"obj": str, "f": mm/min}.
         tipo "RAW": puntos es el texto de una linea G-code tal cual.
    """
    lines = []
    if header:
        lines += ["M140 S75", "M104 S240", "G28", "M109 S240"]
    lines += ["G90", "M83"]
    for z, segs in layers:
        lines += [";LAYER_CHANGE", f";Z:{z:.3f}", f";HEIGHT:{ALTURA_CAPA}"]
        for seg in segs:
            tipo, dato = seg[0], seg[1]
            opts = seg[2] if len(seg) > 2 else {}
            if tipo == "RAW":
                lines.append(dato)
                continue
            nombre = opts.get("obj", obj)
            avance = opts.get("f", 1800)
            lines.append(f"EXCLUDE_OBJECT_START NAME={nombre}")
            lines.append(f";TYPE:{tipo}")
            lines.append(f";WIDTH:{ANCHO}")
            x0, y0 = dato[0]
            lines.append(f"G0 X{x0:.3f} Y{y0:.3f} F9000")
            for (xa, ya), (xb, yb) in zip(dato, dato[1:]):
                e = _e_segmento(math.hypot(xb - xa, yb - ya))
                lines.append(f"G1 X{xb:.3f} Y{yb:.3f} E{e:.5f} F{avance}")
            lines.append(f"EXCLUDE_OBJECT_END NAME={nombre}")
    if footer:
        lines += ["M104 S0", "M140 S0"]
    return "\n".join(lines) + "\n"


def pieza_limpia(capas=10):
    """Bloque 20x20 (x,y 100..120) de `capas` capas."""
    return make_gcode([capa(k, solid(100, 100, 120, 120)) for k in range(1, capas + 1)])


def _analizar(gcode):
    return analyze(gcode, machine=MACHINE, limits=LIMITS)


def _mensajes(res):
    return res["errors"] + res["warnings"]


class TestPiezaLimpia(unittest.TestCase):
    def test_pieza_limpia_sin_problemas(self):
        res = _analizar(pieza_limpia())
        self.assertEqual(res["floating_islands"], [])
        self.assertEqual(res["support_issues"], [])
        self.assertEqual(res["errors"], [])
        self.assertTrue(res["ok"])
        self.assertAlmostEqual(res["max_z"], 2.0, delta=0.01)
        self.assertEqual(res["layers"], 10)


class TestIslasFlotantes(unittest.TestCase):
    def _gcode_con_isla(self, extra_capa6=None):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 6)]
        segs6 = solid(100, 100, 120, 120) + [("Sparse infill", fill_square(140, 140, 150, 150))]
        if extra_capa6 is not None:
            segs6 = segs6 + extra_capa6
        capas.append(capa(6, segs6))
        return make_gcode(capas)

    def test_isla_flotante_detectada(self):
        res = _analizar(self._gcode_con_isla())
        islas = [i for i in res["floating_islands"] if i["layer"] == 6]
        self.assertGreaterEqual(len(islas), 1)
        isla = islas[0]
        self.assertAlmostEqual(isla["x"], 145, delta=3)
        self.assertAlmostEqual(isla["y"], 145, delta=3)
        self.assertAlmostEqual(isla["z"], 1.2, delta=0.01)
        self.assertGreater(isla["area_mm2"], 50)
        self.assertTrue(
            any("flot" in s.lower() or "isla" in s.lower() for s in _mensajes(res)),
            msg=f"sin aviso de isla flotante: {_mensajes(res)}",
        )

    def test_voladizo_apoyado_por_soporte_no_es_isla(self):
        capas = [
            capa(k, solid(100, 100, 120, 120) + [("Support", fill_square(140, 140, 150, 150))])
            for k in range(1, 6)
        ]
        capas.append(capa(6, solid(100, 100, 120, 120) + [("Sparse infill", fill_square(140, 140, 150, 150))]))
        res = _analizar(make_gcode(capas))
        self.assertEqual(res["floating_islands"], [])
        self.assertEqual(res["support_issues"], [])


class TestSoportes(unittest.TestCase):
    def test_soporte_flotante_detectado(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 3)]
        capas += [capa(k, [("Support", fill_square(140, 140, 150, 150))]) for k in range(3, 6)]
        res = _analizar(make_gcode(capas))
        self.assertNotEqual(res["support_issues"], [])

    def test_soporte_apoyado_en_modelo_detectado(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 6)]
        capas += [
            capa(k, solid(100, 100, 120, 120) + [("Support", fill_square(105, 105, 110, 110))])
            for k in range(6, 9)
        ]
        res = _analizar(make_gcode(capas))
        self.assertNotEqual(res["support_issues"], [])


class TestFueraDeCama(unittest.TestCase):
    def test_extrusion_fuera_de_cama(self):
        capa1 = capa(1, solid(100, 100, 120, 120) + [("Sparse infill", [(250, 100), (270, 100)])])
        res = _analizar(make_gcode([capa1]))
        self.assertNotEqual(res["out_of_bed_extrusion"], [])
        self.assertNotEqual(res["errors"], [])
        self.assertFalse(res["ok"])

    def test_viaje_fuera_de_cama(self):
        capa1 = capa(1, solid(100, 100, 120, 120) + [("RAW", "G0 X300 Y100 F9000")])
        res = _analizar(make_gcode([capa1]))
        self.assertNotEqual(res["out_of_bed_travel"], [])


class TestZSobreLimite(unittest.TestCase):
    def test_z_sobre_maximo(self):
        capas = [capa(1, solid(100, 100, 120, 120)), (270.0, solid(100, 100, 120, 120))]
        res = _analizar(make_gcode(capas))
        self.assertTrue(res["z_over_max"])
        self.assertFalse(res["ok"])


class TestTemperaturaYVelocidad(unittest.TestCase):
    def test_temperatura_excesiva(self):
        capa1 = capa(1, solid(100, 100, 120, 120) + [("RAW", "M104 S300")])
        res = _analizar(make_gcode([capa1]))
        self.assertEqual(res["temps"]["nozzle_max"], 300)
        self.assertTrue(any("temp" in e.lower() for e in res["errors"]), msg=res["errors"])

    def test_velocidad_excesiva(self):
        capa1 = capa(1, [("Sparse infill", [(100, 100), (200, 100)], {"f": 30000})])
        res = _analizar(make_gcode([capa1]))
        self.assertAlmostEqual(res["max_speed_mm_s"], 500, delta=1)
        self.assertTrue(
            any("veloc" in e.lower() or "speed" in e.lower() for e in res["errors"]),
            msg=res["errors"],
        )


class TestCaudal(unittest.TestCase):
    def test_caudal_volumetrico_excesivo(self):
        capa1 = capa(1, [("Outer wall", [(100, 100), (200, 100)], {"f": 6000})])
        res = _analizar(make_gcode([capa1]))
        self.assertGreater(res["max_volumetric_mm3_s"], 8)
        self.assertTrue(
            any("caudal" in m.lower() or "volum" in m.lower() for m in _mensajes(res)),
            msg=_mensajes(res),
        )


class TestInicioFin(unittest.TestCase):
    def test_sin_pie(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 4)]
        res = _analizar(make_gcode(capas, footer=False))
        self.assertFalse(res["start_end"]["has_end"])
        self.assertTrue(res["errors"] or res["warnings"])

    def test_con_cabecera_y_pie(self):
        res = _analizar(pieza_limpia(3))
        self.assertTrue(res["start_end"]["has_start"])
        self.assertTrue(res["start_end"]["has_end"])

    def test_sin_cabecera(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 4)]
        res = _analizar(make_gcode(capas, header=False))
        self.assertFalse(res["start_end"]["has_start"])


class TestFilamento(unittest.TestCase):
    def test_longitud_masa_y_tiempo(self):
        res = _analizar(pieza_limpia())
        fil = res["filament"]
        self.assertGreater(fil["length_mm"], 0)
        masa_esperada = fil["length_mm"] * math.pi * FILAMENTO_RADIO ** 2 * DENSIDAD_PLA / 1000
        self.assertLess(abs(fil["mass_g"] - masa_esperada) / masa_esperada, 0.01)
        self.assertGreater(res["time_s_lower_bound"], 0)


class TestObjetosIndependientes(unittest.TestCase):
    def test_apoyo_se_evalua_por_objeto(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 6)]
        # Segundo objeto: una sola capa, a z=1.2, sobre material del primero.
        capas.append(capa(6, [("Sparse infill", fill_square(105, 105, 110, 110), {"obj": "pieza_b"})]))
        res = _analizar(make_gcode(capas))
        islas_b = [i for i in res["floating_islands"] if i["object"] == "pieza_b"]
        self.assertGreaterEqual(len(islas_b), 1)
        self.assertEqual(islas_b[0]["layer"], 6)
        self.assertFalse(any(i["object"] == OBJ for i in res["floating_islands"]))


class TestToleranciaOrcaPrusa(unittest.TestCase):
    """Variantes de comentarios de Orca/Prusa: tipos en otra capitalización, objetos `; printing object`, sin `;Z:`, cabecera de laminador."""

    @staticmethod
    def _prusa(capas=6, z_comentario=True, tipo_soporte="Support material"):
        lines = ["; generated by PrusaSlicer 2.7", "M140 S60", "M104 S215", "G28", "M109 S215", "G90", "M83"]
        for k in range(1, capas + 1):
            z = round(0.2 * k, 3)
            lines += [";LAYER_CHANGE"] + ([f";Z:{z}"] if z_comentario else []) + [f"G1 Z{z} F720", ";HEIGHT:0.2"]
            lines += ["; printing object caja id:0 copy 0", ";TYPE:Perimeter", ";WIDTH:0.45", "G1 X100 Y100 F9000"]
            for (xa, ya), (xb, yb) in zip([(100, 100), (120, 100), (120, 120), (100, 120)], [(120, 100), (120, 120), (100, 120), (100, 100)]):
                lines.append(f"G1 X{xb} Y{yb} E{_e_segmento(math.hypot(xb - xa, yb - ya)):.5f} F1800")
            lines += ["; stop printing object caja id:0 copy 0"]
        lines += ["; estimated printing time (normal mode) = 1h 2m 3s", "M104 S0", "M140 S0"]
        return "\n".join(lines) + "\n"

    def test_objeto_prusa_y_cabecera(self):
        res = _analizar(self._prusa())
        self.assertIn("caja id:0 copy 0", res["per_object"])
        self.assertEqual(res["header"]["time_normal"], 3723)
        self.assertEqual(res["layers"], 6)
        self.assertTrue(res["ok"], res["errors"])

    def test_sin_comentario_z_usa_la_z_del_movimiento(self):
        res = _analizar(self._prusa(z_comentario=False))
        self.assertAlmostEqual(res["max_z"], 1.2, delta=0.01)

    def test_soporte_en_mayusculas_se_reconoce(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 3)]
        capas += [capa(k, [("SUPPORT", fill_square(140, 140, 150, 150))]) for k in range(3, 6)]
        res = _analizar(make_gcode(capas))
        self.assertNotEqual(res["support_issues"], [])      # un soporte flotante solo se ve si se clasifica como soporte

    def test_puente_largo_sobre_dos_apoyos(self):
        # dos pilares separados 14 mm y una losa que los cubre: la luz central queda a >5 mm de cualquier apoyo
        pil = [capa(k, solid(100, 100, 106, 120) + solid(120, 100, 126, 120)) for k in range(1, 6)]
        losa = capa(6, solid(100, 100, 126, 120))
        res = _analizar(make_gcode(pil + [losa]))
        self.assertEqual(res["floating_islands"], [])
        self.assertTrue(any(o["tipo"] == "puente_largo" for o in res["overhangs"]), res["overhangs"])

    def test_sin_exigir_inicio_fin(self):
        capas = [capa(k, solid(100, 100, 120, 120)) for k in range(1, 4)]
        res = analyze(make_gcode(capas, header=False, footer=False), machine=MACHINE, limits=LIMITS, require_start_end=False)
        self.assertEqual(res["errors"], [])


if __name__ == "__main__":
    unittest.main()
