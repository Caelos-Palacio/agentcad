"""check_printability: pared/nervio mínimo medido, voladizos > 45°, islas y puentes en la orientación de impresión (perfil de impresión de agentcad.toml).
La pared se mide con la transformada de distancia sobre vóxeles FINOS (paso <= umbral/5), no con el paso de 1 mm del FEM:
así un nervio de 0,67 mm no pasa desapercibido. Reutiliza fem3d.voxelize_tris. Comprobación digital: no prueba que la impresora lo logre."""
import numpy as np
import scipy.ndimage as ndi
from . import config, geom, instr
from .geom import ErrorHerramienta, r4
from .fem3d import voxelize_tris      # respaldo para mallas no variedad
from PIL import Image, ImageDraw
import manifold3d as M

UMBRALES = dict(pared_min_mm=1.2, voladizo_max_deg=45.0, voladizo_frac_max=0.02, islas_max=0, puente_max_mm=10.0, isla_min_mm2=0.5)
# Severidad del material fino (fracción del volumen de la pieza con espesor local < pared_min_mm): por debajo de PUNTUAL es un detalle, hasta LOCALIZADA una zona, y por encima el diseño es fino.
FINO_PUNTUAL, FINO_LOCALIZADA = 0.005, 0.05
CAPA_CAMA_MM = 0.2      # altura de capa por defecto: las facetas enteras dentro de la primera capa están en la cama y no son voladizo

def severidad_fino(fraccion):
    return 'ninguna' if fraccion <= 0 else 'puntual' if fraccion < FINO_PUNTUAL else 'localizada' if fraccion < FINO_LOCALIZADA else 'extensa'

def normalizar_regiones(regiones):
    """support_regiones del perfil: lista de cajas [xmin, ymin, zmin, xmax, ymax, zmax] en el marco de la pieza (mm). Devuelve tuplas de floats o lanza parametro_invalido."""
    out = []
    try:
        for c in regiones or []:
            c = tuple(float(x) for x in c)
            if len(c) != 6 or not (c[0] < c[3] and c[1] < c[4] and c[2] < c[5]): raise ValueError(c)
            out.append(c)
    except (TypeError, ValueError) as e:
        raise ErrorHerramienta('parametro_invalido', f'support_regiones debe ser una lista de cajas [xmin,ymin,zmin,xmax,ymax,zmax] con min < max: {e}') from None
    return out

def _cajas_impresion(regiones, R, dz):
    """Cajas del marco de la pieza -> AABB en el marco de impresión (la caja girada se sustituye por su envolvente; conservador a favor de «cubierto»)."""
    out = []
    for x0, y0, z0, x1, y1, z1 in regiones:
        c = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]); q = c @ R.T - np.array([0, 0, dz])
        out.append((q.min(0), q.max(0)))
    return out

def _mascara_cubierta(shape, lo, p, cajas):
    """Máscara 3D de vóxeles cuyo centro cae dentro de alguna caja de soporte declarada."""
    m = np.zeros(shape, bool)
    for a, b in cajas:
        i0 = np.clip(np.ceil((a - lo) / p - .5 - 1e-9).astype(int), 0, shape); i1 = np.clip(np.floor((b - lo) / p - .5 + 1e-9).astype(int) + 1, 0, shape)
        m[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]] = True
    return m
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

@instr.medida('imprimibilidad_voxelizar')
def voxelizar(mf, verts, caras, p, lo, shape):
    """Ocupación en centros de vóxel por cortes horizontales de manifold3d (robusto ante aristas coplanares)."""
    if mf is None: return voxelize_tris(verts[caras], p, lo, shape), 'voxelize_tris'
    nx, ny, nz = shape; occ = np.zeros(shape, bool); zmin, zmax = verts[:, 2].min(), verts[:, 2].max()
    for k in range(nz):
        z = lo[2] + (k + .5 + 0.0137) * p      # desplazamiento mínimo: evita cortar justo sobre una cara plana
        if zmin <= z <= zmax: occ[:, :, k] = _capa(mf, z, lo, nx, ny, p).T
    return occ, 'cortes_manifold'

@instr.medida('imprimibilidad_pared_plano')
def pared_en_plano(mf, occ, p, lo, esc, umbral, long_min_mm=0.5):
    """Espesor en el plano de capa (perímetros/nervios): EDT 2D por capa con píxel p/esc. Solo recalcula si la sección cambia.
    Un píxel «fino» (espesor < umbral) solo cuenta si (1) su cresta fina mide >= long_min_mm (descarta motas de 1 píxel) y (2) PERSISTE en la capa
    de arriba o de abajo (descarta las franjas finas que deja un corte casi tangente a una superficie curva o inclinada, p. ej. la última capa
    de un cilindro tumbado). Devuelve (min_mm, lista de (x, y, z, espesor) de puntos finos persistentes, volumen_fino_mm3 = suma de espesor x q x p de esas crestas persistentes)."""
    nx, ny, nz = occ.shape; q = p / esc
    gruesa = np.inf; capas = [None] * nz; ultimo = None; prev = None
    st = np.ones((3, 3), bool)
    for k in range(nz):
        col = occ[:, :, k]
        if not col.any(): ultimo = None; continue
        clave = col.tobytes()
        if clave == ultimo: capas[k] = prev; prev['mult'] += 1; continue
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
        if fino.any():
            ok = (tam[lab] * q >= long_min_mm) & (lab > 0)
            jj, ii = np.nonzero(ok); ii = ii - 1; jj = jj - 1; ee = esp[jj + 1, ii + 1]
        else: ii = jj = ee = np.zeros(0)
        prev = capas[k] = dict(k=k, puntos=puntos, celdas=celdas, ii=ii.astype(int), jj=jj.astype(int), ee=np.asarray(ee, float), mult=1)
    def vecina(c, ci, cj):
        return c is not None and any((ci + a, cj + b) in c['celdas'] for a in (-1, 0, 1) for b in (-1, 0, 1))
    persist = []; vol_fino = 0.0
    for k in range(nz):
        c = capas[k]
        if c is None or not c['puntos']: continue
        ant = capas[k - 1] if k > 0 and capas[k - 1] is not c else None
        sig = capas[k + 1] if k + 1 < nz and capas[k + 1] is not c else None
        rep = (k > 0 and capas[k - 1] is c) or (k + 1 < nz and capas[k + 1] is c)      # la sección se repite en capas contiguas: persiste por construcción
        if c['k'] != k: continue
        if len(c['ee']):       # volumen del material fino persistente: espesor x largo de cresta (q) x altura de capa (p); una sección repetida pesa tantas capas como se repite
            if c['mult'] > 1: pers = np.ones(len(c['ee']), bool)
            else:
                pers = np.zeros(len(c['ee']), bool)
                for v in (ant, sig):
                    if v is None or not v['celdas']: continue
                    mk = np.zeros((nx + 2, ny + 2), bool)
                    for ci, cj in v['celdas']: mk[ci + 1, cj + 1] = True
                    mk = ndi.binary_dilation(mk, structure=st)
                    pers |= mk[c['ii'] // esc + 1, c['jj'] // esc + 1]
            vol_fino += float(c['ee'][pers].sum()) * q * p * c['mult']
        for i, j, e in c['puntos']:
            if rep or vecina(ant, i // esc, j // esc) or vecina(sig, i // esc, j // esc):
                persist.append((lo[0] + (i + .5) * q, lo[1] + (j + .5) * q, lo[2] + (k + .5) * p, e))
    mejor = min([gruesa] + [t[3] for t in persist])
    return (float(mejor) if np.isfinite(mejor) else 0.0), persist, vol_fino

@instr.medida('imprimibilidad_pared_vertical')
def espesor_vertical(occ, p, umbral, tope=6.0):
    """Espesor en Z de losas/techos/suelos: longitud de las rachas verticales de material, en regiones de losa (>= 2·umbral de ancho).
    Devuelve (mínimo_mm o None si no hay losas más finas que `tope`, volumen_mm3 de las columnas de losa con racha < umbral)."""
    o = np.pad(occ, ((0, 0), (0, 0), (1, 1))).astype(np.int8); d = np.diff(o, axis=2)
    ini = np.argwhere(d == 1); fin = np.argwhere(d == -1)
    long_mm = (fin[:, 2] - ini[:, 2]) * p
    mapa = np.full(occ.shape[:2], np.inf)
    np.minimum.at(mapa, (ini[:, 0], ini[:, 1]), long_mm)
    r = max(1, int(round(umbral / p)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]; disco = (xx ** 2 + yy ** 2) <= r * r
    region = ndi.binary_erosion(mapa < tope, structure=disco)
    if not region.any(): return None, 0.0
    fina = region & (mapa < umbral)
    return float(mapa[region].min()), float(mapa[fina].sum()) * p * p

def _orientar(mesh, rot):
    R = geom.rotar(*rot)[:3, :3]
    v = mesh.vertices @ R.T; dz = v[:, 2].min(); v = v - np.array([0, 0, dz])
    return v, R, dz

@instr.medida('imprimibilidad_voladizo')
def _voladizo(mesh, R, vz, ang_max, cama_mm=CAPA_CAMA_MM, cajas=()):
    """Área de caras que miran hacia abajo más de ang_max. Se excluyen (1) las caras ENTERAS dentro de la primera capa (z <= max(0,05 mm, cama_mm)): están en la cama,
    aunque sean casi horizontales, y (2) las caras cuyo centroide cae dentro de una zona de soporte declarada (`cajas`, marco de impresión)."""
    n = mesh.face_normals @ R.T
    zf = vz[mesh.faces].max(1)
    cen = vz[mesh.faces].mean(1)
    mal = (n[:, 2] < -np.cos(np.radians(ang_max)) - 1e-6) & (zf > max(0.05, cama_mm))
    ar = mesh.area_faces
    sin_cubrir = mal.copy()
    if cajas:
        c3 = (mesh.vertices @ R.T)[mesh.faces].mean(1); c3[:, 2] = cen
        for a, b in cajas: sin_cubrir &= ~np.all((c3 >= a - 1e-6) & (c3 <= b + 1e-6), axis=1)
    a_tot = float(ar[mal].sum()); a = float(ar[sin_cubrir].sum())
    ang = float(90.0 - np.degrees(np.arccos(np.clip(-n[sin_cubrir, 2], -1, 1))).min()) if sin_cubrir.any() else 0.0
    return dict(area_mm2=r4(a), fraccion_area=r4(a / ar.sum()), angulo_max_deg=r4(ang), caras=int(sin_cubrir.sum()), area_sin_soporte_mm2=r4(a_tot), area_cubierta_mm2=r4(a_tot - a))

def _capa0(occ):
    return int(np.argmax(occ.any((0, 1)))) if occ.any() else 0

def _capas_cama(p, cama_mm): return max(1, int(np.ceil(cama_mm / p - 1e-9)))

@instr.medida('imprimibilidad_islas')
def _islas(occ, p, min_mm2, cub=None, cama_mm=CAPA_CAMA_MM):
    """(islas sin cubrir, islas cubiertas por una zona de soporte declarada). Una isla está cubierta si >= 50 % de su huella cae en `cub` (máscara 3D).
    No se analizan las capas dentro de la primera altura de capa sobre la cama (`cama_mm`): ahí una faceta casi horizontal escalona la huella sin ser una isla."""
    n = 0; nc = 0; st = np.ones((3, 3), bool)
    for k in range(_capa0(occ) + 1 + _capas_cama(p, cama_mm), occ.shape[2]):
        lab, nl = ndi.label(occ[:, :, k], structure=st)
        if nl == 0: continue
        bajo = ndi.binary_dilation(occ[:, :, k - 1], structure=st)
        tocan = np.unique(lab[bajo & (lab > 0)])
        areas = np.bincount(lab.ravel(), minlength=nl + 1) * p * p
        en_cub = np.bincount(lab[cub[:, :, k]].ravel(), minlength=nl + 1) if cub is not None else None
        tam = np.bincount(lab.ravel(), minlength=nl + 1)
        for L in range(1, nl + 1):
            if L in tocan or areas[L] < min_mm2: continue
            if en_cub is not None and en_cub[L] >= 0.5 * tam[L]: nc += 1
            else: n += 1
    return n, nc

@instr.medida('imprimibilidad_puente')
def _puente(occ, p, cub=None, cama_mm=CAPA_CAMA_MM):
    """Cota superior de la luz (mm). Si hay zonas de soporte declaradas (`cub`, máscara 3D), los vóxeles dentro de ellas cuentan como apoyados."""
    dmax = 0.0
    for k in range(_capa0(occ) + 1 + _capas_cama(p, cama_mm), occ.shape[2]):
        U = occ[:, :, k] & ~occ[:, :, k - 1]
        if cub is not None: U &= ~cub[:, :, k]
        if U.sum() < 4: continue
        d = ndi.distance_transform_edt(~(occ[:, :, k - 1] | (cub[:, :, k] if cub is not None else False)), sampling=p)
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
    try: regiones = normalizar_regiones(prof.get('support_regiones')) if (orientacion_deg is None and not soporte.startswith('no')) else []
    except ErrorHerramienta as e: return e.como_dict()
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
    plano, cand, vol_plano = pared_en_plano(mf, occ, p, lo, esc, u['pared_min_mm'])
    vert, vol_vert = espesor_vertical(occ, p, u['pared_min_mm'])
    vol_total = float(mesh.volume)
    vol_fino = min(vol_plano + vol_vert, vol_total); frac_fino = vol_fino / vol_total if vol_total > 0 else 0.0
    sev = severidad_fino(frac_fino) if frac_fino > 0 else 'ninguna'
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
    cajas = _cajas_impresion(regiones, R, dz)
    cub = _mascara_cubierta(occ.shape, lo, p, cajas) if cajas else None
    cama = float(prof.get('layer', CAPA_CAMA_MM))
    vol = _voladizo(mesh, R, v[:, 2], u['voladizo_max_deg'], cama, cajas)
    n_islas, n_cub = _islas(occ, p, u['isla_min_mm2'], cub, cama); luz = _puente(occ, p, cub, cama)
    luz_sin = _puente(occ, p, None, cama) if cub is not None else luz
    tol = p / esc          # un píxel del plano (0,06 mm): un nervio nominal de 1,2 mm se mide 1,17
    resuelve = p <= u['pared_min_mm'] / 3 + 1e-9
    inc = p
    verificado = bool(cajas)
    perm_vol = soporte.startswith('no') or orientacion_deg is not None or verificado
    nota_sop = {} if (perm_vol and not verificado) else dict(nota='soportes declarados con zona (support_regiones): se comprueba solo lo que queda fuera de ella') if verificado else dict(nota='la pieza declara soportes en PRINT sin zona (support_regiones): valor informativo, no se verifica que cubran este punto')
    banda = bool(u['pared_min_mm'] - tol <= pared < u['pared_min_mm'] + tol)      # el error de medida es ±tol: dentro de la banda no se puede afirmar ni que cumple ni que falla
    crit = [dict(id='pared_min_mm', valor=r4(pared), umbral=u['pared_min_mm'], op='>=', cumple=bool(pared + tol >= u['pared_min_mm']), margen=r4(pared - u['pared_min_mm']), tolerancia_medida_mm=r4(tol),
                 en_banda_tolerancia=banda, severidad=sev, fino_volumen_mm3=r4(vol_fino), fino_fraccion=r4(frac_fino)),
            dict(id='voladizo_frac', valor=vol['fraccion_area'], umbral=u['voladizo_frac_max'], op='<=', cumple=bool(vol['fraccion_area'] <= u['voladizo_frac_max'] or not perm_vol), margen=r4(u['voladizo_frac_max'] - vol['fraccion_area']), **nota_sop),
            dict(id='islas', valor=n_islas, umbral=u['islas_max'], op='<=', cumple=bool(n_islas <= u['islas_max'] or not perm_vol), margen=u['islas_max'] - n_islas, **nota_sop),
            dict(id='puente_mm', valor=r4(luz), umbral=u['puente_max_mm'], op='<=', cumple=bool(luz <= u['puente_max_mm'] or not perm_vol), margen=r4(u['puente_max_mm'] - luz), **nota_sop)]
    if not all(c['cumple'] for c in crit): ver = 'no_cumple'
    elif not resuelve or banda: ver = 'indeterminado'
    else: ver = 'cumple'
    return dict(estado='ok', pieza=r['nombre'], veredicto=ver, pared_min_mm=r4(pared), criterios=crit, umbrales=u,
                voladizo=vol, islas=dict(numero=n_islas, cubiertas=n_cub), puente=dict(luz_estimada_mm=r4(luz), luz_sin_soporte_mm=r4(luz_sin)), puntos_finos=pts,
                material_fino=dict(volumen_mm3=r4(vol_fino), fraccion=r4(frac_fino), severidad=sev, umbral_mm=u['pared_min_mm'],
                                   nota='volumen aproximado (espesor x cresta x capa en el plano + losas finas en vertical); severidad: <0,5 % puntual, <5 % localizada, >= 5 % extensa'),
                orientacion_deg=rot, soporte_declarado=soporte, soporte=dict(declarado=soporte, regiones=len(regiones), cobertura_verificada=verificado),
                fidelidad=dict(paso_mm=p, paso_en_plano_mm=r4(p / esc), espesor_vertical_min_mm=None if vert is None else r4(vert), voxelizado=metodo_vox, voxeles=int(np.prod(shape)), incertidumbre_mm=r4(p), resuelve_umbral=bool(resuelve),
                               nota='pared = min(2·EDT 2D por capa a paso/4 en el plano, rachas verticales en losas); error ≈ ±paso/4 en plano, ±paso en vertical; paso > umbral/3 => indeterminado si nada falla'),
                nivel_validacion='digital',
                limites=['no prueba la capacidad real de la impresora ni la adhesión de capas', 'puente = cota superior (2×distancia máxima al soporte)',
                         'las zonas de soporte son cajas declaradas por ti: no se comprueba que el soporte generado por el slicer las llene'])
