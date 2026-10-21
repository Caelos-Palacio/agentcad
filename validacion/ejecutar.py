"""Ejecuta toda la suite de verificación del FEM voxel y regenera: validacion/resultados.json, validacion/TABLAS.md, validacion/figuras/*.png
y agentcad/validacion_fem.json (tabla compacta que lee evaluate_structure).

    cd <repo> && AGENTCAD_LOCK_HELD=1 flock <lock pesado> python -m validacion.ejecutar

Verificado numéricamente contra solución analítica; NO validado físicamente con ensayos (no hay ninguno)."""
from __future__ import annotations
import json, math, resource, sys
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from validacion import casos as C

TIPOS = {   # tipo de pieza -> (descripción, unidad de n, casos que lo alimentan)
    'viga_flexion': ('barras/vigas a flexión (voladizo, tres puntos)', 'elementos por canto en la dirección de la flexión'),
    'traccion': ('barras a tracción', 'elementos por canto'),
    'torsion': ('barras a torsión de sección maciza', 'elementos por canto menor'),
    'placa_flexion': ('placas delgadas a flexión (a/h = 10)', 'elementos en el espesor'),
    'placa_agujero': ('concentración de tensiones en un agujero (pico de tensión)', 'elementos por diámetro del agujero'),
}

def ejecutar():
    resource.setrlimit(resource.RLIMIT_AS, (4_500_000_000, 4_500_000_000))
    R = dict(voladizo=C.voladizo(), traccion=C.traccion(), placa_agujero=C.placa_agujero(nds=(4, 6, 8, 12, 16)), flexion_3_puntos=C.flexion_3_puntos(), torsion=C.torsion(), placa_apoyada=C.placa_apoyada())
    for k in ('voladizo', 'flexion_3_puntos', 'torsion', 'placa_agujero', 'placa_apoyada'):
        R[k] = dict(puntos=R[k], orden=C.orden_observado([x['n'] for x in R[k]], [x['fem'] for x in R[k]], R[k][0]['referencia']))
    for k in ('ideal', 'empotrada'):
        R['traccion_' + k] = dict(puntos=R['traccion'][k], orden=[])
    del R['traccion']
    return R

def curva(R, tipo):
    """Error relativo de PEOR caso (mayor |error|, con signo) en cada n para un tipo de pieza."""
    fuentes = dict(viga_flexion=['voladizo', 'flexion_3_puntos'], traccion=['traccion_empotrada'], torsion=['torsion'], placa_flexion=['placa_apoyada'], placa_agujero=['placa_agujero'])[tipo]
    por_n = {}
    for f in fuentes:
        for x in R[f]['puntos']:
            e = x['error_rel']
            if abs(e) > abs(por_n.get(x['n'], 0.0)): por_n[x['n']] = e
    return [dict(n=n, error_rel=por_n[n]) for n in sorted(por_n)]

def n_minimo(cv, tol):
    for x in cv:
        if all(abs(y['error_rel']) <= tol for y in cv if y['n'] >= x['n']): return x['n']
    return None

def tabla_compacta(R):
    t = {}
    for tipo, (desc, unidad) in TIPOS.items():
        cv = curva(R, tipo)
        t[tipo] = dict(descripcion=desc, unidad_n=unidad, curva=cv, n_para_5pct=n_minimo(cv, 0.05), n_para_10pct=n_minimo(cv, 0.10))
    return dict(etiqueta='verificado numéricamente contra solución analítica; NO validado físicamente con ensayos', material=dict(E_MPa=C.E, nu=C.NU), tipos=t,
                nota='error = (FEM - referencia)/referencia; negativo = el FEM es más rígido o subestima el pico (lado inseguro)')

def pct(x): return f'{100 * x:+.2f} %'

def tablas_md(R, T):
    L = ['# Resultados de verificación del solver FEM voxel', '',
         '**Verificado numéricamente contra solución analítica.** No es una validación física con ensayos (no hay ninguno). Error = (FEM - referencia)/referencia; ',
         'negativo = FEM más rígido que la teoría (o pico subestimado: lado inseguro para el margen). Material PETG (E = 1900 MPa, nu = 0,38). Regenerado por `python -m validacion.ejecutar`.', '']
    nombres = dict(voladizo='1. Voladizo (Euler-Bernoulli / Timoshenko), L=40, b=h=5, P=10 N', traccion_ideal='2a. Tracción, condiciones ideales (L=30, 5x5, P=100 N)', traccion_empotrada='2b. Tracción, extremo empotrado (impide Poisson)',
                   placa_agujero='3. Placa con agujero, Kt bruto (Peterson, d/W=0,2; n = elementos por diámetro)', flexion_3_puntos='4. Flexión en tres puntos, L=48, b=h=6, P=20 N', torsion='5. Torsión de Saint-Venant, 6x6, L=36 (giro por unidad de longitud)',
                   placa_apoyada='6. Placa cuadrada apoyada (a/h=10, Kirchhoff; ignora el cortante)')
    for k, tit in nombres.items():
        P = R[k]['puntos']; extra = k == 'flexion_3_puntos' or k.startswith('traccion')
        L += [f'## {tit}', '', '| n | paso (mm) | elementos | FEM | referencia | error |' + (' error de tensión |' if extra else ''), '|---|---|---|---|---|---|' + ('---|' if extra else '')]
        for x in P:
            L.append(f"| {x['n']} | {x['paso_mm']:.4g} | {x['elementos']} | {x['fem']:.5g} | {x['referencia']:.5g} | {pct(x['error_rel'])} |" + (f" {pct(x['error_tension_rel'])} |" if extra else ''))
        for o in R[k]['orden']:
            L.append(''); L.append(f"Orden observado con n = {o['ns']}: Richardson p = {o['orden_richardson']:.2f}; valor extrapolado a malla infinita {o['extrapolado']:.5g}"
                                   + (f" (error del extrapolado frente a la referencia: {pct(o['error_extrapolado_rel'])})" if 'error_extrapolado_rel' in o else '') + '.')
        L.append('')
    L += ['Nota: en la placa con agujero el pico (tensión del centroide del elemento, agujero en escalera) no está todavía en régimen asintótico a n <= 16: no se da orden observado ni extrapolación.', '']
    L += ['## Resolución mínima recomendada por tipo de pieza', '', '| tipo | n (unidad) | error con n mínimo | n para <=10 % | n para <=5 % |', '|---|---|---|---|---|']
    for tipo, d in T['tipos'].items():
        cv = d['curva']; e0 = cv[0]
        L.append(f"| {tipo}: {d['descripcion']} | {d['unidad_n']} | {pct(e0['error_rel'])} (n={e0['n']}) | {d['n_para_10pct'] or 'no alcanzado'} | {d['n_para_5pct'] or 'no alcanzado'} |")
    L += ['', 'n = None/«no alcanzado»: dentro del rango probado ningún n llega a esa tolerancia. El error medido es de ESTAS geometrías y cargas; otra pieza puede comportarse peor (huecos, nervios finos, singularidades).', '']
    return '\n'.join(L)

def figuras(R, T):
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    d = RAIZ / 'validacion' / 'figuras'; d.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for k, lab in [('voladizo', 'voladizo'), ('flexion_3_puntos', 'flexión 3 puntos'), ('torsion', 'torsión'), ('placa_agujero', 'placa con agujero (Kt, n por diámetro)'), ('traccion_empotrada', 'tracción empotrada')]:
        P = R[k]['puntos']; ax.loglog([x['n'] for x in P], [max(abs(x['error_rel']), 1e-4) for x in P], 'o-', label=lab)
    ax.axhline(0.05, color='gray', ls='--', lw=.8); ax.axhline(0.10, color='gray', ls=':', lw=.8)
    ax.set_xlabel('n (elementos por dimensión característica)'); ax.set_ylabel('|error relativo| frente a la solución analítica'); ax.set_title('Convergencia de malla del FEM voxel (verificación numérica)'); ax.legend(fontsize=7); ax.grid(True, which='both', alpha=.3)
    fig.tight_layout(); fig.savefig(d / 'convergencia.png', dpi=110); plt.close(fig)
    fig, ax = plt.subplots(figsize=(6.5, 4.2)); P = R['placa_agujero']['puntos']
    ax.plot([x['n'] for x in P], [x['fem'] for x in P], 'o-', label='FEM voxel'); ax.axhline(P[0]['referencia'], color='r', ls='--', label='Peterson, d/W=0,2 (Kt bruto)'); ax.axhline(3.0, color='gray', ls=':', label='placa infinita (Kt=3)')
    ax.set_xlabel('elementos por diámetro del agujero'); ax.set_ylabel('Kt = s_max / s_bruta'); ax.legend(fontsize=8); ax.grid(alpha=.3); ax.set_title('Placa con agujero: Kt frente a la resolución'); fig.tight_layout(); fig.savefig(d / 'placa_agujero.png', dpi=110); plt.close(fig)

def main():
    R = ejecutar(); T = tabla_compacta(R)
    (RAIZ / 'validacion' / 'resultados.json').write_text(json.dumps(R, indent=1, ensure_ascii=False), encoding='utf-8')
    (RAIZ / 'agentcad' / 'validacion_fem.json').write_text(json.dumps(T, indent=1, ensure_ascii=False), encoding='utf-8')
    (RAIZ / 'validacion' / 'TABLAS.md').write_text(tablas_md(R, T), encoding='utf-8')
    figuras(R, T)
    print((RAIZ / 'validacion' / 'TABLAS.md').read_text(encoding='utf-8'))

if __name__ == '__main__': main()
