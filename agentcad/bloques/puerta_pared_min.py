from ._base import simulado, medida
from . import _pieza
MANIFIESTO = dict(nombre='puerta_pared_min', descripcion='Puerta: pared mínima imprimible de la pieza >= umbral (agentcad.check_printability, con su tolerancia de medida).',
    entradas={'pieza': {'type': 'string'}, 'umbral_mm': {'type': 'number', 'default': 1.2}},
    salidas={'ok': {'type': 'boolean'}, 'pared_min_mm': {'type': 'number'}, 'veredicto': {'type': 'string'}},
    precondiciones=['STL de la pieza en rutas.stl'], efectos=[], ejemplo={'pieza': 'soporte'}, pesado=True, deshacible=False,
    honestidad='digital: medida sobre malla voxelizada (±paso/4); no incluye la tolerancia de la impresora ni prueba la pieza impresa')
def _ver(e, pared, tol): return dict(ok=bool(pared + tol >= e.get('umbral_mm', 1.2)), pared_min_mm=round(pared, 4), veredicto='cumple' if pared + tol >= e.get('umbral_mm', 1.2) else 'no_cumple')
def ejecutar(e, ctx):
    r = _pieza.printabilidad(_pieza.actual(e['pieza'])); crit = next(c for c in r['criterios'] if c['id'] == 'pared_min_mm')
    return _ver(e, r['pared_min_mm'], crit['tolerancia_medida_mm'])
def simular(e, ctx): return _ver(e, float(medida(ctx, e['pieza'], 'pared_min_mm', 1.5)), 0.0)
