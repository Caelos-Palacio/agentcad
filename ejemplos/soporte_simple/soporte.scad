// Equivalente OpenSCAD de generar_stl.py (documentación; el ejemplo no necesita OpenSCAD para funcionar).
include <params.scad>;
taladros = [[5, 5], [ancho - 5, 5], [5, alto - 5], [ancho - 5, alto - 5]];
module placa() {
  difference() {
    union() {
      cube([ancho, alto, espesor]);
      for (t = taladros) translate([t[0], t[1], espesor - 0.01]) cylinder(r = 3.5, h = 6.01, $fn = 32);
    }
    for (t = taladros) translate([t[0], t[1], -1]) cylinder(r = 1.6, h = espesor + 8, $fn = 32);
    // las ventanas (ventanas == 1) las calcula generar_stl.py: rejilla hexagonal a >= 9 mm de los pilares
  }
}
placa();
