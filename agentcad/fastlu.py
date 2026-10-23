"""Factorización LU dispersa con ordenación de disección anidada (ND) calculada solo con el grafo de la matriz.

`scipy.sparse.linalg.splu(..., permc_spec='COLAMD')` produce un relleno de ~24x en rejillas de vóxel 3D
(un eslabón de 106k gdl a 1,0 mm: 106k gdl, 7,1M nnz, pico 3,1 GB). Una ordenación por disección anidada (separadores = niveles
intermedios de BFS) reduce relleno, tiempo y memoria sin cambiar la solución (solo el orden de redondeo; ~1e-12 relativo).
No necesita METIS ni coordenadas: sirve para cualquier K. Solo usa numpy/scipy.

    lu = fastlu.splu_nd(Kf)          # mismo uso que splu: lu.solve(b)
    fastlu.install()                  # redirige splu(..., permc_spec='COLAMD') de matrices grandes (lo hace fem3d.py)

Variables de entorno: AGENTCAD_FASTLU=1 ACTIVA la redirección (por defecto desactivada para no cambiar procesos ajenos en curso; structure.py la activa al evaluar); AGENTCAD_FASTLU_MIN (por defecto 20000: por debajo, COLAMD es igual o más rápido) = gdl mínimos.
"""
from __future__ import annotations
import functools, os
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse import csgraph
from . import instr

LEAF = 100          # tamaño de hoja (medido en una pieza de 1,5 mm de paso: 30->10,0x, 100->10,2x, 600->11,8x, 2500->16,6x de relleno; COLAMD 12,4x)

def _levels(G, s):
    """Nivel BFS de cada nodo desde s (−1 si no alcanzable), con el Dijkstra sin pesos de scipy (C)."""
    d = csgraph.dijkstra(G, directed=False, unweighted=True, indices=s)
    lev = np.full(G.shape[0], -1, np.int64); ok = np.isfinite(d); lev[ok] = d[ok].astype(np.int64)
    return lev

def _nd_graph(G, leaf):
    """Disección anidada sobre un grafo simétrico G (CSR, sin diagonal). Devuelve la permutación de sus nodos."""
    n = G.shape[0]
    # pila de tareas: ('sub', nodos) o ('emit', nodos); los separadores se emiten DESPUÉS de sus hijos
    stack = [('sub', np.arange(n))]
    result = []
    while stack:
        kind, nodes = stack.pop()
        if kind == 'emit': result.append(nodes); continue
        if len(nodes) <= leaf:
            if len(nodes): result.append(nodes)
            continue
        sub = G[nodes][:, nodes].tocsr()
        nc, lab = csgraph.connected_components(sub, directed=False)
        if nc > 1:
            for c in range(nc - 1, -1, -1): stack.append(('sub', nodes[lab == c]))
            continue
        # componente conexa: BFS desde un nodo pseudo-periférico
        s = 0
        for _ in range(2):
            lev = _levels(sub, s); s = int(np.argmax(lev))
        lev = _levels(sub, s)
        cnt = np.bincount(lev); cum = np.cumsum(cnt)
        # separador: nivel que equilibra mitades, preferiendo niveles pequeños
        half = len(nodes) / 2; cand = np.nonzero((cum - cnt > 0.25*len(nodes)) & (cum < 0.75*len(nodes)))[0]
        if len(cand) == 0: cand = np.array([int(np.argmin(np.abs(cum - half)))])
        k = cand[np.argmin(cnt[cand])]
        low = nodes[lev < k]; sep = nodes[lev == k]; high = nodes[lev > k]
        if len(low) == 0 or len(high) == 0:           # no se puede dividir: hoja
            result.append(nodes); continue
        # orden de ejecución: low, high y luego sep (pila LIFO => se empuja al revés)
        stack.append(('emit', sep)); stack.append(('sub', high)); stack.append(('sub', low))
    perm = np.concatenate(result)
    assert len(perm) == n and len(np.unique(perm)) == n
    return perm

def nd_order(A):
    """Permutación (array de índices de A) por disección anidada. A: matriz dispersa cuadrada (patrón simétrico o no).
    Agrupa los gdl con patrón de fila idéntico (los 3 gdl de un nodo) en un nodo del grafo: 7x menos aristas.
    Cualquier permutación da la misma solución; solo cambia el rendimiento."""
    A = sp.csr_matrix(A); A.sort_indices(); n = A.shape[0]
    S = (abs(A) + abs(A.T)).tocsr(); S.sort_indices()
    rng = np.random.default_rng(12345); R = rng.integers(1, 2**63 - 1, size=n, dtype=np.int64).astype(np.uint64)
    h = np.add.reduceat(R[S.indices], S.indptr[:-1]) if S.nnz else np.zeros(n, np.uint64)
    _, cls = np.unique(h, return_inverse=True); nc = int(cls.max()) + 1
    P = sp.csr_matrix((np.ones(n), (np.arange(n), cls)), shape=(n, nc))
    Q = (P.T @ S @ P).tocsr(); Q.setdiag(0); Q.eliminate_zeros(); Q.data[:] = 1
    pc = _nd_graph(Q, max(10, LEAF // 3))
    pos = np.empty(nc, np.int64); pos[pc] = np.arange(nc)
    return np.argsort(pos[cls], kind='stable')

class NDLU:
    """Envuelve SuperLU sobre P A P^T con ordenación natural; mismo `solve` que SuperLU."""
    metodo = 'nd'
    def __init__(self, A, perm, lu): self.perm = perm; self._lu = lu; self.shape = A.shape
    @property
    def nnz(self): return self._lu.nnz
    def solve(self, b, trans='N'):
        if trans != 'N': raise NotImplementedError
        y = self._lu.solve(np.ascontiguousarray(np.asarray(b, dtype=float)[self.perm]))
        x = np.empty_like(y); x[self.perm] = y
        return x
    @property
    def L(self): return self._lu.L
    @property
    def U(self): return self._lu.U

_orig_splu = spla.splu

_ORD_CACHE: dict = {}      # patrón disperso -> permutación (en SIMP el patrón de K es idéntico en todas las iteraciones)

def _pattern_key(A):
    import hashlib
    h = hashlib.blake2b(A.indptr.tobytes(), digest_size=16); h.update(A.indices.tobytes())
    return (A.shape[0], int(A.nnz), h.digest())

def splu_nd(A, original=None):
    """LU con ordenación ND. Para K simétrica definida positiva; sin pivoteo (diag_pivot_thresh=0) y modo simétrico.
    La permutación se reutiliza si el patrón de A es el mismo que en la llamada anterior (típico del bucle SIMP)."""
    A = sp.csc_matrix(A); A.sort_indices()
    key = _pattern_key(A); perm = _ORD_CACHE.get(key)
    instr.cache_evento('orden_nd', perm is not None, n_dof=int(A.shape[0]))
    if perm is None:
        with instr.etapa('fem_ordenacion_nd', n_dof=int(A.shape[0])):
            perm = nd_order(A)
        _ORD_CACHE.clear(); _ORD_CACHE[key] = perm          # solo la última: una permutación ocupa 8 B por gdl
    Ap = A[perm][:, perm].tocsc()
    lu = (original or _orig_splu)(Ap, permc_spec='NATURAL', diag_pivot_thresh=0.0, options=dict(SymmetricMode=True))
    return NDLU(A, perm, lu)


def install():
    """(Solo con AGENTCAD_FASTLU=1) Redirige splu(A, permc_spec='COLAMD') de matrices grandes a la versión ND. Si algo falla, usa el splu original."""
    if os.environ.get('AGENTCAD_FASTLU', '0') != '1' or getattr(spla.splu, '_fastlu', False): return
    nmin = int(os.environ.get('AGENTCAD_FASTLU_MIN', '20000'))
    prev = spla.splu
    @functools.wraps(prev)
    def splu(A, *a, **k):
        if k.get('permc_spec') == 'COLAMD' and not a and A.shape[0] >= nmin and A.shape[0] == A.shape[1]:
            try: return splu_nd(A, original=prev)
            except Exception: pass
        return prev(A, *a, **k)
    splu._fastlu = True
    spla.splu = splu
