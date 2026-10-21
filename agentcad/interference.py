"""check_interference: volumen de interferencia de una pieza con sus vecinas del ensamblaje (manifold3d), en una pose.
Poses, pares exentos, categorías excluidas y umbral se declaran en agentcad.toml ([poses], [interferencia]); el ensamblaje es un JSON (rutas.ensamblaje)."""
import json
from pathlib import Path
import numpy as np
from . import config, geom
from .geom import ErrorHerramienta, r4
import fnmatch
axis_rotation = geom.rotacion_eje

UMBRAL_MM3 = 0.1      # umbral por defecto; configurable en [interferencia].umbral_mm3

def volumen_interferencia(a, b):
    """Volumen (mm3) de la intersección de dos Manifold."""
    return abs(float((a ^ b).volume()))

def _exento(ida, idb):
    """Pares que encajan por diseño (p. ej. un tornillo en su alojamiento): [interferencia].exentos = [[patron_a, patron_b], ...] (fnmatch, sin orden)."""
    for pa, pb in config.proyecto()['interferencia'].get('exentos', []):
        if (fnmatch.fnmatch(ida, pa) and fnmatch.fnmatch(idb, pb)) or (fnmatch.fnmatch(ida, pb) and fnmatch.fnmatch(idb, pa)): return True
    return False

def _angulos(pose):
    if pose is None: return 'neutra', {}
    if isinstance(pose, str):
        poses = config.proyecto().poses
        if pose not in poses: raise ErrorHerramienta('pose_desconocida', f'poses disponibles: {sorted(poses)}')
        return pose, dict(poses[pose])
    if isinstance(pose, dict):
        for k, v in pose.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)): raise ErrorHerramienta('pose_invalida', f'ángulo no numérico en {k}')
        return 'personalizada', {k: float(v) for k, v in pose.items()}
    raise ErrorHerramienta('pose_invalida', 'pose debe ser nombre o diccionario de ángulos')

def check_interference(part, pose=None, umbral_mm3=None):
    if umbral_mm3 is None: umbral_mm3 = config.proyecto()['interferencia'].get('umbral_mm3', UMBRAL_MM3)
    try:
        r = geom.resolver(part); nombre_pose, ang = _angulos(pose)
    except ErrorHerramienta as e: return e.como_dict()
    pr = config.proyecto(); cfg = pr['interferencia']; fa = pr.ensamblaje
    if not fa or not fa.is_file():
        return dict(estado='ok', pieza=r['nombre'], pose=nombre_pose, veredicto='no_evaluable', interferencias=[], volumen_total_mm3=0.0, umbral_mm3=umbral_mm3,
                    pares_probados=0, nivel_validacion='digital', motivo='no hay ensamblaje configurado (rutas.ensamblaje en agentcad.toml): sin vecinas que comprobar')
    data = json.loads(fa.read_text())
    modulo = r['modulo']
    if not any(Path(p['file']).stem == modulo for p in data['parts']):
        return dict(estado='ok', pieza=r['nombre'], pose=nombre_pose, veredicto='no_evaluable', interferencias=[], volumen_total_mm3=0.0,
                    umbral_mm3=umbral_mm3, pares_probados=0, nivel_validacion='digital', motivo='la pieza no figura en el ensamblaje: sin vecinas que comprobar')
    ent = []
    for p in data['parts']:
        if p.get('group') in cfg['excluir_grupos'] or p.get('category') in cfg['excluir_categorias']: continue
        propia = Path(p['file']).stem == modulo
        ruta = r['ruta'] if propia else pr.raiz / p['file']
        m = geom.cargar(ruta); mat = np.array(p['matrix']).reshape(4, 4).T
        for j in reversed(data.get('joints', [])):
            if p['group'] in j.get('groups', []) or p['id'] in j.get('parts', []): mat = axis_rotation(j['pivot'], j['axis'], ang.get(j['id'], 0)) @ mat
        v = geom.transformar(m.vertices, mat)
        ent.append(dict(id=p['id'], propia=propia, malla=m, mat=mat, bb=np.array([v.min(0), v.max(0)]), v=v))
    propias = [e for e in ent if e['propia']]
    inter, no_eval, pares = [], [], 0
    cache = {}
    def solido(e):
        if e['id'] not in cache:
            m = e['malla']; cache[e['id']] = None
            if m.is_watertight:
                import manifold3d as M
                mf = M.Manifold(M.Mesh(vert_properties=e['v'].astype(np.float32), tri_verts=np.asarray(m.faces, np.uint32)))
                if mf.volume() > 0: cache[e['id']] = mf
        return cache[e['id']]
    for a in propias:
        for b in ent:
            if b['propia'] or _exento(a['id'], b['id']): continue
            if not np.all(np.minimum(a['bb'][1], b['bb'][1]) - np.maximum(a['bb'][0], b['bb'][0]) > .02): continue
            ma, mb = solido(a), solido(b)
            if ma is None or mb is None:
                no_eval.append(b['id'] if mb is None else a['id']); continue
            pares += 1; vol = volumen_interferencia(ma, mb)
            if vol > 0: inter.append(dict(con=b['id'], instancia=a['id'], volumen_mm3=r4(vol)))
    inter = sorted([i for i in inter if i['volumen_mm3'] > umbral_mm3], key=lambda d: -d['volumen_mm3'])
    tot = sum(i['volumen_mm3'] for i in inter)
    return dict(estado='ok', pieza=r['nombre'], pose=nombre_pose, angulos=ang, veredicto='interfiere' if inter else 'sin_interferencia',
                interferencias=inter, volumen_total_mm3=r4(tot), umbral_mm3=umbral_mm3, pares_probados=pares,
                no_evaluables=sorted(set(no_eval)), nivel_validacion='digital',
                limites=['poses discretas, sin volumen barrido', 'envolventes de hardware nominales', 'una malla cerrada no prueba encaje ni tolerancias'])
