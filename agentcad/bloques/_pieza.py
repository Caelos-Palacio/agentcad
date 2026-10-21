"""Resolución de piezas para las puertas: nombre en rutas.stl (actual) o ruta absoluta de la línea base declarada en [bases] de agentcad.toml."""
from ._base import proy
def actual(p): return p
def base(p, ctx=None, ref='linea_base'):
    d = proy(ctx).bases.get(ref)
    return str(d / f'{p}.stl') if d else str(proy(ctx).raiz / '_sin_linea_base' / f'{p}.stl')
def printabilidad(parte):
    from agentcad.printability import check_printability
    r = check_printability(parte)
    if r.get('estado') != 'ok': raise RuntimeError(f"check_printability: {r.get('codigo')} {r.get('mensaje')}")
    return r
