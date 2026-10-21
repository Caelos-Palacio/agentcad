"""evaluate_structure: masa, margen mínimo y flecha con el FEM voxel de agentcad (fem3d + fastlu), SOLO para piezas con modelo de carga registrado.
Una pieza sin modelo de carga devuelve status='no_validado' (nunca una cifra inventada). Los modelos se registran por código (`registrar_modelo`) o se declaran
en agentcad.toml como [estructura.<pieza>] (modelo genérico `placa_apoyada`: placa sobre apoyos circulares con carga repartida). Digital: no prueba resistencia física."""
import os
from pathlib import Path
import numpy as np
from . import config, geom, benchmarks
from .geom import ErrorHerramienta, r4
os.environ.setdefault('AGENTCAD_FASTLU', '1')
from .fem3d import Voxel, voxelize_stl
import scipy.ndimage as ndi

ADMISIBLE_MPA = 10.0          # admisible por defecto (MPa); configurable por pieza (admisible_MPa). Valor de ejemplo: resistencia entre capas 20 MPa / 2
MAX_ELEMENTOS = 250_000

MODELOS = {}
def registrar_modelo(modulo, funcion, valid_for, casos, no_valido_para=None, recomendado_mm=None, descripcion=''):
    """funcion(ruta, paso_mm, caso, modulo) -> dict(margen, flecha_mm, elementos)."""
    MODELOS[modulo] = dict(funcion=funcion, valid_for=list(valid_for), casos=list(casos), recomendado_mm=recomendado_mm, descripcion=descripcion,
                           no_valido_para=list(no_valido_para or ['fatiga', 'fluencia', 'anisotropía de capas', 'tolerancias de impresión', 'ensayo físico']))

def _resolver_modulo_modelo(r): return r['modulo']

def modelo_voladizo_x(P=10.0, E=benchmarks.E_PETG, nu=benchmarks.NU_PETG):
    """Voladizo genérico: cara x mín empotrada, carga P (N) en -z repartida en la cara x máx. Para validar el flujo con geometría de solución conocida."""
    def f(ruta, paso, caso, modulo):
        occ, o = voxelize_stl(Path(ruta), paso)
        v = Voxel(occ, paso, o, E=E, nu=nu); x = v.xyz
        fx = np.nonzero(x[:, 0] < x[:, 0].min() + 1e-9)[0]; fixed = np.concatenate([3 * fx, 3 * fx + 1, 3 * fx + 2])
        tip = np.nonzero(x[:, 0] > x[:, 0].max() - 1e-9)[0]
        F = np.zeros(3 * v.nn); F[3 * tip + 2] = -P / len(tip)
        u = v.solve(F, fixed); vm = v.vonmises(v.stress(u))
        return dict(margen=float(ADMISIBLE_MPA / np.percentile(vm, 99.5)), flecha_mm=float(-u[3 * tip + 2].mean()), elementos=int(v.ne))
    return f

def modelo_placa_apoyada(cfg):
    """Placa sobre apoyos circulares en su cara inferior con carga repartida en lo que sobresale por encima del espesor.
    cfg: apoyos [[x,y],..] (marco local de la pieza), radio_apoyo_mm, carga_N, espesor_mm, E_MPa, nu, admisible_MPa.
    margen = admisible / percentil 99,5 de von Mises (no el máximo puntual)."""
    apoyos = [tuple(a) for a in cfg['apoyos']]; r_ap = float(cfg.get('radio_apoyo_mm', 4.5)); N = float(cfg['carga_N']); t = float(cfg.get('espesor_mm', 3.0))
    E = float(cfg.get('E_MPa', benchmarks.E_PETG)); nu = float(cfg.get('nu', benchmarks.NU_PETG)); adm = float(cfg.get('admisible_MPa', ADMISIBLE_MPA))
    def f(ruta, paso, caso, modulo):
        occ, o = voxelize_stl(Path(ruta), paso)
        lab, nl = ndi.label(occ)
        if nl > 1: occ = lab == 1 + int(np.argmax(ndi.sum(occ, lab, range(1, nl + 1))))
        v = Voxel(occ, paso, o, E=E, nu=nu); xyz = v.xyz; zmin = xyz[:, 2].min(); bottom = np.abs(xyz[:, 2] - zmin) < 1e-6
        sel = bottom & np.any([np.hypot(xyz[:, 0] - x, xyz[:, 1] - y) < r_ap for x, y in apoyos], axis=0)
        fx = np.nonzero(sel)[0]
        if len(fx) == 0: raise ErrorHerramienta('modelo_mal_configurado', 'ningún nodo de la cara inferior cae en los apoyos declarados (¿marco local o radio_apoyo_mm?)')
        fixed = np.concatenate([3 * fx, 3 * fx + 1, 3 * fx + 2])
        top = np.nonzero((xyz[:, 2] > zmin + t + 1.0) & (np.abs(xyz[:, 2] - xyz[:, 2].max()) < 6.0))[0]
        if len(top) == 0: top = np.nonzero(xyz[:, 2] >= zmin + t)[0]
        F = np.zeros(3 * v.nn); F[3 * top + 2] = -N / len(top)
        u = v.solve(F, fixed); vm = v.vonmises(v.stress(u))
        return dict(margen=float(adm / np.percentile(vm, 99.5)), flecha_mm=float(np.abs(u[2::3]).max()), elementos=int(v.ne), vm_p995_mpa=float(np.percentile(vm, 99.5)), vm_max_mpa=float(vm.max()))
    return f

_NO_PLACA = ['golpes o impactos', 'fatiga y fluencia', 'tornillos reales y su apriete', 'anisotropía entre capas más allá del admisible fijo', 'ensayo físico']

def _modelo_de_proyecto(modulo):
    cfg = config.proyecto()['estructura'].get(modulo)
    if not cfg: return None
    if cfg.get('modelo', 'placa_apoyada') != 'placa_apoyada': raise ErrorHerramienta('modelo_desconocido', f"[estructura.{modulo}] modelo '{cfg.get('modelo')}' no existe; modelos: placa_apoyada")
    adm = cfg.get('admisible_MPa', ADMISIBLE_MPA)
    return dict(funcion=modelo_placa_apoyada(cfg), casos=list(cfg.get('casos', ['carga'])), recomendado_mm=cfg.get('recomendado_mm'), no_valido_para=list(_NO_PLACA),
                descripcion='modelo placa_apoyada declarado en agentcad.toml (FEM voxel)',
                valid_for=[f"placa apoyada en {len(cfg['apoyos'])} apoyos circulares (r {cfg.get('radio_apoyo_mm', 4.5)} mm) en la cara inferior", f"carga {cfg['carga_N']} N repartida sobre lo que sobresale de la placa",
                           f"E={cfg.get('E_MPa', benchmarks.E_PETG)} MPa, nu={cfg.get('nu', benchmarks.NU_PETG)}; elasticidad lineal isótropa; admisible {adm} MPa",
                           'margen = admisible / percentil 99,5 de von Mises (no el máximo puntual)'])

def modelo_de(modulo): return MODELOS.get(modulo) or _modelo_de_proyecto(modulo)

MOTIVO_SIN_MODELO = ('no hay modelo de carga registrado para esta pieza: declara [estructura.<pieza>] en agentcad.toml o llama a structure.registrar_modelo(); '
                     'sin cargas, apoyos y material validados agentcad no inventa un margen')

def evaluate_structure(part, cases=None, fidelity=None):
    try:
        r = geom.resolver(part)
        if fidelity is not None and (isinstance(fidelity, bool) or not isinstance(fidelity, (int, float)) or not 0.2 <= fidelity <= 5.0):
            raise ErrorHerramienta('parametro_invalido', 'fidelity (paso en mm) debe estar entre 0.2 y 5.0')
        prof = geom.perfil(r['modulo']); mp = geom.masa_g(r['ruta'], prof)
        mod = modelo_de(r['modulo'])
        base = dict(estado='ok', pieza=r['nombre'], masa_g=r4(mp['masa_g']), nivel_validacion='digital')
        if mod is None:
            return dict(base, status='no_validado', motivo=MOTIVO_SIN_MODELO, margen_min=None, flecha_mm=None, casos={}, valid_for=[], no_valido_para=[],
                        fidelity=None, advertencias=[])
        casos = cases if cases is not None else list(mod['casos'])
        mal = [c for c in casos if c not in mod['casos']]
        if mal: raise ErrorHerramienta('caso_desconocido', f'casos disponibles: {mod["casos"]}; recibido: {mal}')
    except ErrorHerramienta as e: return e.como_dict()
    mesh = geom.cargar(r['ruta']); paso = float(fidelity if fidelity is not None else 1.0)
    est = float(mesh.volume) / paso ** 3
    if est > MAX_ELEMENTOS * 3:
        return dict(estado='error', codigo='demasiado_grande', mensaje=f'~{int(est)} elementos a paso {paso}; sube fidelity')
    adv = []
    rec = min([x for x in (mod['recomendado_mm'], float(mesh.extents.min()) / 4) if x])
    if paso > rec + 1e-9: adv.append(f'paso {paso} mm > recomendado {r4(rec)} mm: el FEM no resuelve bien los nervios/espesores finos; el margen puede estar sobreestimado')
    res = {c: mod['funcion'](r['ruta'], paso, c, r['modulo']) for c in casos}
    margen = min(v['margen'] for v in res.values()); flecha = max(abs(v['flecha_mm']) for v in res.values())
    return dict(base, status='ok', margen_min=r4(margen), flecha_mm=r4(flecha), casos={c: {k: r4(x) for k, x in v.items()} for c, v in res.items()},
                fidelity=dict(paso_mm=paso, elementos=max(v['elementos'] for v in res.values()), solver='fem3d hexaedro lineal 2x2x2 + LU (fastlu)',
                              error_conocido='viga: -17 % (2 el/canto), -6 % (4), -3 % (8) vs Timoshenko; ver agentcad/benchmarks.py y la sección de validación del README'),
                valid_for=mod['valid_for'], no_valido_para=mod['no_valido_para'], advertencias=adv, modelo=mod['descripcion'])
