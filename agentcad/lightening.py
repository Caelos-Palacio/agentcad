"""apply_hex_lightening: aligeramiento hexagonal de placas planas en una COPIA de trabajo (nunca toca el original) con aligerado_placa.py.
Devuelve masa antes/después y los resultados de interferencia, fabricabilidad y estructura sobre la copia."""
import hashlib, json, math
import numpy as np
import manifold3d as M
from . import config, geom, __version__
from .geom import ErrorHerramienta, r4
from . import aligerado_placa as lp

def _num(x, lo, hi, nombre):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not (lo <= x <= hi):
        raise ErrorHerramienta('parametro_invalido', f'{nombre} debe ser numérico en [{lo}, {hi}]')
    return float(x)

def _cortadores_placa(cells, d, t):
    R = d / math.sqrt(3)
    return [M.Manifold.cylinder(t + 2, R, R, 6).rotate([0, 0, 30]).translate([c[0], c[1], -1]) for c in cells]

def apply_hex_lightening(part, d, rib, keep, t=3.0, tipo='placa', comprobar=True, fidelity_estructura=1.0):
    try:
        r = geom.resolver(part)
        d = _num(d, 1.0, 40.0, 'd'); rib = _num(rib, 0.5, 10.0, 'rib'); keep = _num(keep, 0.0, 20.0, 'keep'); t = _num(t, 0.5, 20.0, 't')
        if tipo != 'placa': raise ErrorHerramienta('parametro_invalido', "tipo debe ser 'placa' (único tipo soportado)")
    except ErrorHerramienta as e: return e.como_dict()
    mesh = geom.cargar(r['ruta'])
    if abs(mesh.bounds[0][2]) > 1e-3:
        return dict(estado='error', codigo='marco_no_soportado', mensaje='el aligerado espera la cara inferior de la placa en z=0 (marco local de la pieza)')
    prof = geom.perfil(r['modulo']); antes = geom.masa_g(r['ruta'], prof)
    cells, _R = lp.plan(str(r['ruta']), t, rib=rib, d=d, keep=keep)
    cut = _cortadores_placa(cells, d, t)
    base = geom.a_manifold(mesh)
    res = base - M.Manifold.batch_boolean(cut, M.OpType.Add) if cut else base
    out = geom.de_manifold(res) if cut else mesh
    cid = r['modulo'] + '-' + hashlib.sha1(json.dumps([geom.sha256_fichero(r['ruta']), d, rib, keep, t, tipo, __version__]).encode()).hexdigest()[:10]
    td = config.trabajo_dir(); td.mkdir(parents=True, exist_ok=True)
    ruta = td / f'{cid}.stl'; out.export(str(ruta))
    meta = dict(modulo=r['modulo'], origen=r['nombre'], sha256_origen=geom.sha256_fichero(r['ruta']), tipo=tipo, parametros=dict(d=d, rib=rib, keep=keep, t=t), n_ventanas=len(cells))
    ruta.with_suffix('.json').write_text(json.dumps(meta, indent=1))
    despues = geom.masa_g(ruta, prof)
    sal = dict(estado='ok', pieza=r['nombre'], tipo=tipo, parametros=dict(d=d, rib=rib, keep=keep, t=t), n_ventanas=len(cells),
               copia=dict(id=cid, ruta=str(ruta), parte=f'copia:{cid}'),
               masa_antes_g=r4(antes['masa_g']), masa_despues_g=r4(despues['masa_g']), delta_masa_g=r4(antes['masa_g'] - despues['masa_g']),
               volumen_antes_mm3=r4(antes['volumen_mm3']), volumen_despues_mm3=r4(despues['volumen_mm3']), perfil_impresion=prof, nivel_validacion='digital',
               nota='ventanas pasantes en zonas libres de agujeros y salientes')
    if comprobar:
        from .interference import check_interference
        from .printability import check_printability
        from .structure import evaluate_structure
        p = f'copia:{cid}'
        sal['interferencia'] = check_interference(p); sal['fabricabilidad'] = check_printability(p); sal['estructura'] = evaluate_structure(p, fidelity=fidelity_estructura)
    return sal
