"""Bloque check_gcode: analiza un gcode ya laminado (Orca/Prusa-like) frente al perfil de máquina de `[gcode]` en agentcad.toml. Núcleo en agentcad/gcode.py."""
import json
from pathlib import Path
from ._base import raiz, proy, sim, huella_base
MANIFIESTO = dict(nombre='check_gcode', descripcion='Analiza un gcode: islas flotantes, puentes, voladizos, soportes sin cama, límites de cama/Z, temperaturas, caudal, inicio/fin.',
    entradas={'archivo': {'type': 'string', 'descripcion': 'ruta del gcode (relativa a la raíz del proyecto, o bajo una raíz permitida)'},
              'perfil': {'type': 'string', 'default': '', 'descripcion': 'perfil de máquina de [gcode.perfiles.<nombre>]; vacío = gcode.perfil'},
              'guardar': {'type': 'boolean', 'default': False, 'descripcion': 'escribe el detalle completo en JSON y devuelve su ruta'}},
    salidas={'ok': {'type': 'boolean'}, 'errores': {'type': 'integer'}, 'avisos': {'type': 'integer'}, 'capas': {'type': 'integer'},
             'islas': {'type': 'integer'}, 'puentes_largos': {'type': 'integer'}, 'voladizos': {'type': 'integer'}, 'soportes_sin_cama': {'type': 'integer'},
             'fuera_de_cama': {'type': 'integer'}, 'caudal_max': {'type': 'number', 'unidad': 'mm3/s'}, 'z_max': {'type': 'number', 'unidad': 'mm'},
             'masa_g': {'type': 'number', 'unidad': 'g'}, 'mensajes': {'type': 'array'}, 'detalle': {'type': 'string'}},
    precondiciones=['gcode existente bajo la raíz del proyecto', '[gcode] en agentcad.toml con perfil de máquina (cama_x_mm, cama_y_mm, z_max_mm obligatorios)'],
    efectos=['con guardar=true escribe <trabajo>/gcode_<nombre>.json'], ejemplo={'archivo': 'gcode/ejemplo.gcode'}, pesado=True, deshacible=False, determinista=True,
    honestidad='digital: analiza el gcode, no la pieza impresa; no prueba adhesión, puentes reales ni caudal de la boquilla. «deshacer» no aplica: el bloque solo lee')

def _perfil(ctx, nombre):
    g = proy(ctx)['gcode']; nombre = nombre or g.get('perfil', '')
    if not nombre: raise ValueError('check_gcode: sin perfil; declara [gcode] perfil = "<nombre>" y [gcode.perfiles.<nombre>] en agentcad.toml')
    pf = g.get('perfiles', {}).get(nombre)
    if pf is None: raise ValueError(f'check_gcode: perfil {nombre!r} no declarado; hay: {sorted(g.get("perfiles", {}))}')
    for k in ('cama_x_mm', 'cama_y_mm', 'z_max_mm'):
        if k not in pf: raise ValueError(f'check_gcode: falta {k} en [gcode.perfiles.{nombre}]')
    return nombre, pf, g

def _ruta(ctx, archivo):
    from .. import config
    r = raiz(ctx); p = Path(archivo); p = p if p.is_absolute() else r / p; p = p.resolve()
    if not any(p == q.resolve() or q.resolve() in p.parents for q in [r, *config.raices_permitidas()]): raise ValueError('check_gcode: la ruta debe estar bajo la raíz del proyecto o una raíz permitida')
    if not p.is_file(): raise FileNotFoundError(f'check_gcode: no existe {archivo}')
    return p

def huella(e, ctx):
    from .. import cache
    if (ctx or {}).get('simulado'): return dict(simulado=True)          # el modelo sintético se hashea aparte (sim.json)
    nombre, pf, g = _perfil(ctx, e.get('perfil', ''))
    return dict(gcode=cache.sha256_fichero(_ruta(ctx, e['archivo'])), perfil=nombre, **huella_base(ctx))

def _limites(pf):
    m = dict(max_volumetric_mm3_s='caudal_max_mm3_s', nozzle_temp_max='temp_boquilla_max', bed_temp_max='temp_cama_max', max_speed_mm_s='velocidad_max_mm_s',
             first_layer_speed='velocidad_primera_capa_mm_s', density='densidad_g_cm3')
    lim = {k: pf[v] for k, v in m.items() if v in pf}
    if pf.get('limites_rol'): lim['role_limits'] = dict(pf['limites_rol'])
    return lim

def ejecutar(e, ctx):
    from .. import gcode
    nombre, pf, g = _perfil(ctx, e.get('perfil', '')); p = _ruta(ctx, e['archivo'])
    res = gcode.analyze(p, dict(bed_x=pf['cama_x_mm'], bed_y=pf['cama_y_mm'], z_max=pf['z_max_mm']), _limites(pf), cell=g.get('celda_mm', 0.2),
                        filament_d=pf.get('diametro_filamento_mm', 1.75), require_start_end=pf.get('exigir_inicio_fin', True))
    ov = res['overhangs']; detalle = ''
    if e.get('guardar'):
        from .. import config
        d = config.trabajo_dir(); d.mkdir(parents=True, exist_ok=True); f = d / f'gcode_{p.stem}.json'; f.write_text(json.dumps(res, indent=1, default=str)); detalle = str(f)
    return dict(ok=res['ok'], errores=len(res['errors']), avisos=len(res['warnings']), capas=res['layers'], islas=len(res['floating_islands']),
                puentes_largos=sum(o['tipo'] == 'puente_largo' for o in ov), voladizos=sum(o['tipo'] == 'voladizo_fuerte' for o in ov),
                soportes_sin_cama=sum(s['tipo'] not in ('flotante_bajo', 'interior_tronco') for s in res['support_issues']),
                fuera_de_cama=len(res['out_of_bed_extrusion']) + len(res['out_of_bed_travel']), caudal_max=round(res['max_volumetric_mm3_s'], 3),
                z_max=round(res['max_z'], 3), masa_g=round(res['filament']['mass_g'], 2), mensajes=(res['errors'] + res['warnings'])[:6], detalle=detalle)

def simular(e, ctx):
    """Modelo SINTÉTICO: `gcode` de sim.json si existe (campos de las salidas), si no un gcode limpio inventado. No predice ningún laminado."""
    try: s = sim(ctx).get('gcode', {})
    except FileNotFoundError: s = {}
    base = dict(ok=True, errores=0, avisos=0, capas=10, islas=0, puentes_largos=0, voladizos=0, soportes_sin_cama=0, fuera_de_cama=0, caudal_max=5.0, z_max=2.0, masa_g=1.0,
                mensajes=['simulado: cifras sintéticas, no se ha leído ningún gcode'], detalle='')
    base.update({k: v for k, v in s.items() if k in base}); return base
