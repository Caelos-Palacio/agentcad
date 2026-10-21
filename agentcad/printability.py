"""check_printability: pared/nervio mínimo medido, voladizos > 45°, islas y puentes en la orientación de impresión (perfil de impresión de agentcad.toml).
La pared se mide con la transformada de distancia sobre vóxeles FINOS (paso <= umbral/5), no con el paso de 1 mm del FEM:
así un nervio de 0,67 mm no pasa desapercibido. Reutiliza fem3d.voxelize_tris. Comprobación digital: no prueba que la impresora lo logre."""
import numpy as np
import scipy.ndimage as ndi
from . import config, geom
from .geom import ErrorHerramienta, r4
from .fem3d import voxelize_tris      # respaldo para mallas no variedad
from PIL import Image, ImageDraw
import manifold3d as M

UMBRALES = dict(pared_min_mm=1.2, voladizo_max_deg=45.0, voladizo_frac_max=0.02, islas_max=0, puente_max_mm=10.0, isla_min_mm2=0.5)
MAX_VOXELES = 15_000_000

def _manifold(verts, caras):
    mf = M.Manifold(M.Mesh(vert_properties=np.asarray(verts, np.float32), tri_verts=np.asarray(caras, np.uint32)))
    return None if (mf.status() != M.Error.NoError or mf.is_empty()) else mf

def _capa(mf, z, lo, nx, ny, q):
    """Máscara (ny,nx) de la sección horizontal a altura z con píxeles de lado q (centros en lo + (i+.5) q); relleno par-impar por anillo (PIL)."""
    img = np.zeros((ny, nx), bool)
    for ring in mf.slice(z).to_polygons():
        r = np.asarray(ring, float)
        if abs(0.5 * np.sum(r[:, 0] * np.roll(r[:, 1], -1) - np.roll(r[:, 0], -1) * r[:, 1])) < 2 * q * q: continue   # anillo degenerado (área ~0): PIL lo dibujaría como una línea de 1 píxel
        c = (r - lo[:2]) / q - .5
        x0, y0 = np.floor(c.min(0)).astype(int) - 1; x1, y1 = np.ceil(c.max(0)).astype(int) + 2
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, nx), min(y1, ny)
        if x1 <= x0 or y1 <= y0: continue
        im = Image.new('L', (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(im).polygon([(a - x0, b - y0) for a, b in c], fill=1)
        img[y0:y1, x0:x1] ^= np.asarray(im, bool)
    return img

def voxelizar(mf, verts, caras, p, lo, shape):
    """Ocupación en centros de vóxel por cortes horizontales de manifold3d (robusto ante aristas coplanares)."""
    if mf is None: return voxelize_tris(verts[caras], p, lo, shape), 'voxelize_tris'
    nx, ny, nz = shape; occ = np.zeros(shape, bool); zmin, zmax = verts[:, 2].min(), verts[:, 2].max()
    for k in range(nz):
        z = lo[2] + (k + .5 + 0.0137) * p      # desplazamiento mínimo: evita cortar justo sobre una cara plana
        if zmin <= z <= zmax: occ[:, :, k] = _capa(mf, z, lo, nx, ny, p).T
    return occ, 'cortes_manifold'

def pared_en_plano(mf, occ, p, lo, esc, umbral, long_min_mm=0.5):
    """Espesor en el plano de capa (perímetros/nervios): EDT 2D por capa con píxel p/esc. Solo recalcula si la sección cambia.
    Un píxel «fino» (espesor < umbral) solo cuenta si (1) su cresta fina mide >= long_min_mm (descarta motas de 1 píxel) y (2) PERSISTE en la capa
    de arriba o de abajo (descarta las franjas finas que deja un corte casi tangente a una superficie curva o inclinada, p. ej. la última capa
    de un cilindro tumbado). Devuelve (min_mm, lista de (x, y, z, espesor) de puntos finos persistentes)."""
    nx, ny, nz = occ.shape; q = p / esc
    gruesa = np.inf; capas = [None] * nz; ultimo = None; prev = None
    st = np.ones((3, 3), bool)
    for k in range(nz):
        col = occ[:, :, k]
        if not col.any(): ultimo = None; continue
        clave = col.tobytes()
        if clave == ultimo: capas[k] = prev; continue
        ultimo = clave
        if mf is not None and esc > 1: img = _capa(mf, lo[2] + (k + .5 + 0.0137) * p, lo, nx * esc, ny * esc, q)
        else: img = col.T
        img = np.pad(img, 1)
        edt = ndi.distance_transform_edt(img, sampling=q)
        ridge = img & (ndi.maximum_filter(edt, size=3) <= edt + 1e-9)
        esp = 2 * edt - 0.5 * q
        fino = ridge & (esp < umbral)
        resto = ridge & ~fino
        if resto.any(): gruesa = min(gruesa, float(esp[resto].min()))
        puntos = []
        if fino.any():
            lab, n = ndi.label(fino, structure=st); tam = np.bincount(lab.ravel(), minlength=n + 1)
            for L in np.nonzero(tam * q >= long_min_mm)[0]:
                if L == 0: continue
                ij = np.argwhere(lab == L) - 1
                for j, i in ij[:400]: puntos.append((int(i), int(j), float(esp[j + 1, i + 1])))
        celdas = {(i // esc, j // esc) for i, j, _e in puntos}
        prev = capas[k] = dict(k=k, puntos=puntos, celdas=celdas)
    def vecina(c, ci, cj):
        return c is not None and any((ci + a, cj + b) in c['celdas'] for a in (-1, 0, 1) for b in (-1, 0, 1))
    persist = []
    for k in range(nz):
        c = capas[k]
        if c is None or not c['puntos']: continue
        ant = capas[k - 1] if k > 0 and capas[k - 1] is not c else None
        sig = capas[k + 1] if k + 1 < nz and capas[k + 1] is not c else None
        rep = (k > 0 and capas[k - 1] is c) or (k + 1 < nz and capas[k + 1] is c)      # la sección se repite en capas contiguas: persiste por construcción
        if c['k'] != k: continue
        for i, j, e in c['puntos']:
            if rep or vecina(ant, i // esc, j // esc) or vecina(sig, i // esc, j // esc):
                persist.append((lo[0] + (i + .5) * q, lo[1] + (j + .5) * q, lo[2] + (k + .5) * p, e))
    mejor = min([gruesa] + [t[3] for t in persist])
    return (float(mejor) if np.isfinite(mejor) else 0.0), persist

def espesor_vertical(occ, p, umbral, tope=6.0):
    """Espesor en Z de losas/techos/suelos: longitud de las rachas verticales de material, en regiones de losa (>= 2·umbral de ancho).
    Devuelve el mínimo (mm) o None si no hay losas más finas que `tope`."""
    o = np.pad(occ, ((0, 0), (0, 0), (1, 1))).astype(np.int8); d = np.diff(o, axis=2)
    ini = np.argwhere(d == 1); fin = np.argwhere(d == -1)
    long_mm = (fin[:, 2] - ini[:, 2]) * p
    mapa = np.full(occ.shape[:2], np.inf)
    np.minimum.at(mapa, (ini[:, 0], ini[:, 1]), long_mm)
    r = max(1, int(round(umbral / p)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]; disco = (xx ** 2 + yy ** 2) <= r * r
    region = ndi.binary_erosion(mapa < tope, structure=disco)
    return float(mapa[region].min()) if region.any() else None

def _orientar(mesh, rot):
    R = geom.rotar(*rot)[:3, :3]
    v = mesh.vertices @ R.T; dz = v[:, 2].min(); v = v - np.array([0, 0, dz])
    return v, R, dz

def _voladizo(mesh, R, vz, ang_max):
    n = mesh.face_normals @ R.T
    zf = vz[mesh.faces].max(1)      # solo se excluyen las caras enteras sobre la cama
    mal = (n[:, 2] < -np.cos(np.radians(ang_max)) - 1e-6) & (zf > 0.05)
    ar = mesh.area_faces
    a = float(ar[mal].sum())
    ang = float(90.0 - np.degrees(np.arccos(np.clip(-n[mal, 2], -1, 1))).min()) if mal.any() else 0.0
    return dict(area_mm2=r4(a), fraccion_area=r4(a / ar.sum()), angulo_max_deg=r4(ang), caras=int(mal.sum()))

def _capa0(occ):
    return int(np.argmax(occ.any((0, 1)))) if occ.any() else 0

def _islas(occ, p, min_mm2):
    n = 0; st = np.ones((3, 3), bool)
    for k in range(_capa0(occ) + 1, occ.shape[2]):
        lab, nl = ndi.label(occ[:, :, k], structure=st)
        if nl == 0: continue
        bajo = ndi.binary_dilation(occ[:, :, k - 1], structure=st)
        tocan = np.unique(lab[bajo & (lab > 0)])
        areas = np.bincount(lab.ravel(), minlength=nl + 1) * p * p
        for L in range(1, nl + 1):
            if L not in tocan and areas[L] >= min_mm2: n += 1
    return n

def _puente(occ, p):
    dmax = 0.0
    for k in range(_capa0(occ) + 1, occ.shape[2]):
        U = occ[:, :, k] & ~occ[:, :, k - 1]
        if U.sum() < 4: continue
        d = ndi.distance_transform_edt(~occ[:, :, k - 1], sampling=p)
        dmax = max(dmax, float(d[U].max()))
    return 2 * dmax      # cota superior de la luz (un voladizo a un solo lado cuenta como luz doble: conservador)

def check_printability(part, paso_mm=None, orientacion_deg=None, umbrales=None):
    try:
        r = geom.resolver(part)
        if paso_mm is not None and (isinstance(paso_mm, bool) or not isinstance(paso_mm, (int, float)) or not 0.05 <= paso_mm <= 2.0):
            raise ErrorHerramienta('parametro_invalido', 'paso_mm debe estar entre 0.05 y 2.0')
    except ErrorHerramienta as e: return e.como_dict()
    u = dict(UMBRALES); u.update(umbrales or {})
    mesh = geom.cargar(r['ruta']); prof = geom.perfil(r['modulo'])
    rot = list(orientacion_deg) if orientacion_deg is not None else list(prof.get('rot', [0, 0, 0]))
    soporte = prof.get('support', 'no') if orientacion_deg is None else 'no'
    v, R, dz = _orientar(mesh, rot)
    ext = v.max(0) - v.min(0)
    p = paso_mm if paso_mm else u['pared_min_mm'] / 5
    p = max(p, (float(np.prod(ext + 4 * p)) / MAX_VOXELES) ** (1 / 3)) if not paso_mm else p
    p = float(round(p, 4))
    lo = v.min(0) - 2 * p; shape = tuple(np.ceil((ext + 4 * p) / p).astype(int))
    if np.prod(shape) > 4 * MAX_VOXELES:
        return dict(estado='error', codigo='demasiado_grande', mensaje=f'{int(np.prod(shape))} vóxeles a paso {p}; sube paso_mm')
    mf = _manifold(v, mesh.faces)
    occ, metodo_vox = voxelizar(mf, v, mesh.faces, p, lo, shape)
    esc = 1 if paso_mm else 4          # con paso explícito se emula esa resolución; en automático el plano se afina a p/4
    while esc > 1 and (shape[0] * esc) * (shape[1] * esc) > 12_000_000: esc -= 1
    plano, cand = pared_en_plano(mf, occ, p, lo, esc, u['pared_min_mm'])
    vert = espesor_vertical(occ, p, u['pared_min_mm'])
    pared = min(plano, vert) if vert is not None else plano
    pts = []
    celdas = {}
    for x, y, z, e in sorted(cand, key=lambda t: t[3]):
        c = (round(x / 2), round(y / 2), round(z / 2))
        if c not in celdas: celdas[c] = (x, y, z, e)
    for x, y, z, e in list(celdas.values())[:8]:
        q = R.T @ (np.array([x, y, z]) + np.array([0, 0, dz]))      # marco de impresión -> marco de la pieza
        pts.append(dict(centro_mm=[r4(t) for t in q], espesor_mm=r4(e), tipo='en_plano'))
    if vert is not None and vert < u['pared_min_mm']: pts.append(dict(espesor_mm=r4(vert), tipo='vertical'))
    vol = _voladizo(mesh, R, v[:, 2], u['voladizo_max_deg'])
    n_islas = _islas(occ, p, u['isla_min_mm2']); luz = _puente(occ, p)
    tol = p / esc          # un píxel del plano (0,06 mm): un nervio nominal de 1,2 mm se mide 1,17
    resuelve = p <= u['pared_min_mm'] / 3 + 1e-9
    inc = p
    perm_vol = soporte.startswith('no') or orientacion_deg is not None
    nota_sop = {} if perm_vol else dict(nota='la pieza declara soportes en PRINT: valor informativo, los soportes lo cubren')
    crit = [dict(id='pared_min_mm', valor=r4(pared), umbral=u['pared_min_mm'], op='>=', cumple=bool(pared + tol >= u['pared_min_mm']), margen=r4(pared - u['pared_min_mm']), tolerancia_medida_mm=r4(tol)),
            dict(id='voladizo_frac', valor=vol['fraccion_area'], umbral=u['voladizo_frac_max'], op='<=', cumple=bool(vol['fraccion_area'] <= u['voladizo_frac_max'] or not perm_vol), margen=r4(u['voladizo_frac_max'] - vol['fraccion_area']), **nota_sop),
            dict(id='islas', valor=n_islas, umbral=u['islas_max'], op='<=', cumple=bool(n_islas <= u['islas_max'] or not perm_vol), margen=u['islas_max'] - n_islas, **nota_sop),
            dict(id='puente_mm', valor=r4(luz), umbral=u['puente_max_mm'], op='<=', cumple=bool(luz <= u['puente_max_mm'] or not perm_vol), margen=r4(u['puente_max_mm'] - luz), **nota_sop)]
    if not all(c['cumple'] for c in crit): ver = 'no_cumple'
    elif not resuelve: ver = 'indeterminado'
    else: ver = 'cumple'
    return dict(estado='ok', pieza=r['nombre'], veredicto=ver, pared_min_mm=r4(pared), criterios=crit, umbrales=u,
                voladizo=vol, islas=dict(numero=n_islas), puente=dict(luz_estimada_mm=r4(luz)), puntos_finos=pts,
                orientacion_deg=rot, soporte_declarado=soporte,
                fidelidad=dict(paso_mm=p, paso_en_plano_mm=r4(p / esc), espesor_vertical_min_mm=None if vert is None else r4(vert), voxelizado=metodo_vox, voxeles=int(np.prod(shape)), incertidumbre_mm=r4(p), resuelve_umbral=bool(resuelve),
                               nota='pared = min(2·EDT 2D por capa a paso/4 en el plano, rachas verticales en losas); error ≈ ±paso/4 en plano, ±paso en vertical; paso > umbral/3 => indeterminado si nada falla'),
                nivel_validacion='digital',
                limites=['no prueba la capacidad real de la impresora ni la adhesión de capas', 'puente = cota superior (2×distancia máxima al soporte)'])
