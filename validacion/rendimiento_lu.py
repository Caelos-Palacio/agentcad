"""Rendimiento de la factorización LU con disección anidada (agentcad/fastlu.py) frente a la base de scipy (splu, COLAMD) sobre los casos de validacion/.

    cd <repo> && AGENTCAD_LOCK_HELD=1 flock <lock pesado> python -m validacion.rendimiento_lu [--reps 3] [--rapido]

Cada medida es un PROCESO nuevo (memoria pico limpia) con AGENTCAD_INSTR=1; las dos variantes se alternan (A B, B A, A B...) para repartir la deriva de carga de la máquina.
Variantes: `base` = AGENTCAD_FASTLU=0 (splu COLAMD de scipy); `nd` = AGENTCAD_FASTLU=1 y AGENTCAD_FASTLU_MIN=1 (ND forzado incluso por debajo del umbral habitual de 20.000 gdl, para ver dónde compensa).
Tiempos = etapas de agentcad.instr (fem_factorizacion incluye la ordenación ND; fem_ordenacion_nd es la parte de ordenación). Se verifica que el resultado numérico del caso coincide (tolerancia 1e-8 relativa).
Escribe validacion/rendimiento_lu.json y validacion/RENDIMIENTO_LU.md. Todo digital: tiempos de ESTA máquina (compartida), no una propiedad del algoritmo."""
from __future__ import annotations
import argparse, json, os, resource, statistics, subprocess, sys, time
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
CASOS = [('voladizo', 8), ('voladizo', 12), ('flexion_3_puntos', 8), ('flexion_3_puntos', 12), ('torsion', 8), ('torsion', 12), ('placa_agujero', 12), ('placa_agujero', 16)]
VARIANTES = {'base': {'AGENTCAD_FASTLU': '0'}, 'nd': {'AGENTCAD_FASTLU': '1', 'AGENTCAD_FASTLU_MIN': '1'}}
TOL = 1e-8

def trabajador(caso, n):
    sys.path.insert(0, str(RAIZ))
    from validacion import casos as C
    from agentcad import instr
    instr.configurar(activa=True, memoria='muestreo')
    t = time.perf_counter(); fn = getattr(C, caso); r = fn(nds=(n,)) if caso == 'placa_agujero' else fn(ns=(n,)); seg = time.perf_counter() - t
    et = {x['etapa']: x for x in instr.resumir(instr.registros())}; fac = [x for x in instr.registros() if x.get('etapa') == 'fem_factorizacion'][0]
    return dict(caso=caso, n=n, fem=r[0]['fem'], elementos=r[0]['elementos'], n_dof=int(fac['n_dof']), metodo=fac['metodo'], relleno=fac['relleno'], seg_total=round(seg, 3),
                seg_factorizacion=et['fem_factorizacion']['seg'], seg_ordenacion=et.get('fem_ordenacion_nd', {}).get('seg', 0.0), seg_resolucion=et['fem_resolucion']['seg'], seg_ensamblado=et['fem_ensamblado']['seg'],
                rss_pico_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))

def lanzar(caso, n, variante):
    env = {k: v for k, v in os.environ.items() if not k.startswith('AGENTCAD_FASTLU')}; env.update(VARIANTES[variante], AGENTCAD_INSTR='1', PYTHONPATH=str(RAIZ))
    r = subprocess.run([sys.executable, '-m', 'validacion.rendimiento_lu', '--trabajador', caso, str(n)], capture_output=True, text=True, env=env, cwd="/tmp", timeout=1800)
    if r.returncode: raise RuntimeError(f'{caso} n={n} {variante}: {r.stderr[-400:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])

def med(xs): return statistics.median(xs)

def ejecutar(reps=3, casos=CASOS):
    res = []
    for caso, n in casos:
        runs = {v: [] for v in VARIANTES}
        for i in range(reps):
            for v in (list(VARIANTES) if i % 2 == 0 else list(VARIANTES)[::-1]): runs[v].append(lanzar(caso, n, v))
        b, d = runs['base'], runs['nd']; dif = max(abs(x['fem'] - b[0]['fem']) / abs(b[0]['fem']) for x in b + d)
        fila = dict(caso=caso, n=n, n_dof=b[0]['n_dof'], elementos=b[0]['elementos'], reps=reps, dif_resultado_rel=dif, ok_equivalencia=dif <= TOL)
        for v, rs in runs.items():
            fila[v] = {k: round(med([x[k] for x in rs]), 3) for k in ('seg_total', 'seg_factorizacion', 'seg_ordenacion', 'seg_resolucion', 'rss_pico_mib', 'relleno')}
            fila[v]['seg_factorizacion_rango'] = [round(min(x['seg_factorizacion'] for x in rs), 3), round(max(x['seg_factorizacion'] for x in rs), 3)]
        fila['mejora_factorizacion_pct'] = round(100 * (1 - fila['nd']['seg_factorizacion'] / fila['base']['seg_factorizacion']), 1)
        fila['mejora_total_pct'] = round(100 * (1 - fila['nd']['seg_total'] / fila['base']['seg_total']), 1)
        fila['mejora_rss_pct'] = round(100 * (1 - fila['nd']['rss_pico_mib'] / fila['base']['rss_pico_mib']), 1)
        res.append(fila); print(f"{caso} n={n} ({fila['n_dof']} gdl): factorización {fila['mejora_factorizacion_pct']:+.1f} %, total {fila['mejora_total_pct']:+.1f} %, RSS {fila['mejora_rss_pct']:+.1f} %", flush=True)
    return res

def tablas(res):
    L = ['| caso | gdl | factorización base (s) | factorización ND (s, con ordenación) | de ellas ordenación | mejora fact. | mejora total | relleno base / ND | RSS pico base / ND (MiB) | dif. resultado |', '|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|']
    for f in res:
        b, d = f['base'], f['nd']
        L.append(f"| {f['caso']} n={f['n']} | {f['n_dof']} | {b['seg_factorizacion']:.2f} ({b['seg_factorizacion_rango'][0]:.2f}-{b['seg_factorizacion_rango'][1]:.2f}) | {d['seg_factorizacion']:.2f} ({d['seg_factorizacion_rango'][0]:.2f}-{d['seg_factorizacion_rango'][1]:.2f}) | {d['seg_ordenacion']:.2f} | "
                 f"{f['mejora_factorizacion_pct']:+.1f} % | {f['mejora_total_pct']:+.1f} % | {b['relleno']:.1f} / {d['relleno']:.1f} | {b['rss_pico_mib']:.0f} / {d['rss_pico_mib']:.0f} | {f['dif_resultado_rel']:.1e} |")
    return '\n'.join(L)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--reps', type=int, default=3); ap.add_argument('--rapido', action='store_true'); ap.add_argument('--trabajador', nargs=2); a = ap.parse_args()
    if a.trabajador: print(json.dumps(trabajador(a.trabajador[0], int(a.trabajador[1])))); sys.exit(0)
    res = ejecutar(a.reps, CASOS[:2] if a.rapido else CASOS)
    if not a.rapido:
        (RAIZ / 'validacion' / 'rendimiento_lu.json').write_text(json.dumps(res, indent=1)); (RAIZ / 'validacion' / 'RENDIMIENTO_LU.md').write_text('# Rendimiento de la factorización LU (ND frente a COLAMD) en los casos de validacion/\n\n(generado por `python -m validacion.rendimiento_lu`; ver el texto de interpretación en docs/instrumentacion.md)\n\n' + tablas(res) + '\n')
    else: print(tablas(res))
