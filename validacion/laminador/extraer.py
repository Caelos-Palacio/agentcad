#!/usr/bin/env python3
"""Extrae, de un proyecto de origen con placas laminadas, las tablas PEQUEÑAS de esta comparación (datos/*.json). Solo lectura sobre el origen; no copia gcodes ni STL.

  python -m validacion.laminador.extraer --origen RUTA_DEL_PROYECTO [--geom-raw geom_raw.json]

Espera en el origen: cad/stl/plates/plate_N.stl, cad/plate_layout.json (pieza -> placa, cajas), build/gcode/analysis/<impresora>_plate_N{,_geom}.json (analizador de gcode y
clasificación diseño/artefacto), build/gcode/analysis/geom_scan.json (rebanado de las STL sin soportes) y build/gcode/tools/slice_plates.py (solo se LEE el diccionario PERFIL con ast).
Escribe: datos/printability.json (lo que dice check_printability, sin soportes, orientación de la placa), datos/verdad_laminador.json (A: rebanado STL sin soportes; B: gcode con los
soportes del laminador, clasificado 'diseno'), datos/laminado.json (tiempo, filamento y rasgos por placa e impresora). Es lento (minutos): rebana y voxeliza 16 piezas.
La separación de las placas en piezas usa las cajas de plate_layout.json; el resultado es DIGITAL: nada de esto se ha pesado ni imprimido."""
import argparse, ast, json, os, re, sys, tempfile
from pathlib import Path
import numpy as np

AQUI = Path(__file__).resolve().parent
IMPRESORAS = ('kobra_x', 'kobra_3', 'kobra_2_neo')

def separar_placas(origen):
    """{pieza: dict(placa, n, malla)} desde las STL de placa (componentes conexas asignadas por caja de plate_layout.json)."""
    import trimesh
    lay = json.loads((origen / 'cad/plate_layout.json').read_text()); piezas = {}
    for n in (1, 2, 3, 4):
        comps = trimesh.load(origen / f'cad/stl/plates/plate_{n}.stl').split(only_watertight=False); usados = set()
        for p in [p for p in lay['parts'] if p['plate'] == n]:
            bmin, bmax = np.array(p['bounds_min']), np.array(p['bounds_max']); mejor, md = None, 1e9
            for i, c in enumerate(comps):
                if i in usados: continue
                d = np.abs(c.bounds[0][:2] - bmin[:2]).max() + np.abs(c.bounds[1][:2] - bmax[:2]).max() + (0 if abs(c.bounds[1][2] - bmax[2]) < 2.5 else 99)
                if d < md: mejor, md = i, d
            if mejor is None or md > 1.0: raise RuntimeError(f'placa {n}: no casa {p["module"]} (desviación {md})')
            usados.add(mejor)
            if p['module'] in piezas: piezas[p['module']]['n'] += 1
            else: piezas[p['module']] = dict(placa=n, n=1, malla=comps[mejor])
    return piezas

def perfiles(origen):
    """Lee PERFIL = {pieza: (capa, perimetros, relleno %, patron, soporte)} de slice_plates.py SIN importarlo."""
    arbol = ast.parse((origen / 'build/gcode/tools/slice_plates.py').read_text())
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(getattr(t, 'id', '') == 'PERFIL' for t in nodo.targets): return ast.literal_eval(nodo.value)
    raise RuntimeError('PERFIL no encontrado')

def ejecutar_printability(piezas, perf):
    from agentcad import printability
    out = {}
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); (t / 'stl').mkdir(); (t / 'agentcad.toml').write_text('[proyecto]\nnombre = "laminador"\n'); os.environ['AGENTCAD_PROYECTO'] = str(t)
        for k, v in piezas.items():
            v['malla'].export(t / 'stl' / f'{k}.stl'); r = printability.check_printability(k, orientacion_deg=[0, 0, 0])      # orientación de la placa; sin soportes
            if r.get('estado') != 'ok': raise RuntimeError(f'{k}: {r}')
            c = {x['id']: x for x in r['criterios']}
            out[k] = dict(placa=v['placa'], n=v['n'], veredicto=r['veredicto'], pared_min_mm=r['pared_min_mm'], pared_severidad=c['pared_min_mm']['severidad'], islas=r['islas']['numero'],
                          luz_puente_mm=r['puente']['luz_estimada_mm'], voladizo_fraccion=r['voladizo']['fraccion_area'], voladizo_area_mm2=r['voladizo']['area_mm2'],
                          resuelve_umbral=r['fidelidad']['resuelve_umbral'], paso_mm=r['fidelidad']['paso_mm'])
    return out

def verdad(origen, geom_raw=None):
    an = origen / 'build/gcode/analysis'; scan = json.loads((an / 'geom_scan.json').read_text()); crudo = json.loads(Path(geom_raw).read_text()) if geom_raw else {}
    out = {}
    for k, v in scan.items():
        tipos = [e.get('tipo') for e in v['voladizos_diseno']]
        raw = crudo.get(k, {}).get('voladizos_raw', [])
        A = dict(islas=len(v['islas_diseno']), puentes_largos=tipos.count('puente_largo'), voladizos_fuertes=tipos.count('voladizo_fuerte'),
                 luz_max_mm=round(2 * max(d, default=0), 1) if (d := [e['max_dist_mm'] for e in raw if e['tipo'] == 'puente_largo']) else None)
        B = {}
        for pr in IMPRESORAS:
            c = dict(islas=0, puentes_largos=0, voladizos_fuertes=0)
            for n in (1, 2, 3, 4):
                f = an / f'{pr}_plate_{n}_geom.json'
                for e in json.loads(f.read_text()) if f.is_file() else []:
                    if e['piece'] != k or e['clasificacion'] != 'diseno': continue
                    c['islas' if e['kind'] == 'floating_islands' else 'puentes_largos' if e['tipo'] == 'puente_largo' else 'voladizos_fuertes'] += 1
            B[pr] = c
        out[k] = dict(placa=v['placa'], soporte_en_perfil=v['soporte_en_perfil'], A=A, B=B)
    return out

def laminado(origen, piezas, perf):
    from agentcad import geom
    an = origen / 'build/gcode/analysis'; filas = []
    por_placa = {n: dict(volumen_mm3=0.0, area_mm2=0.0, masa_cad_g=0.0, piezas=0) for n in (1, 2, 3, 4)}
    for k, v in piezas.items():
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / f'{k}.stl'; v['malla'].export(f); m = geom.masa_g(f, dict(walls=perf[k][1], infill=perf[k][2]))
        for campo, val in (('volumen_mm3', m['volumen_mm3']), ('area_mm2', m['area_mm2']), ('masa_cad_g', m['masa_g'])): por_placa[v['placa']][campo] += val * v['n']
        por_placa[v['placa']]['piezas'] += v['n']
    for pr in IMPRESORAS:
        for n in (1, 2, 3, 4):
            d = json.loads((an / f'{pr}_plate_{n}.json').read_text()); h = d['header']
            filas.append(dict(impresora=pr, placa=n, tiempo_s=h['time_normal'], filamento_g=h['filament_g'], filamento_m=round(d['filament']['length_mm'] / 1000, 2), capas=d['layers'], z_max_mm=d['max_z'],
                              capas_con_soporte=sum(o['support_layers'] for o in d['per_object'].values())))
    return dict(placas={str(n): {k: round(v, 2) for k, v in x.items()} for n, x in por_placa.items()}, filas=filas)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0]); ap.add_argument('--origen', required=True); ap.add_argument('--geom-raw'); a = ap.parse_args(argv)
    origen = Path(a.origen).resolve(); sys.path.insert(0, str(AQUI.parents[1])); piezas = separar_placas(origen); perf = perfiles(origen); d = AQUI / 'datos'; d.mkdir(exist_ok=True)
    for nombre, obj in (('printability', ejecutar_printability(piezas, perf)), ('verdad_laminador', verdad(origen, a.geom_raw)), ('laminado', laminado(origen, piezas, perf))):
        (d / f'{nombre}.json').write_text(json.dumps(obj, indent=1, ensure_ascii=False)); print('escrito', d / f'{nombre}.json')

if __name__ == '__main__': main()
