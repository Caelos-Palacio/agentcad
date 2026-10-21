"""FEM propio de hexaedros lineales (vóxel cúbico, integración 2x2x2) para verificar geometría final."""
from __future__ import annotations
import sys
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

def _D(E, nu):
    l = E*nu/((1+nu)*(1-2*nu)); m = E/(2*(1+nu))
    D = np.zeros((6, 6)); D[:3, :3] = l; D[range(3), range(3)] += 2*m; D[3:, 3:] = np.eye(3)*m
    return D

_NODE = np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]], float)*2-1

def _B(xi, eta, ze, h):
    dN = np.zeros((3, 8))
    for a, (sx, sy, sz) in enumerate(_NODE):
        dN[0, a] = sx*(1+sy*eta)*(1+sz*ze)/8
        dN[1, a] = sy*(1+sx*xi)*(1+sz*ze)/8
        dN[2, a] = sz*(1+sx*xi)*(1+sy*eta)/8
    dN *= 2/h
    B = np.zeros((6, 24))
    for a in range(8):
        c = 3*a
        B[0, c] = dN[0, a]; B[1, c+1] = dN[1, a]; B[2, c+2] = dN[2, a]
        B[3, c] = dN[1, a]; B[3, c+1] = dN[0, a]
        B[4, c+1] = dN[2, a]; B[4, c+2] = dN[1, a]
        B[5, c] = dN[2, a]; B[5, c+2] = dN[0, a]
    return B

def ke_unit(nu, h=1.0):
    D = _D(1.0, nu); g = 1/np.sqrt(3); K = np.zeros((24, 24))
    for xi in (-g, g):
        for eta in (-g, g):
            for ze in (-g, g):
                B = _B(xi, eta, ze, h); K += B.T@D@B*(h/2)**3
    return K

class Voxel:
    def __init__(self, occ, pitch, origin, E=1900.0, nu=0.38):
        self.occ = np.asarray(occ, bool); self.h = float(pitch); self.o = np.asarray(origin, float)
        self.E = E; self.nu = nu
        nx, ny, nz = self.occ.shape
        ie, je, ke = np.nonzero(self.occ)
        self.eidx = np.stack([ie, je, ke], 1); self.ne = len(ie)
        # nodos (nx+1,ny+1,nz+1)
        nid = -np.ones((nx+1, ny+1, nz+1), np.int64)
        offs = _NODE.astype(int)*0.5+0.5
        offs = offs.astype(int)
        corners = np.stack([self.eidx+o for o in offs], 1)  # ne,8,3
        flat = np.ravel_multi_index(corners.reshape(-1, 3).T, (nx+1, ny+1, nz+1))
        uniq, inv = np.unique(flat, return_inverse=True)
        self.nn = len(uniq); self.enodes = inv.reshape(self.ne, 8)
        xyz = np.stack(np.unravel_index(uniq, (nx+1, ny+1, nz+1)), 1)
        self.xyz = self.o + xyz*self.h
        self.edof = (self.enodes[:, :, None]*3 + np.arange(3)).reshape(self.ne, 24)
        self.Ke0 = ke_unit(nu, self.h)*1.0   # E=1
        self.Ke0 = self.Ke0  # ya incluye h^3 * (1/h)^2 = h
    def assemble(self, xe=None):
        xe = np.ones(self.ne) if xe is None else xe
        I = np.repeat(self.edof, 24, axis=1).ravel(); J = np.tile(self.edof, (1, 24)).ravel()
        V = (xe[:, None]*self.E*self.Ke0.ravel()[None, :]).ravel()
        return sp.coo_matrix((V, (I, J)), shape=(3*self.nn,)*2).tocsc()
    def nodes_where(self, pred):
        return np.nonzero(pred(self.xyz))[0]
    def solve(self, F, fixed_dofs, xe=None):
        K = self.assemble(xe); n = 3*self.nn
        free = np.setdiff1d(np.arange(n), fixed_dofs)
        # eliminar dof desconectados (diagonal ~0)
        Kf = K[free][:, free]
        lu = spla.splu(Kf.tocsc(), permc_spec='COLAMD')
        u = np.zeros(n); u[free] = lu.solve(F[free])
        self.K = None
        return u
    def stress(self, u, xe=None):
        D = _D(self.E, self.nu); B = _B(0, 0, 0, self.h)
        ue = u[self.edof]; s = ue@(D@B).T
        if xe is not None: s = s*xe[:, None]
        return s  # sxx, syy, szz, txy, tyz, txz
    @staticmethod
    def vonmises(s):
        sx, sy, sz, txy, tyz, txz = s.T
        return np.sqrt(0.5*((sx-sy)**2+(sy-sz)**2+(sz-sx)**2)+3*(txy**2+tyz**2+txz**2))
    def compliance(self, F, u): return float(F@u)

def voxelize_tris(tris, pitch, origin, shape, axis=2):
    """Ocupación exacta en centros de vóxel por paridad de rayos paralelos al eje `axis`.
    tris: (n,3,3) mm; origin: esquina mínima de la rejilla; shape: (nx,ny,nz)."""
    ax = axis; ua, ub = [i for i in range(3) if i != ax]
    na, nb, nc = shape[ua], shape[ub], shape[ax]
    jit = pitch*1e-4
    hits = [[] for _ in range(na*nb)]
    for t in tris:
        a, b, c = t[:, ua], t[:, ub], t[:, ax]
        ia0 = max(int(np.ceil((a.min()-origin[ua]-pitch/2-jit)/pitch)), 0); ia1 = min(int(np.floor((a.max()-origin[ua]-pitch/2-jit)/pitch)), na-1)
        ib0 = max(int(np.ceil((b.min()-origin[ub]-pitch/2-jit)/pitch)), 0); ib1 = min(int(np.floor((b.max()-origin[ub]-pitch/2-jit)/pitch)), nb-1)
        if ia1 < ia0 or ib1 < ib0: continue
        det = (b[1]-b[2])*(a[0]-a[2])+(a[2]-a[1])*(b[0]-b[2])
        if abs(det) < 1e-12: continue
        ga, gb = np.meshgrid(np.arange(ia0, ia1+1), np.arange(ib0, ib1+1), indexing='ij')
        pa = origin[ua]+(ga+.5)*pitch+jit; pb = origin[ub]+(gb+.5)*pitch+jit*1.7
        l1 = ((b[1]-b[2])*(pa-a[2])+(a[2]-a[1])*(pb-b[2]))/det
        l2 = ((b[2]-b[0])*(pa-a[2])+(a[0]-a[2])*(pb-b[2]))/det
        l3 = 1-l1-l2
        m = (l1 >= 0)&(l2 >= 0)&(l3 >= 0)
        if not m.any(): continue
        z = l1[m]*c[0]+l2[m]*c[1]+l3[m]*c[2]
        for i, j, zz in zip(ga[m], gb[m], z): hits[i*nb+j].append(zz)
    occ = np.zeros((na, nb, nc), bool)
    zc = origin[ax]+(np.arange(nc)+.5)*pitch
    for k, hz in enumerate(hits):
        if len(hz) < 2: continue
        hz = np.sort(hz)
        if len(hz) % 2: hz = hz[:-1]
        for z0, z1 in zip(hz[0::2], hz[1::2]):
            occ[k//nb, k % nb, (zc > z0)&(zc < z1)] = True
    return np.moveaxis(occ, [0, 1, 2], [ua, ub, ax]) if False else _restore(occ, ua, ub, ax)

def _restore(occ, ua, ub, ax):
    out = np.zeros((0,))
    perm = [ua, ub, ax]
    inv = np.argsort(perm)
    return np.transpose(occ, inv)

def stl_triangles(path):
    """Triángulos (n,3,3) de un STL (binario o ASCII) vía trimesh."""
    import trimesh
    return np.asarray(trimesh.load(str(path), force='mesh').triangles, float)

def voxelize_stl(path, pitch, origin=None, shape=None, axis=2):
    tris = stl_triangles(path)
    lo = tris.reshape(-1, 3).min(0); hi = tris.reshape(-1, 3).max(0)
    if origin is None: origin = lo - pitch*0.0
    if shape is None: shape = np.ceil((hi-origin)/pitch).astype(int)
    return voxelize_tris(tris, pitch, np.asarray(origin, float), tuple(shape), axis), np.asarray(origin, float)

def _energy(self, u, xe=None):
    ue = u[self.edof]
    e = 0.5*self.E*np.einsum('ei,ij,ej->e', ue, self.Ke0, ue)
    return e if xe is None else e*xe
Voxel.energy = _energy

try:   # LU con disección anidada para K grandes (solo con AGENTCAD_FASTLU=1); misma solución hasta ~1e-10 relativo
    from . import fastlu as _fastlu
    _fastlu.install()
except Exception:
    pass
