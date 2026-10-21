"""Casos de verificación del solver FEM voxel de agentcad (agentcad/fem3d.py) contra soluciones analíticas o publicadas.

Etiqueta: «verificado numéricamente contra solución analítica». NO es una validación física con ensayos (no hay ninguno).
Cada caso devuelve una lista de dicts, uno por resolución, con `n` = elementos a lo largo del canto/dimensión característica menor,
el valor del FEM, la referencia y el error relativo (FEM - ref)/ref (positivo = FEM más flexible/tensión mayor que la teoría).
Material: PETG (E = 1900 MPa, nu = 0,38); unidades mm, N, MPa.
"""
from __future__ import annotations
import math, os
import numpy as np
os.environ.setdefault('AGENTCAD_FASTLU', '1')
from agentcad.fem3d import Voxel
from agentcad import benchmarks as bm

E, NU = bm.E_PETG, bm.NU_PETG
G = E / (2 * (1 + NU))
KAPPA = 5 / 6                       # factor de cortante de Timoshenko (el mismo que agentcad/benchmarks.py)
T = 1e-9

def _ids(v, mask): return np.nonzero(mask)[0]
def _dofs(nodos, comps=(0, 1, 2)): return np.concatenate([3 * nodos + c for c in comps]) if len(nodos) else np.zeros(0, int)

def orden_observado(ns, valores, ref=None):
    """Orden de convergencia observado con refinamientos de razón 2 (n, 2n, 4n).
    - respecto a la referencia: p = log2(|e_n| / |e_2n|) con e = valor - ref (solo informativo si el error tiende a un residuo no nulo);
    - de Richardson (sin usar la referencia): p = log2((v_n - v_2n)/(v_2n - v_4n)).
    Devuelve una lista de dicts por cada terna consecutiva de razón 2 y la extrapolación de Richardson v_inf = v_4n + (v_4n - v_2n)/(2^p - 1)."""
    d = dict(zip(ns, valores)); out = []
    for n in sorted(d):
        if 2 * n in d and 4 * n in d:
            a, b, c = d[n], d[2 * n], d[4 * n]
            if (a - b) * (b - c) > 0 and abs(b - c) > 1e-14:
                p = math.log2((a - b) / (b - c))
                if p <= 0.05: continue            # los incrementos no decrecen: la malla aún no está en régimen asintótico, el orden no es interpretable
                ext = c + (c - b) / (2 ** p - 1)
                o = dict(ns=[n, 2 * n, 4 * n], orden_richardson=p, extrapolado=ext)
                if ref: o.update(error_extrapolado_rel=(ext - ref) / ref, orden_vs_referencia=math.log2(abs(a - ref) / abs(b - ref)) if abs(b - ref) > 0 and abs(a - ref) > 0 else None)
                out.append(o)
    return out

# ---------------------------------------------------------------- 1. voladizo (Euler-Bernoulli / Timoshenko)
def voladizo(ns=(2, 3, 4, 6, 8, 12), L=40.0, b=5.0, h=5.0, P=10.0):
    """Voladizo empotrado con carga transversal repartida en el extremo. Referencia: Timoshenko (EB + cortante, kappa = 5/6).
    El FEM empotra TODA la sección (impide el alabeo), lo que añade una rigidez que Timoshenko no incluye: el error no tiende a cero con la malla."""
    ref = bm.viga_referencia(L, b, h, E, NU, P); out = []
    for n in ns:
        p = h / n; nx, ny = int(round(L / p)), int(round(b / p))
        v = Voxel(np.ones((nx, ny, n), bool), p, (0, 0, 0), E=E, nu=NU); x = v.xyz
        fijo = _dofs(_ids(v, x[:, 0] < T)); tip = _ids(v, np.abs(x[:, 0] - L) < T)
        F = np.zeros(3 * v.nn); F[3 * tip + 2] = -P / len(tip)
        u = v.solve(F, fijo); w = float(-u[3 * tip + 2].mean())
        out.append(dict(n=n, paso_mm=p, elementos=int(v.ne), fem=w, referencia=ref['timoshenko_mm'], referencia_eb=ref['euler_bernoulli_mm'], error_rel=(w - ref['timoshenko_mm']) / ref['timoshenko_mm']))
    return out

# ---------------------------------------------------------------- 2. barra a tracción
def traccion(ns=(1, 2, 4), L=30.0, b=5.0, h=5.0, P=100.0):
    """Barra a tracción. (a) condiciones ideales (simetría en tres caras, tracción uniforme): el hexaedro lineal reproduce un campo uniforme EXACTO;
    (b) empotrada (se impide la contracción de Poisson en el extremo): efecto de borde real que la teoría 1D ignora."""
    A = b * h; ref_d = P * L / (E * A); ref_s = P / A; res = {'ideal': [], 'empotrada': []}
    for n in ns:
        p = h / n; nx, ny = int(round(L / p)), int(round(b / p))
        for caso in res:
            v = Voxel(np.ones((nx, ny, n), bool), p, (0, 0, 0), E=E, nu=NU); x = v.xyz
            cara = _ids(v, np.abs(x[:, 0] - L) < T)
            if caso == 'ideal': fijo = np.concatenate([_dofs(_ids(v, x[:, 0] < T), (0,)), _dofs(_ids(v, x[:, 1] < T), (1,)), _dofs(_ids(v, x[:, 2] < T), (2,))])
            else: fijo = _dofs(_ids(v, x[:, 0] < T))
            F = np.zeros(3 * v.nn); peso = np.where((x[cara, 1] < T) | (x[cara, 1] > b - T), .5, 1.0) * np.where((x[cara, 2] < T) | (x[cara, 2] > h - T), .5, 1.0)
            F[3 * cara] = P * peso / peso.sum()
            u = v.solve(F, np.unique(fijo)); d = float(u[3 * cara].mean())
            sig = v.stress(u); c = v.o + (v.eidx + .5) * v.h; sel = np.abs(c[:, 0] - L / 2) < p
            s_med = float(sig[sel, 0].mean()); s_max = float(sig[sel, 0].max())
            res[caso].append(dict(n=n, paso_mm=p, elementos=int(v.ne), fem=d, referencia=ref_d, error_rel=(d - ref_d) / ref_d,
                                  tension_media=s_med, tension_max=s_max, tension_referencia=ref_s, error_tension_rel=(s_max - ref_s) / ref_s))
    return res

# ---------------------------------------------------------------- 3. placa con agujero (concentración de tensiones Kt)
def kt_peterson_neto(dw): return 3.000 - 3.140 * dw + 3.667 * dw ** 2 - 1.527 * dw ** 3
def kt_bruto_peterson(dw): return kt_peterson_neto(dw) / (1 - dw)          # Kt respecto a la tensión bruta P/(W t): s_max = Kt_g · s_bruta

def placa_agujero(nds=(4, 6, 8, 12, 16), W=20.0, d=4.0, Lh=30.0, t=1.0, sigma=1.0):
    """Placa a tracción con agujero circular central, 1/4 con simetrías (x=0, y=0). Se mide Kt = s_max / s_bruta con s_max = máx. de s_xx (elemento, en el centroide)
    entre los elementos pegados al plano de simetría de la sección neta. Referencia: Kt = 3 de la placa infinita (Kirsch) con la corrección de ancho finito de Peterson
    (Kt_neto = 3,000 - 3,140 d/W + 3,667 (d/W)^2 - 1,527 (d/W)^3, sobre la tensión neta). El agujero se discretiza «en escalera» y la tensión es del centroide del elemento:
    ambos hacen que el FEM subestime el pico."""
    dw = d / W; ref = kt_bruto_peterson(dw); out = []
    for nd in nds:
        p = d / nd; nx, ny, nz = int(round(Lh / p)), int(round((W / 2) / p)), max(1, int(round(t / p)))
        c = (np.arange(nx) + .5) * p; cy = (np.arange(ny) + .5) * p
        occ = np.ones((nx, ny, nz), bool); occ &= ((c[:, None] ** 2 + cy[None, :] ** 2) > (d / 2) ** 2)[:, :, None]
        v = Voxel(occ, p, (0, 0, 0), E=E, nu=NU); x = v.xyz
        fijo = np.concatenate([_dofs(_ids(v, x[:, 0] < T), (0,)), _dofs(_ids(v, x[:, 1] < T), (1,))])
        # un nodo fija uz (la placa puede contraerse libremente en el espesor): nodo de la cara z mínima en el plano x=0
        n0 = _ids(v, (x[:, 2] < T) & (x[:, 0] < T)); fijo = np.concatenate([fijo, 3 * n0[:1] + 2])
        cara = _ids(v, np.abs(x[:, 0] - Lh) < T)
        F = np.zeros(3 * v.nn); peso = np.where((x[cara, 1] < T) | (x[cara, 1] > W / 2 - T), .5, 1.0) * np.where((x[cara, 2] < T) | (x[cara, 2] > nz * p - T), .5, 1.0)
        F[3 * cara] = sigma * (W / 2) * (nz * p) * peso / peso.sum()
        u = v.solve(F, np.unique(fijo)); sig = v.stress(u); cen = v.o + (v.eidx + .5) * v.h
        sel = (cen[:, 0] < (d / 2 + 1.5 * p)) & (cen[:, 1] < (d / 2 + 2.0 * p)) & (cen[:, 1] > d / 2 - 2.0 * p)     # entorno del punto (0, d/2): fondo del agujero sobre la sección neta
        smax = float(sig[sel, 0].max()); out.append(dict(n=nd, paso_mm=p, elementos=int(v.ne), fem=smax / sigma, referencia=ref, referencia_infinita=3.0, error_rel=(smax / sigma - ref) / ref))
    return out

# ---------------------------------------------------------------- 4. flexión en tres puntos
def flexion_3_puntos(ns=(2, 3, 4, 6, 8, 12), L=48.0, b=6.0, h=6.0, P=20.0, ancho_carga=2.0):
    """Viga biapoyada con carga central (modelo 1/2 con simetría en x = L/2). Referencia: Timoshenko  PL^3/(48EI) + PL/(4 kappa G A)  para la flecha en el centro (cara inferior),
    y Euler-Bernoulli  s = M z / I  para la tensión en la fila inferior de elementos (centroide, a media altura de elemento de la cara inferior, en x = L/2 - paso/2), con M exacto para la carga realmente repartida.
    La carga se reparte en una franja de ancho `ancho_carga` (al menos un elemento) para evitar la singularidad de la carga puntual."""
    I = b * h ** 3 / 12; A = b * h
    ref = P * L ** 3 / (48 * E * I) + P * L / (4 * KAPPA * G * A); out = []
    for n in ns:
        p = h / n; nx, ny = int(round((L / 2) / p)), int(round(b / p))
        v = Voxel(np.ones((nx, ny, n), bool), p, (0, 0, 0), E=E, nu=NU); x = v.xyz; mitad = L / 2
        sim = _dofs(_ids(v, np.abs(x[:, 0] - mitad) < T), (0,))
        apoyo = _ids(v, (x[:, 0] < T) & (x[:, 2] < T)); fijo = np.concatenate([sim, 3 * apoyo + 2, 3 * apoyo[:1] + 1])
        ancho = max(ancho_carga, p) + 1e-9
        top = _ids(v, (np.abs(x[:, 2] - h) < T) & (x[:, 0] > mitad - ancho))
        peso = np.where((x[top, 1] < T) | (x[top, 1] > b - T), .5, 1.0) * np.where(np.abs(x[top, 0] - mitad) < T, .5, 1.0)
        F = np.zeros(3 * v.nn); F[3 * top + 2] = -(P / 2) * peso / peso.sum()
        u = v.solve(F, np.unique(fijo)); cen = _ids(v, (np.abs(x[:, 0] - mitad) < T) & (x[:, 2] < T)); w = float(-u[3 * cen + 2].mean())
        sig = v.stress(u); c = v.o + (v.eidx + .5) * v.h
        sel = (c[:, 2] < p) & (np.abs(c[:, 0] - (mitad - p / 2)) < p / 4); xs = float(c[sel, 0].mean()); zc = h / 2 - p / 2
        planos = np.unique(np.round(x[top, 0], 9)); fx_ = np.array([(P / 2) * peso[np.abs(x[top, 0] - xp) < T].sum() / peso.sum() for xp in planos])
        M = (P / 2) * xs - float((fx_[planos < xs] * (xs - planos[planos < xs])).sum())         # momento exacto en x = xs con la carga realmente repartida en la franja
        s_ref = M / I * zc; s_fem = float(sig[sel, 0].mean())                   # tracción en la cara inferior: s_xx > 0
        out.append(dict(n=n, paso_mm=p, elementos=int(v.ne), fem=w, referencia=ref, error_rel=(w - ref) / ref, tension_fem=s_fem, tension_referencia=s_ref, error_tension_rel=(s_fem - s_ref) / s_ref))
    return out

# ---------------------------------------------------------------- 5. torsión de Saint-Venant
def j_saint_venant(a, b, terminos=60):
    """Constante torsional de una sección rectangular a x b (a >= b): J = a b^3 /3 [1 - 192/pi^5 (b/a) sum_{n impar} tanh(n pi a / 2b)/n^5] (serie exacta de Saint-Venant)."""
    a, b = max(a, b), min(a, b)
    s = sum(math.tanh(n * math.pi * a / (2 * b)) / n ** 5 for n in range(1, 2 * terminos, 2))
    return a * b ** 3 / 3 * (1 - 192 / math.pi ** 5 * (b / a) * s)

def torsion(ns=(2, 3, 4, 6, 8, 12), L=36.0, b=6.0, h=6.0, Mt=100.0):
    """Barra prismática de sección rectangular empotrada por un extremo (sin alabeo) con par Mt en el otro. Se mide el giro por unidad de longitud entre x = L/3 y 2L/3
    (lejos de los extremos, donde rige Saint-Venant): theta' = Mt/(G J). El par se aplica con fuerzas nodales tangenciales proporcionales a la distancia al eje."""
    J = j_saint_venant(h, b); ref = Mt / (G * J); out = []
    for n in ns:
        p = min(b, h) / n; nx, ny, nz = int(round(L / p)), int(round(b / p)), int(round(h / p))
        v = Voxel(np.ones((nx, ny, nz), bool), p, (0, 0, 0), E=E, nu=NU); x = v.xyz
        fijo = _dofs(_ids(v, x[:, 0] < T)); cara = _ids(v, np.abs(x[:, 0] - L) < T)
        yc, zc = x[cara, 1] - b / 2, x[cara, 2] - h / 2; r2 = (yc ** 2 + zc ** 2).sum()
        F = np.zeros(3 * v.nn); F[3 * cara + 1] = -Mt * zc / r2; F[3 * cara + 2] = Mt * yc / r2
        u = v.solve(F, fijo)
        def giro(x0):
            s = _ids(v, np.abs(x[:, 0] - x0) < T); yy, zz = x[s, 1] - b / 2, x[s, 2] - h / 2
            return float((yy * u[3 * s + 2] - zz * u[3 * s + 1]).sum() / (yy ** 2 + zz ** 2).sum())
        x1, x2 = round((L / 3) / p) * p, round((2 * L / 3) / p) * p; g = (giro(x2) - giro(x1)) / (x2 - x1)
        out.append(dict(n=n, paso_mm=p, elementos=int(v.ne), fem=g, referencia=ref, error_rel=(g - ref) / ref, J_mm4=J))
    return out

# ---------------------------------------------------------------- 6. placa apoyada (la de benchmarks.py, referencia de Kirchhoff)
def placa_apoyada(ns=(2, 4)):
    res = bm.placa_error_vs_paso(pasos=tuple(5.0 / n for n in ns))
    return [dict(n=n, paso_mm=r['paso_mm'], elementos=r['elementos'], fem=r['flecha_fem_mm'], referencia=r['referencia_mm'], error_rel=r['error_rel']) for n, r in zip(ns, res)]
