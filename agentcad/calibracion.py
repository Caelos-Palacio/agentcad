"""Calibración sencilla de una estimación frente a medidas del laminador: y ≈ r·x (una razón) ajustada por mínimo ERROR RELATIVO, con validación cruzada que deja fuera un GRUPO entero
(p. ej. una placa con todas sus impresoras: repetir la misma geometría en el entrenamiento sería hacer trampa). Con pocos grupos el resultado se declara NO fiable.
Todo es digital: una razón ajustada a unos laminados no predice la impresión real (falta imprimir y pesar)."""
import numpy as np
MIN_GRUPOS_FIABLE = 8        # por debajo, `fiable: false`: con 4 placas el error de validación cruzada es una indicación, no una garantía

def _datos(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if x.ndim != 1 or x.shape != y.shape or x.size == 0: raise ValueError('x e y deben ser listas no vacías de la misma longitud')
    if not (np.all(x > 0) and np.all(y > 0) and np.all(np.isfinite(x)) and np.all(np.isfinite(y))): raise ValueError('x e y deben ser positivos y finitos')
    return x, y

def ajustar_razon(x, y):
    """r que minimiza sum(((r·x - y)/y)^2): r = sum(x/y) / sum((x/y)^2)."""
    x, y = _datos(x, y); u = x / y; return float(u.sum() / (u * u).sum())

def validacion_cruzada(x, y, grupos):
    """Deja fuera cada grupo, ajusta con el resto y predice el grupo. Devuelve errores relativos ((pred - medido)/medido) por punto, mape, max_abs y n_grupos."""
    x, y = _datos(x, y); g = np.asarray(list(grupos), dtype=object)
    if g.shape != x.shape: raise ValueError('grupos debe tener la longitud de x')
    nombres = list(dict.fromkeys(g.tolist()))
    if len(nombres) < 2: raise ValueError('hacen falta al menos 2 grupos para validar')
    err = np.zeros(x.size)
    for n in nombres:
        fuera = np.array([v == n for v in g.tolist()]); r = ajustar_razon(x[~fuera], y[~fuera]); err[fuera] = (r * x[fuera] - y[fuera]) / y[fuera]
    return dict(errores_rel=[float(e) for e in err], mape=float(np.abs(err).mean()), max_abs=float(np.abs(err).max()), n_grupos=len(nombres))

def calibrar(filas, campo_x, campo_y, campo_grupo):
    """filas: lista de dicts. Devuelve razón (con todos los datos), validación cruzada por grupos y `fiable` (>= MIN_GRUPOS_FIABLE grupos)."""
    x = [f[campo_x] for f in filas]; y = [f[campo_y] for f in filas]; g = [f[campo_grupo] for f in filas]; cv = validacion_cruzada(x, y, g); fiable = cv['n_grupos'] >= MIN_GRUPOS_FIABLE
    nota = (f'{cv["n_grupos"]} grupos: suficientes para una indicación de error' if fiable else f'solo {cv["n_grupos"]} grupos (< {MIN_GRUPOS_FIABLE}): el error de validación cruzada es una indicación, no una garantía')
    return dict(razon=ajustar_razon(x, y), n=len(x), n_grupos=cv['n_grupos'], cv=cv, fiable=fiable, nota=nota)

def estimar(x, razon, error_rel):
    """Estimación y banda declarada: valor = razon·x, [valor(1-e), valor(1+e)]."""
    v = float(razon) * float(x); return dict(valor=v, min=v * (1 - error_rel), max=v * (1 + error_rel), error_rel=float(error_rel))
