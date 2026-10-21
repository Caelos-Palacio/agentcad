"""Pruebas de referencia del FEM voxel (agentcad/fem3d.py) contra soluciones analíticas.
Se usan en los tests y se resumen en la salida de evaluate_structure (campo `validacion_fem`) para que el agente conozca el error del método."""
import numpy as np
import os
os.environ.setdefault('AGENTCAD_FASTLU', '1')
from .fem3d import Voxel

E_PETG, NU_PETG = 1900.0, 0.38
# Tolerancias DECLARADAS (error relativo máximo aceptado respecto a la teoría); medidas con las pruebas y redondeadas al alza.
TOLERANCIAS = {
    'viga_grueso': dict(error_rel=0.25, nota='paso = canto/2 (medido 17 %): bloqueo por cortante del hexaedro lineal; el FEM es más RÍGIDO que la teoría'),
    'viga_fino': dict(error_rel=0.06, nota='paso = canto/8 (medido 2,8 %)'),
    'placa_fino': dict(error_rel=0.10, nota='a/h = 10, 4 elementos en el espesor (medido +6 %: Kirchhoff ignora el cortante)'),
}

def viga_referencia(L, b, h, E, nu, P, kappa=5 / 6):
    I = b * h ** 3 / 12; G = E / (2 * (1 + nu)); eb = P * L ** 3 / (3 * E * I); sh = P * L / (kappa * G * b * h)
    return dict(euler_bernoulli_mm=eb, cortante_mm=sh, timoshenko_mm=eb + sh)

def viga_fem(L, b, h, P, pitch, E=E_PETG, nu=NU_PETG):
    n = (int(round(L / pitch)), int(round(b / pitch)), int(round(h / pitch)))
    v = Voxel(np.ones(n, bool), pitch, (0, 0, 0), E=E, nu=nu); x = v.xyz
    fx = np.nonzero(x[:, 0] < 1e-9)[0]; fixed = np.concatenate([3 * fx, 3 * fx + 1, 3 * fx + 2])
    tip = np.nonzero(np.abs(x[:, 0] - L) < 1e-9)[0]
    F = np.zeros(3 * v.nn); F[3 * tip + 2] = -P / len(tip)
    u = v.solve(F, fixed)
    return float(-u[3 * tip + 2].mean()), int(v.ne)

def viga_error_vs_paso(pasos=(2.5, 1.25, 0.625), L=40.0, b=5.0, h=5.0, P=10.0):
    ref = viga_referencia(L, b, h, E_PETG, NU_PETG, P)['timoshenko_mm']; out = []
    for p in pasos:
        w, ne = viga_fem(L, b, h, P, p)
        out.append(dict(paso_mm=p, elementos=ne, flecha_fem_mm=w, referencia_mm=ref, error_rel=(w - ref) / ref))
    return out

def placa_referencia(a, h, E, nu, q):
    D = E * h ** 3 / (12 * (1 - nu ** 2)); return 0.00406 * q * a ** 4 / D       # Kirchhoff, apoyo simple, presión uniforme

def placa_fem(a, h, q, pitch, E=E_PETG, nu=NU_PETG):
    n = (int(round(a / pitch)), int(round(a / pitch)), int(round(h / pitch)))
    v = Voxel(np.ones(n, bool), pitch, (0, 0, 0), E=E, nu=nu); x = v.xyz; t = 1e-9
    lado = (x[:, 0] < t) | (x[:, 0] > a - t) | (x[:, 1] < t) | (x[:, 1] > a - t)
    fixed = list(3 * np.nonzero(lado)[0] + 2)
    A = np.nonzero((x[:, 0] < t) & (x[:, 1] < t) & (x[:, 2] < t))[0][0]; B = np.nonzero((np.abs(x[:, 0] - a) < t) & (x[:, 1] < t) & (x[:, 2] < t))[0][0]
    fixed += [3 * A, 3 * A + 1, 3 * B + 1]
    top = np.nonzero(np.abs(x[:, 2] - h) < t)[0]
    w = np.where(((x[top, 0] < t) | (x[top, 0] > a - t)), .5, 1.0) * np.where(((x[top, 1] < t) | (x[top, 1] > a - t)), .5, 1.0)
    F = np.zeros(3 * v.nn); F[3 * top + 2] = -q * a * a * w / w.sum()
    u = v.solve(F, np.array(sorted(set(fixed))))
    c = np.nonzero((np.abs(x[:, 0] - a / 2) < t + 1e-6) & (np.abs(x[:, 1] - a / 2) < t + 1e-6))[0]
    return float(-u[3 * c + 2].mean()), int(v.ne)

def placa_error_vs_paso(pasos=(2.5, 1.25), a=50.0, h=5.0, q=0.01):
    ref = placa_referencia(a, h, E_PETG, NU_PETG, q); out = []
    for p in pasos:
        w, ne = placa_fem(a, h, q, p)
        out.append(dict(paso_mm=p, elementos=ne, flecha_fem_mm=w, referencia_mm=ref, error_rel=(w - ref) / ref))
    return out

def informe_validacion():
    return dict(viga_voladizo=viga_error_vs_paso(), placa_apoyada=placa_error_vs_paso(), tolerancias=TOLERANCIAS,
                referencias='viga: Timoshenko (kappa=5/6); placa: Kirchhoff apoyo simple, presión uniforme (0,00406 q a^4/D)')
