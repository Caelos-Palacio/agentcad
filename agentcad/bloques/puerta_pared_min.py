from ._base import simulado, medida
from . import _pieza
MANIFIESTO = dict(nombre='puerta_pared_min', descripcion='Puerta: pared mínima imprimible >= umbral, o no peor que la línea base si esta ya incumplía (check_printability).',
    entradas={'pieza': {'type': 'string'}, 'umbral_mm': {'type': 'number', 'default': 1.2}, 'base': {'type': 'string', 'default': 'linea_base'}},
    salidas={'ok': {'type': 'boolean'}, 'pared_min_mm': {'type': 'number'}, 'veredicto': {'type': 'string'}, 'preexistente': {'type': 'boolean'}, 'vertical_no_resuelto': {'type': 'boolean'}},
    precondiciones=['STL de la pieza en rutas.stl; opcional, línea base en [bases]'], efectos=[], ejemplo={'pieza': 'soporte'}, pesado=True, deshacible=False,
    honestidad='digital: un defecto preexistente de la base no se cuenta como nuevo pero se informa (preexistente=true); medida sobre malla voxelizada (±paso/4); no incluye la tolerancia de la impresora ni prueba la pieza impresa')
def efectiva(r):
    """(pared_efectiva_mm, vertical_no_resuelto) desde un resultado de check_printability. Una racha vertical <= 1,5 vóxeles no es medible
    (aliasing de superficies curvas/inclinadas junto a losas): se descarta y se informa; el espesor en plano (EDT, ±paso/4) sí cuenta."""
    fid = r.get('fidelidad', {}); vert = fid.get('espesor_vertical_min_mm'); p = fid.get('paso_mm', 0.0)
    if vert is None or vert > 1.5 * p: return r['pared_min_mm'], False
    planos = [q['espesor_mm'] for q in r.get('puntos_finos', []) if q.get('tipo') == 'en_plano']
    return (min(planos) if planos else max(r['pared_min_mm'], 10.0)), True
def _ver(e, pared, tol, pared_base=None, nores=False):
    u = e.get('umbral_mm', 1.2); ok = pared + tol >= u; pre = False
    if not ok and pared_base is not None and pared_base + tol < u and pared + tol >= pared_base - tol: ok, pre = True, True   # defecto preexistente que no empeora
    return dict(ok=bool(ok), pared_min_mm=round(pared, 4), veredicto='cumple' if ok and not pre else ('preexistente_no_peor' if pre else 'no_cumple'), preexistente=pre, vertical_no_resuelto=nores)
def ejecutar(e, ctx):
    r = _pieza.printabilidad(_pieza.actual(e['pieza'])); crit = next(c for c in r['criterios'] if c['id'] == 'pared_min_mm')
    from pathlib import Path
    bs = _pieza.base(e['pieza'], ctx, e.get('base', 'linea_base')); pb = 0 if Path(bs).is_file() else None
    pe, nr = efectiva(r)
    return _ver(e, pe, crit['tolerancia_medida_mm'], pb if pb is None else efectiva(_pieza.printabilidad(bs))[0], nr)
def simular(e, ctx): return _ver(e, float(medida(ctx, e['pieza'], 'pared_min_mm', 1.5)), 0.0)
