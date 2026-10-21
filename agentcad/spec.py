"""Especificación declarativa por pieza (<rutas.specs>/<pieza>.json) y check_spec: cumple / no cumple por requisito con el margen."""
import json
from pathlib import Path
import numpy as np
import manifold3d as M
from . import config, geom, schema, describe
from .geom import ErrorHerramienta, r4

ESQUEMA_PATH = config.ROOT / 'spec_schema.json'
SPEC_SCHEMA_FORMAL = json.loads(ESQUEMA_PATH.read_text())

def _esquema_minimo():
    """Subconjunto que acepta check_spec en ejecución (specs en línea de las pruebas): sin cargas/orientación/unidad obligatorias."""
    s = json.loads(json.dumps(SPEC_SCHEMA_FORMAL)); s['required'] = ['pieza', 'version', 'requisitos']
    s['properties']['esquema'] = {'type': 'string'}; s['properties']['requisitos']['minItems'] = 0
    s['$defs']['requisito']['required'] = ['id', 'metrica', 'op', 'valor']; s['properties']['prioridades']['minItems'] = 0
    return s
SPEC_SCHEMA = _esquema_minimo()

METRICAS = {
    'describe.masa_estimada_g': 'g', 'describe.volumen_mm3': 'mm3', 'describe.componentes': 'adimensional',
    'fabricabilidad.pared_min_mm': 'mm', 'fabricabilidad.voladizo.fraccion_area': 'fraccion', 'fabricabilidad.voladizo.angulo_max_deg': 'grados',
    'fabricabilidad.islas.numero': 'adimensional', 'fabricabilidad.puente.luz_estimada_mm': 'mm',
    'interferencia.volumen_total_mm3': 'mm3', 'estructura.margen_min': 'adimensional', 'estructura.flecha_mm': 'mm', 'estructura.masa_g': 'g'}

def check_spec_file(spec):
    """Valida una especificación (ruta a .json o diccionario) contra spec_schema.json y las reglas semánticas del SDD.
    Devuelve dict(valido, errores, avisos, pieza). Los mensajes dicen qué campo falla y qué se esperaba."""
    err, av, pieza = [], [], None
    if isinstance(spec, (str, Path)):
        f = Path(spec)
        if not f.is_file(): return dict(valido=False, errores=[f'no existe el fichero {f}'], avisos=[], pieza=None)
        try: spec = json.loads(f.read_text())
        except ValueError as e: return dict(valido=False, errores=[f'JSON mal formado en {f.name}: {e}'], avisos=[], pieza=None)
    err += schema.validate(spec, SPEC_SCHEMA_FORMAL)
    if isinstance(spec, dict):
        pieza = spec.get('pieza')
        prios = spec.get('prioridades') if isinstance(spec.get('prioridades'), list) else []
        vistos = set()
        for i, q in enumerate(spec.get('requisitos') if isinstance(spec.get('requisitos'), list) else []):
            if not isinstance(q, dict): continue
            if q.get('id') in vistos: err.append(f"requisitos[{i}]: id duplicado '{q.get('id')}'")
            vistos.add(q.get('id')); m = q.get('metrica')
            if isinstance(m, str):
                if m.split('.')[0] not in {k.split('.')[0] for k in METRICAS}: err.append(f"requisitos[{i}]: sección '{m.split('.')[0]}' desconocida en la métrica '{m}'; secciones: {sorted({k.split('.')[0] for k in METRICAS})}")
                elif m not in METRICAS: err.append(f"requisitos[{i}]: métrica '{m}' desconocida; métricas conocidas: {sorted(METRICAS)}")
                elif isinstance(q.get('unidad'), str) and q['unidad'] != METRICAS[m]: err.append(f"requisitos[{i}]: unidad '{q['unidad']}' no coincide con la métrica '{m}' (se espera '{METRICAS[m]}')")
            cp = q.get('clase_prioridad')
            if cp is not None and cp not in prios: err.append(f"requisitos[{i}]: clase_prioridad '{cp}' no figura en prioridades {prios}")
        vistos = set()
        for i, z in enumerate(spec.get('zonas_obligatorias') if isinstance(spec.get('zonas_obligatorias'), list) else []):
            if not isinstance(z, dict): continue
            if z.get('id') in vistos: err.append(f"zonas_obligatorias[{i}]: id duplicado '{z.get('id')}'")
            vistos.add(z.get('id')); t = z.get('tipo')
            if t == 'agujeros_conservados' and not z.get('referencia'): err.append(f"zonas_obligatorias[{i}] ('{z.get('id')}', agujeros_conservados) requiere 'referencia' (pieza de la que se leen los agujeros)")
            if t in ('caja_material', 'caja_hueco'):
                if 'caja_mm' not in z: err.append(f"zonas_obligatorias[{i}] ('{z.get('id')}', {t}) requiere 'caja_mm' [[x0,y0,z0],[x1,y1,z1]]")
                campo = 'fraccion_min' if t == 'caja_material' else 'fraccion_max'
                if campo not in z: err.append(f"zonas_obligatorias[{i}] ('{z.get('id')}', {t}) requiere '{campo}'")
        vistos = set()
        for i, c in enumerate(spec.get('cargas') if isinstance(spec.get('cargas'), list) else []):
            if isinstance(c, dict):
                if c.get('id') in vistos: err.append(f"cargas[{i}]: id duplicado '{c.get('id')}'")
                vistos.add(c.get('id'))
        sup = [c.get('id') for c in spec.get('cargas', []) if isinstance(c, dict) and c.get('supuesto') is True]
        if sup: av.append(f'cargas con supuesto=true (hipótesis, no medidas): {sup}')
        o = spec.get('orientacion_impresion')
        pf = config.proyecto().perfil_impresion(pieza) if isinstance(pieza, str) else None
        if isinstance(o, dict) and isinstance(o.get('rot_deg'), list) and pf and 'rot' in pf and list(o['rot_deg']) != list(pf['rot']):
            av.append(f"orientacion_impresion.rot_deg {o['rot_deg']} difiere de [impresion.{pieza}].rot de agentcad.toml {list(pf['rot'])}")
    return dict(valido=not err, errores=err, avisos=av, pieza=pieza)

def validar_spec(s): return schema.validate(s, SPEC_SCHEMA)

def cargar_spec(modulo):
    f = config.specs_dir() / f'{modulo}.json'
    if not f.is_file(): raise ErrorHerramienta('spec_no_encontrada', f'no existe {f.name} en la carpeta rutas.specs')
    return json.loads(f.read_text())

def _evaluar(valor, op, umbral, tol=0.0):
    """El margen incluye la tolerancia de medida declarada: >= => valor + tol - umbral ; <= => umbral + tol - valor."""
    if valor is None: return 'no_evaluable', None
    m = (valor + tol - umbral) if op == '>=' else (umbral + tol - valor)
    return ('cumple' if m >= -1e-9 else 'no_cumple'), r4(m)

def _camino(d, ruta):
    for k in ruta.split('.'):
        if not isinstance(d, dict) or k not in d: return None
        d = d[k]
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None

def _zona(z, mesh, rutaobj):
    t = z['tipo']
    if t == 'agujeros_conservados':
        ref = geom.cargar(geom.resolver(z['referencia'])['ruta']); tol = z.get('tolerancia_mm', 0.1)
        a, _s, _x = describe.cilindros(ref); b, _s2, _x2 = describe.cilindros(mesh)
        falt = []
        for h in a:
            ok = any(g['eje'] == h['eje'] and abs(g['radio_mm'] - h['radio_mm']) <= tol and
                     all(abs(p - q) <= tol for p, q in zip(g['centro_mm'], h['centro_mm']) if p is not None and q is not None) for g in b)
            if not ok: falt.append(dict(eje=h['eje'], centro_mm=h['centro_mm'], radio_mm=h['radio_mm']))
        return dict(id=z['id'], tipo=t, estado='cumple' if not falt else 'no_cumple', valor=len(a) - len(falt), umbral=len(a), margen=-len(falt), faltantes=falt)
    caja = np.array(z['caja_mm'], float); lo, hi = caja.min(0), caja.max(0)
    box = M.Manifold.cube(list(hi - lo)).translate(list(lo))
    frac = float((geom.a_manifold(mesh) ^ box).volume() / box.volume())
    if t == 'caja_material':
        umbral = z.get('fraccion_min', 0.95); est, mar = _evaluar(frac, '>=', umbral)
    else:
        umbral = z.get('fraccion_max', 0.0); est, mar = _evaluar(frac, '<=', umbral)
    return dict(id=z['id'], tipo=t, estado=est, valor=r4(frac), umbral=umbral, margen=mar)

def check_spec(part, spec=None, registrar=False, fidelity_estructura=1.0):
    try:
        r = geom.resolver(part)
        s = spec if spec is not None else cargar_spec(r['modulo'])
        err = validar_spec(s)
        if err: raise ErrorHerramienta('spec_invalida', '; '.join(err[:5]))
    except ErrorHerramienta as e: return e.como_dict()
    necesarias = {q['metrica'].split('.')[0] for q in s['requisitos']}
    sec = {}
    if 'describe' in necesarias: sec['describe'] = describe.describe_part(part, radio_vecinas_mm=0.0)
    if 'interferencia' in necesarias:
        from .interference import check_interference; sec['interferencia'] = check_interference(part)
    if 'fabricabilidad' in necesarias:
        from .printability import check_printability; sec['fabricabilidad'] = check_printability(part)
    if 'estructura' in necesarias:
        from .structure import evaluate_structure; sec['estructura'] = evaluate_structure(part, fidelity=fidelity_estructura)
    reqs = []
    for q in s['requisitos']:
        v = _camino(sec, q['metrica']); est, mar = _evaluar(v, q['op'], q['valor'], q.get('tolerancia', 0.0))
        reqs.append(dict(id=q['id'], metrica=q['metrica'], op=q['op'], umbral=q['valor'], valor=None if v is None else r4(v), estado=est, margen=mar,
                         prioridad=q.get('prioridad', 9), **({} if 'tolerancia' not in q else dict(tolerancia=q['tolerancia'])), **({} if v is not None else dict(motivo='métrica no disponible (sección sin modelo validado o error)'))))
    mesh = geom.cargar(r['ruta'])
    zonas = [_zona(z, mesh, r['ruta']) for z in s.get('zonas_obligatorias', [])]
    estados = [x['estado'] for x in reqs + zonas]
    ver = 'no_cumple' if 'no_cumple' in estados else ('no_validado' if 'no_evaluable' in estados else 'cumple')
    out = dict(estado='ok', pieza=r['nombre'], veredicto=ver, requisitos=reqs, zonas=zonas, prioridades=s.get('prioridades', []),
               resumen=dict(cumplen=estados.count('cumple'), no_cumplen=estados.count('no_cumple'), no_evaluables=estados.count('no_evaluable')),
               cargas=s.get('cargas', []), supuestos=[c['id'] for c in s.get('cargas', []) if c.get('supuesto')],
               estructura_status=sec.get('estructura', {}).get('status'), nivel_validacion='digital')
    if registrar:
        from .registro import record_result
        out['registro'] = record_result('check_spec', part, parametros=dict(spec_version=s['version'], fidelity_estructura=fidelity_estructura),
                                        resultado=dict(veredicto=ver, requisitos=[{k: x[k] for k in ('id', 'estado', 'valor', 'umbral', 'margen')} for x in reqs],
                                                       zonas=[{k: x.get(k) for k in ('id', 'estado', 'valor', 'umbral', 'margen')} for x in zonas]))
    return out
