"""Bloque estimar_impresion: filamento y tiempo de impresión a partir de la masa estimada del CAD, con la razón y el error DECLARADOS en `[calibracion]` de agentcad.toml (ver agentcad/calibracion.py)."""
from ._base import proy, huella_base
MANIFIESTO = dict(nombre='estimar_impresion', descripcion='Estima filamento y tiempo de impresión desde la masa del CAD con una calibración declarada y su error; sin calibración no da cifras.',
    entradas={'masa_g': {'type': 'number', 'unidad': 'g', 'descripcion': 'masa estimada del CAD (describe_part / build), sin soportes'},
              'perfil': {'type': 'string', 'default': '', 'descripcion': 'perfil de [calibracion.perfiles.<nombre>]; vacío = calibracion.perfil'}},
    salidas={'filamento_g': {'type': 'number', 'unidad': 'g'}, 'filamento_min_g': {'type': 'number', 'unidad': 'g'}, 'filamento_max_g': {'type': 'number', 'unidad': 'g'},
             'tiempo_h': {'type': 'number', 'unidad': 'h'}, 'tiempo_min_h': {'type': 'number', 'unidad': 'h'}, 'tiempo_max_h': {'type': 'number', 'unidad': 'h'},
             'fiable': {'type': 'boolean'}, 'nota': {'type': 'string'}},
    precondiciones=['[calibracion.perfiles.<nombre>] con razon_filamento, error_filamento_rel, s_por_g, error_tiempo_rel, n_grupos (ajustados con agentcad.calibracion a TUS laminados)'],
    efectos=[], ejemplo={'masa_g': 100.0}, pesado=False, deshacible=False, determinista=True,
    honestidad='digital: razón ajustada a unos laminados, con el error de validación cruzada declarado; no se ha pesado ni cronometrado nada y con pocos grupos de calibración `fiable` es false')

def _perfil(ctx, nombre):
    c = proy(ctx)['calibracion']; n = nombre or c.get('perfil', '')
    pf = c.get('perfiles', {}).get(n) if n else None
    if pf is None: raise ValueError(f'no_calibrado: perfil {n!r} sin calibración en [calibracion.perfiles]; ajústala con agentcad.calibracion.calibrar a tus laminados' + (f' (hay: {sorted(c.get("perfiles", {}))})' if c.get('perfiles') else ''))
    for k in ('razon_filamento', 'error_filamento_rel', 's_por_g', 'error_tiempo_rel', 'n_grupos'):
        if k not in pf: raise ValueError(f'no_calibrado: falta {k} en [calibracion.perfiles.{n}]')
    return n, pf

def huella(e, ctx): return dict(perfil=_perfil(ctx, e.get('perfil', ''))[1], **huella_base(ctx))

def ejecutar(e, ctx):
    from .. import calibracion
    if not e['masa_g'] > 0: raise ValueError('estimar_impresion: masa_g debe ser > 0')
    n, pf = _perfil(ctx, e.get('perfil', '')); f = calibracion.estimar(e['masa_g'], pf['razon_filamento'], pf['error_filamento_rel']); t = calibracion.estimar(e['masa_g'], pf['s_por_g'] / 3600.0, pf['error_tiempo_rel'])
    fiable = pf['n_grupos'] >= calibracion.MIN_GRUPOS_FIABLE
    nota = (f'digital; perfil {n}, calibrado con {pf["n_grupos"]} grupos' + ('' if fiable else f' (< {calibracion.MIN_GRUPOS_FIABLE}: error indicativo, no garantizado)') + (f'; origen: {pf["origen"]}' if pf.get('origen') else '')
            + f'; banda = error de validación cruzada declarado (filamento ±{100 * pf["error_filamento_rel"]:.0f} %, tiempo ±{100 * pf["error_tiempo_rel"]:.0f} %)')
    return dict(filamento_g=round(f['valor'], 2), filamento_min_g=round(f['min'], 2), filamento_max_g=round(f['max'], 2), tiempo_h=round(t['valor'], 3), tiempo_min_h=round(t['min'], 3), tiempo_max_h=round(t['max'], 3), fiable=fiable, nota=nota)
