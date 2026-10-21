from ._base import medida
MANIFIESTO = dict(nombre='puerta_interferencia', descripcion='Puerta: la pieza no interfiere (> 0,1 mm3) con sus vecinas, salvo el volumen conocido declarado (agentcad.check_interference).',
    entradas={'pieza': {'type': 'string'}, 'pose': {'type': 'string', 'default': 'neutra'}, 'conocido_mm3': {'type': 'number', 'default': 0.0, 'unidad': 'mm3'}},
    salidas={'ok': {'type': 'boolean'}, 'volumen_mm3': {'type': 'number', 'unidad': 'mm3'}, 'estado': {'type': 'string'}},
    precondiciones=['STL actual y ensamblaje (rutas.ensamblaje; tras build)'], efectos=[], ejemplo={'pieza': 'soporte'}, pesado=True, deshacible=False,
    determinista=True, honestidad='digital: poses discretas, geometría nominal, sin holguras; estado no_evaluable si la pieza no figura en el ensamblaje (no cuenta como validada)')
def _ver(e, vol, estado): return dict(ok=estado != 'interfiere' or vol <= e.get('conocido_mm3', 0.0) + 1e-9, volumen_mm3=round(vol, 4), estado=estado)
def huella(e, ctx):
    from ._base import huella_pieza, huella_ensamblaje
    return dict(huella_pieza(e['pieza'], ctx), **huella_ensamblaje(ctx))
def ejecutar(e, ctx):
    from agentcad.interference import check_interference
    r = check_interference(e['pieza'], None if e.get('pose', 'neutra') == 'neutra' else e['pose'])
    if r.get('estado') != 'ok': raise RuntimeError(f"check_interference: {r.get('codigo')} {r.get('mensaje')}")
    return _ver(e, r.get('volumen_total_mm3', 0.0), r['veredicto'])
def simular(e, ctx):
    v = float(medida(ctx, e['pieza'], 'interferencia_mm3', 0.0)); return _ver(e, v, 'interfiere' if v > 0.1 else 'sin_interferencia')
