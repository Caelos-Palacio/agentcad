"""describe_part: descripción medida de una pieza (caras, agujeros cilíndricos, bbox, volumen, masa, componentes, zonas protegidas, vecinas)."""
import json
from pathlib import Path
import numpy as np, trimesh
from . import config, geom
from .geom import ErrorHerramienta, r4

EJES = 'xyz'

def _ajuste_circulo(p2):
    A = np.c_[2 * p2, np.ones(len(p2))]; b = (p2 ** 2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = sol[:2]; r = float(np.sqrt(max(sol[2] + c @ c, 0)))
    return c, r, float(np.abs(np.hypot(*(p2 - c).T) - r).max())

def cilindros(mesh, min_segmentos=8, cobertura_min=330.0):
    """Superficies cilíndricas con eje paralelo a x, y o z. Devuelve (agujeros, salientes, arcos)."""
    ag, sal, arcos = [], [], []
    for ax in range(3):
        lat = np.nonzero(np.abs(mesh.face_normals[:, ax]) < 0.2)[0]
        if len(lat) < 3: continue
        mask = np.zeros(len(mesh.faces), bool); mask[lat] = True
        adj = mesh.face_adjacency[mask[mesh.face_adjacency].all(1)]
        import scipy.sparse as sp, scipy.sparse.csgraph as cg
        g = sp.coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(len(mesh.faces),) * 2)
        _, lab = cg.connected_components(g, directed=False)
        o = [i for i in range(3) if i != ax]
        for L in np.unique(lab[lat]):
            f = np.nonzero((lab == L) & mask)[0]
            if len(f) < 3: continue
            nd = np.unique(np.round(mesh.face_normals[f][:, o], 2), axis=0)
            if len(nd) < min_segmentos: continue                    # un hexágono (6 caras planas) no es un cilindro
            v = mesh.vertices[np.unique(mesh.faces[f])]
            c, r, res = _ajuste_circulo(v[:, o])
            if res > max(0.02 * r, 0.03) or r < 0.2: continue
            ang = np.sort(np.degrees(np.arctan2(v[:, o[1]] - c[1], v[:, o[0]] - c[0])))
            gaps = np.diff(np.r_[ang, ang[0] + 360]); cob = 360.0 - gaps.max()
            ctr = mesh.triangles_center[f][:, o] - c; nrm = mesh.face_normals[f][:, o]
            interior = float(((ctr * nrm).sum(1) < 0).mean()) > 0.5   # la normal apunta al eje: material rodea el hueco
            cen = [0.0] * 3; cen[o[0]], cen[o[1]] = c; z0, z1 = float(v[:, ax].min()), float(v[:, ax].max())
            d = dict(eje=EJES[ax], centro_mm=[r4(cen[o[0]]) if i == o[0] else r4(cen[o[1]]) if i == o[1] else None for i in range(3)],
                     radio_mm=r4(r), diametro_mm=r4(2 * r), segmentos=int(len(nd)), residuo_mm=r4(res),
                     intervalo_eje_mm=[r4(z0), r4(z1)], profundidad_mm=r4(z1 - z0),
                     recorre_bbox=bool(abs(z0 - mesh.bounds[0][ax]) < 1e-3 and abs(z1 - mesh.bounds[1][ax]) < 1e-3))
            d['centro_mm'] = [x for x in d['centro_mm']]   # None en la coordenada del eje
            if cob < cobertura_min: d['cobertura_deg'] = r4(cob); arcos.append(d)
            else: (ag if interior else sal).append(d)
    key = lambda d: (d['eje'], d['radio_mm'], d['intervalo_eje_mm'])
    return sorted(ag, key=key), sorted(sal, key=key), sorted(arcos, key=key)

def caras_planas(mesh, n=6):
    nn = np.round(mesh.face_normals, 3) + 0.0; off = np.round((mesh.triangles_center * mesh.face_normals).sum(1) / 0.05) * 0.05
    grupos = {}
    for i in range(len(mesh.faces)):
        k = (tuple(nn[i]), round(float(off[i]), 2)); grupos.setdefault(k, []).append(i)
    out = []
    for (nor, o), idx in grupos.items():
        a = float(mesh.area_faces[idx].sum())
        out.append(dict(normal=list(nor), desplazamiento_mm=o, area_mm2=r4(a), caras=len(idx)))
    return sorted(out, key=lambda d: -d['area_mm2'])[:n]

def zonas_protegidas(modulo):
    """Zonas protegidas de la pieza desde el archivo `rutas.zonas` de agentcad.toml (JSON: {parts: {<pieza>: {nondesignable_add, void_add, keep_free_tool_volumes}}})."""
    f = config.proyecto().zonas
    base = dict(fuente=str(f.name) if f else None, total=0, zonas=[])
    if not f or not f.is_file(): return dict(base, disponible=False, nota='no hay archivo de zonas protegidas configurado (rutas.zonas en agentcad.toml)')
    try: p = json.loads(f.read_text())['parts'].get(modulo)
    except Exception: p = None
    if not p: return dict(base, disponible=False, nota=f'la pieza no figura en {f.name}')
    zs = []
    for clave in ('nondesignable_add', 'void_add', 'keep_free_tool_volumes'):
        for z in p.get(clave, []):
            zs.append(dict(lista=clave, id=z.get('id'), tipo=z.get('type'), clase=z.get('kind'), motivo=z.get('reason')))
    return dict(base, disponible=True, total=len(zs), zonas=zs[:40], truncado=len(zs) > 40)

def vecinas(modulo, mesh, radio_mm=10.0):
    """Piezas del ensamblaje (rutas.ensamblaje, pose neutra) a menos de radio_mm de la pieza; distancia mínima exacta (FCL)."""
    pr = config.proyecto(); f = pr.ensamblaje
    if not f or not f.is_file(): return [], 'no hay ensamblaje configurado (rutas.ensamblaje en agentcad.toml)'
    asm = json.loads(f.read_text())
    inst = [p for p in asm['parts'] if Path(p['file']).stem == modulo]
    if not inst: return [], 'la pieza no está en el ensamblaje'
    from collections import OrderedDict
    res = OrderedDict()
    for ins in inst:
        Mw = np.array(ins['matrix']).reshape(4, 4).T
        wm = mesh.copy(); wm.apply_transform(Mw); lo, hi = wm.bounds
        for p in asm['parts']:
            if p is ins or Path(p['file']).stem == modulo: continue
            om = geom.cargar(pr.raiz / p['file']); Mo = np.array(p['matrix']).reshape(4, 4).T
            om.apply_transform(Mo); a, b = om.bounds
            gap = np.maximum(np.maximum(a - hi, lo - b), 0)
            if np.linalg.norm(gap) > radio_mm: continue
            cm = trimesh.collision.CollisionManager(); cm.add_object('o', om)
            d = float(cm.min_distance_single(wm))
            cur = res.get(p['id'])
            if cur is None or d < cur['distancia_min_mm']:
                res[p['id']] = dict(id=p['id'], archivo=p['file'], categoria=p.get('category'), instancia=ins['id'], distancia_min_mm=r4(max(d, 0.0)))
    return sorted(res.values(), key=lambda d: d['distancia_min_mm']), None

def describe_part(part, perfil=None, radio_vecinas_mm=10.0):
    try: r = geom.resolver(part)
    except ErrorHerramienta as e: return e.como_dict()
    mesh = geom.cargar(r['ruta'])
    prof = geom.perfil(r['modulo'], perfil)
    mp = geom.masa_g(r['ruta'], prof)
    ag, sal, arcos = cilindros(mesh)
    out = dict(estado='ok', pieza=r['nombre'], origen=r['origen'], archivo=str(r['ruta']),
               bbox_mm=dict(min=[r4(x) for x in mesh.bounds[0]], max=[r4(x) for x in mesh.bounds[1]], tamano=[r4(x) for x in mesh.extents]),
               volumen_mm3=r4(abs(mesh.volume)), area_mm2=r4(mp['area_mm2']), malla_cerrada=bool(mesh.is_watertight),
               masa_estimada_g=r4(mp['masa_g']), perfil_impresion=prof, componentes=int(len(mesh.split(only_watertight=False))),
               caras_principales=caras_planas(mesh), agujeros_cilindricos=ag, salientes_cilindricos=sal, arcos_cilindricos=arcos,
               zonas_protegidas=zonas_protegidas(r['modulo']), nivel_validacion='digital',
               limites=['cilindros solo con eje paralelo a x, y o z', 'masa = estimación con el perfil de impresión y el material de agentcad.toml, no pesada'])
    try: v, nota = vecinas(r['modulo'], mesh, radio_vecinas_mm)
    except Exception as e: v, nota = [], f'vecinas no calculadas: {type(e).__name__}'
    out['vecinas'] = v
    if nota: out['nota_vecinas'] = nota
    return out
