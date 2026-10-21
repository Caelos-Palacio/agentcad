import json, subprocess
from ._base import raiz, proy, fijar_param, flag_activo, scad, simulado, python
MANIFIESTO = dict(nombre='aplicar_params', descripcion='Fija en params.scad los parámetros y el flag de cada pieza elegida (JSON de configuración) y ejecuta sus emisores.',
    entradas={'config': {'type': 'string', 'descripcion': 'ruta al JSON piezas.<pieza>.{flag,params,emitir?,fem?}'}, 'pieza': {'type': 'string', 'default': 'todas'}},
    salidas={'piezas_activas': {'type': 'array'}, 'anteriores': {'type': 'object'}},
    precondiciones=['config JSON con piezas.<pieza>.{flag,params,emitir?}', 'el archivo rutas.params (OpenSCAD) contiene cada flag y parámetro'],
    efectos=['edita el archivo rutas.params', 'puede ejecutar los comandos `emitir` de la configuración (no en modo simulado)'], pesado=False, deshacible=True,
    honestidad='solo cambia parámetros de diseño; la validez se decide en build/verify/puertas. deshacer = flag de la pieza a 0 (no restaura parámetros auxiliares)',
    ejemplo={'config': 'config.json'})
def _cfg(e, ctx): return json.loads((raiz(ctx) / e['config']).read_text())
def _activos(t, cfg): return [p for p, c in cfg['piezas'].items() if flag_activo(t, c['flag'])]
def _sel(e, cfg):
    s = e.get('pieza', 'todas')
    if s == 'todas': return list(cfg['piezas'])
    if s not in cfg['piezas']: raise KeyError(f'pieza {s} no está en la configuración')
    return [s]
def ejecutar(e, ctx):
    r = raiz(ctx); cfg = _cfg(e, ctx); pp = proy(ctx).params; t = pp.read_text(); ant = {}
    for p in _sel(e, cfg):
        c = cfg['piezas'][p]
        for k, v in {**c.get('params', {}), c['flag']: 1}.items():
            t, a = fijar_param(t, k, scad(v)); ant.setdefault(k, a)
    pp.write_text(t)
    if not simulado(ctx):
        for p in _sel(e, cfg):
            for cmd in cfg['piezas'][p].get('emitir', []): subprocess.run([python()] + cmd, cwd=str(r), check=True, capture_output=True)
    return dict(piezas_activas=_activos(t, cfg), anteriores=ant)
def deshacer(e, ctx):
    r = raiz(ctx); cfg = _cfg(e, ctx); pp = proy(ctx).params; t = pp.read_text()
    for p in _sel(e, cfg): t, _ = fijar_param(t, cfg['piezas'][p]['flag'], '0')
    pp.write_text(t)
    return dict(piezas_activas=_activos(t, cfg), anteriores={})
