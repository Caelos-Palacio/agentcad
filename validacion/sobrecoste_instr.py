"""Sobrecoste medido de agentcad.instr.

    cd <repo> && AGENTCAD_LOCK_HELD=1 flock <lock pesado> python -m validacion.sobrecoste_instr [--reps 9]

1) MICRO: coste de una etapa vacía (desactivada, memoria no/basica/muestreo/tracemalloc), en microsegundos.
2) MACRO: tres cargas reales, cada una en un proceso nuevo, alternando AGENTCAD_INSTR=0 / 1 (A B, B A...). Se informa la mediana de cada variante, la diferencia relativa y el rango
   intercuartílico de ruido de la variante desactivada: una diferencia menor que ese ruido no es distinguible de cero en esta máquina.
   - fem: caso `voladizo` de validacion/ a 8 elementos por canto (ensamblado, factorización, resolución, tensiones).
   - imprimibilidad: check_printability de la placa del ejemplo (pasos de voxelización, pared, voladizos, islas, puentes).
   - pipeline: integrar_variante en modo simulado (3 corridas sobre una copia temporal; diario, perfil por paso y sumidero de hijos; bloques ligeros).
Escribe validacion/sobrecoste_instr.json y imprime una tabla Markdown."""
from __future__ import annotations
import argparse, json, os, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent

def micro(n=20000):
    sys.path.insert(0, str(RAIZ)); from agentcad import instr
    out = {}
    for nombre, kw in (('desactivada', dict(activa=False)), ('memoria=no', dict(activa=True, memoria='no')), ('memoria=basica', dict(activa=True, memoria='basica')),
                       ('memoria=muestreo', dict(activa=True, memoria='muestreo')), ('memoria=tracemalloc', dict(activa=True, memoria='tracemalloc'))):
        instr.restablecer(); instr.configurar(**kw); m = n if nombre != 'memoria=tracemalloc' else n // 4; t = time.perf_counter()
        for _ in range(m):
            with instr.etapa('x', n=1): pass
        out[nombre] = round((time.perf_counter() - t) / m * 1e6, 2)
    t = time.perf_counter()
    for _ in range(n): pass
    instr.restablecer(); instr.configurar(activa=True, memoria='muestreo'); m = 2000; t = time.perf_counter()
    for _ in range(m):
        with instr.medir_paso(): pass
    out['medir_paso (por paso de pipeline)'] = round((time.perf_counter() - t) / m * 1e6, 1)
    out['bucle_vacio'] = round((time.perf_counter() - t) / n * 1e6, 3); instr.restablecer(); return out

CODIGOS = {
 'fem': "from validacion import casos as C; C.voladizo(ns=(8,))",
 'imprimibilidad': "import os; os.chdir(%r); from agentcad import printability as P; P.check_printability('placa_soporte')",
}

def una_vez(carga, instr_on, ejemplo):
    env = {k: v for k, v in os.environ.items() if not k.startswith('AGENTCAD_INSTR')}; env.update(AGENTCAD_INSTR='1' if instr_on else '0', PYTHONPATH=str(RAIZ), AGENTCAD_FASTLU='1', AGENTCAD_LOCK_HELD='1')
    codigo = CODIGOS['imprimibilidad'] % str(ejemplo) if carga == 'imprimibilidad' else CODIGOS[carga] if carga == 'fem' else PIPELINE
    t = time.perf_counter(); r = subprocess.run([sys.executable, '-W', 'ignore', '-c', f'import time; t=time.perf_counter()\n{codigo}\nprint(time.perf_counter()-t)'], capture_output=True, text=True, env=env, cwd=str(RAIZ if carga == 'fem' else '/tmp'), timeout=900)
    if r.returncode: raise RuntimeError(r.stderr[-500:])
    return float(r.stdout.strip().splitlines()[-1])           # tiempo de la carga (sin el arranque del intérprete ni los imports)

PIPELINE = r'''
import os, tempfile, shutil, json
from pathlib import Path
from agentcad import pipeline as pl, sim_fixture
d = Path(tempfile.mkdtemp()); info = sim_fixture.crear(d / 'p')
pipe = pl.cargar_pipeline('integrar_variante'); params = dict(etiqueta='v2', etiqueta_anterior='v1', config='config.json', base_g=info['base_g'])
for i in range(3): pl.Ejecutor(pipe, params, f'c{i}', info['raiz'], simulado=True).correr()
shutil.rmtree(d)
'''

def iqr(xs):
    q = statistics.quantiles(xs, n=4); return q[2] - q[0]

def macro(reps):
    ejemplo = RAIZ / 'ejemplos' / 'soporte_simple'; res = {}
    with tempfile.TemporaryDirectory() as t:
        ej = Path(t) / 'ej'; shutil.copytree(ejemplo, ej, ignore=shutil.ignore_patterns('build', 'registro', 'trabajo'))
        for carga in ('fem', 'imprimibilidad', 'pipeline'):
            v = {False: [], True: []}
            for i in range(reps):
                for on in ((False, True) if i % 2 == 0 else (True, False)): v[on].append(una_vez(carga, on, ej))
            a, b = statistics.median(v[False]), statistics.median(v[True])
            res[carga] = dict(reps=reps, mediana_desactivada_s=round(a, 4), mediana_activa_s=round(b, 4), sobrecoste_pct=round(100 * (b - a) / a, 2), ruido_iqr_desactivada_pct=round(100 * iqr(v[False]) / a, 2),
                              minimo_desactivada_s=round(min(v[False]), 4), minimo_activa_s=round(min(v[True]), 4), sobrecoste_minimos_pct=round(100 * (min(v[True]) - min(v[False])) / min(v[False]), 2))
    return res

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--reps', type=int, default=9); a = ap.parse_args()
    out = dict(micro_us_por_etapa=micro(), macro=macro(a.reps)); (RAIZ / 'validacion' / 'sobrecoste_instr.json').write_text(json.dumps(out, indent=1))
    print('| carga | mediana desactivada (s) | mediana activa (s) | sobrecoste | ruido (IQR desact.) | sobrecoste de los mínimos |\n|---|--:|--:|--:|--:|--:|')
    for k, r in out['macro'].items(): print(f"| {k} | {r['mediana_desactivada_s']} | {r['mediana_activa_s']} | {r['sobrecoste_pct']:+.2f} % | {r['ruido_iqr_desactivada_pct']:.2f} % | {r['sobrecoste_minimos_pct']:+.2f} % |")
    print('\nmicro (us por etapa vacía):', json.dumps(out['micro_us_por_etapa']))
