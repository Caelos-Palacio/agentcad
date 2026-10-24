"""Factorización LU con disección anidada (agentcad/fastlu.py) frente a la factorización base de scipy (splu, COLAMD).
TOLERANCIA DECLARADA: la solución con ND coincide con la de COLAMD hasta TOL_REL = 1e-8 en norma relativa (||x_nd - x_ref|| / ||x_ref||); el residuo relativo ||K x - b|| / ||b||
de la solución con ND es <= 1e-10. Cualquier permutación da la misma solución exacta: solo cambia el redondeo (el origen midió 3,9e-9 como peor caso componente a componente, ~1e-11 en norma)."""
import os, unittest
from unittest import mock
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from agentcad import fastlu, instr
from agentcad.fem3d import Voxel
from tests._marcas import pesada

TOL_REL = 1e-8
TOL_RESIDUO = 1e-10
BASE = fastlu._orig_splu            # el splu de scipy sin redirección (aunque otra prueba haya importado structure/benchmarks y activado la redirección)

def viga(L=40, w=8, t=8, huecos=True, cargas=3):
    occ = np.ones((L, w, t), bool)
    if huecos: occ[10:14, 2:6, :] = False; occ[25:29, :, 2:5] = False
    v = Voxel(occ, 1.0, (0, 0, 0), E=1000.0, nu=0.3)
    fixed = np.concatenate([3 * v.nodes_where(lambda p: p[:, 0] < 1e-9) + d for d in range(3)])
    tip = v.nodes_where(lambda p: p[:, 0] > L - 1e-9); Fs = []
    for k in range(cargas):
        F = np.zeros(3 * v.nn); F[3 * tip + k] = 1.0 / len(tip); Fs.append(F)
    free = np.setdiff1d(np.arange(3 * v.nn), fixed)
    return v, fixed, free, v.assemble()[free][:, free].tocsc(), [F[free] for F in Fs], Fs

def rel(a, b): return np.linalg.norm(a - b) / np.linalg.norm(b)

class Equivalencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.v, cls.fixed, cls.free, cls.K, cls.Fs, cls.Ffull = viga()
    def setUp(self): fastlu._ORD_CACHE.clear(); self.addCleanup(fastlu._ORD_CACHE.clear)
    def test_misma_solucion_que_colamd_en_tres_casos_de_carga(self):
        ref = BASE(self.K, permc_spec='COLAMD'); nd = fastlu.splu_nd(self.K, original=BASE)
        for F in self.Fs:
            x0, x1 = ref.solve(F), nd.solve(F)
            self.assertLess(rel(x1, x0), TOL_REL); self.assertLess(np.linalg.norm(self.K @ x1 - F) / np.linalg.norm(F), TOL_RESIDUO); self.assertEqual(x1.shape, F.shape)
    def test_varios_rhs_a_la_vez(self):
        B = np.stack(self.Fs, 1); ref = BASE(self.K, permc_spec='COLAMD').solve(B); x = fastlu.splu_nd(self.K, original=BASE).solve(B)
        self.assertEqual(x.shape, B.shape); self.assertLess(rel(x, ref), TOL_REL)
    def test_solo_trans_N(self):
        with self.assertRaises(NotImplementedError): fastlu.splu_nd(self.K, original=BASE).solve(self.Fs[0], trans='T')
    def test_envoltura_expone_metodo_y_relleno(self):
        lu = fastlu.splu_nd(self.K, original=BASE); self.assertEqual(lu.metodo, 'nd'); self.assertGreater(lu.nnz, self.K.nnz); self.assertEqual(lu.shape, self.K.shape)
    def test_resultado_fisico_del_fem_identico_con_y_sin_nd(self):
        """Voxel.solve + tensiones de von Mises con la redirección a ND frente a COLAMD: desplazamientos, von Mises y flexibilidad."""
        v, fixed, F = self.v, self.fixed, self.Ffull[2]
        with mock.patch.object(spla, 'splu', BASE): u0 = v.solve(F, fixed); vm0 = v.vonmises(v.stress(u0))
        with mock.patch.object(spla, 'splu', lambda A, *a, **k: fastlu.splu_nd(A, original=BASE)): u1 = v.solve(F, fixed); vm1 = v.vonmises(v.stress(u1))
        self.assertLess(rel(u1, u0), TOL_REL); self.assertLess(rel(vm1, vm0), 1e-7); self.assertAlmostEqual(float(F @ u1) / float(F @ u0), 1.0, places=8)
    def test_el_fem_registra_el_metodo_en_la_etapa_de_factorizacion(self):
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True)
        with mock.patch.object(spla, 'splu', lambda A, *a, **k: fastlu.splu_nd(A, original=BASE)): self.v.solve(self.Ffull[0], self.fixed)
        f = [r for r in instr.registros() if r.get('etapa') == 'fem_factorizacion'][0]; self.assertEqual(f['metodo'], 'nd'); self.assertGreater(f['relleno'], 1.0)
        self.assertIn('fem_ordenacion_nd', {r.get('etapa') for r in instr.registros()})

class Ordenacion(unittest.TestCase):
    def setUp(self): fastlu._ORD_CACHE.clear(); self.addCleanup(fastlu._ORD_CACHE.clear)
    def test_permutacion_valida_y_determinista(self):
        K = viga()[3]; p = fastlu.nd_order(K); self.assertEqual(sorted(p.tolist()), list(range(K.shape[0]))); self.assertTrue(np.array_equal(p, fastlu.nd_order(K)))
    def test_grafo_desconectado(self):
        A = sp.block_diag([sp.diags([4, -1, -1], [0, 1, -1], shape=(300, 300)), sp.diags([4, -1, -1], [0, 1, -1], shape=(250, 250))], format='csc')
        p = fastlu.nd_order(A); self.assertEqual(sorted(p.tolist()), list(range(550)))
        b = np.arange(550, dtype=float); self.assertLess(rel(fastlu.splu_nd(A, original=BASE).solve(b), BASE(A, permc_spec='COLAMD').solve(b)), TOL_REL)
    def test_matriz_menor_que_la_hoja(self):
        A = sp.csc_matrix(np.array([[4., 1, 0], [1, 4, 1], [0, 1, 4]])); b = np.array([1., 2, 3])
        self.assertLess(rel(fastlu.splu_nd(A, original=BASE).solve(b), np.linalg.solve(A.toarray(), b)), 1e-12)
    def test_cache_de_ordenacion_por_patron(self):
        instr.restablecer(); self.addCleanup(instr.restablecer); instr.configurar(activa=True); K = viga(L=20)[3]
        fastlu.splu_nd(K, original=BASE); fastlu.splu_nd(K * 2.0, original=BASE)               # mismo patrón, otros valores
        self.assertEqual(len(fastlu._ORD_CACHE), 1); self.assertEqual(instr.resumir_cache(instr.registros()), {'orden_nd': {'aciertos': 1, 'fallos': 1}})
        self.assertEqual(sum(1 for r in instr.registros() if r.get('etapa') == 'fem_ordenacion_nd'), 1)       # la ordenación solo se paga una vez
    def test_patron_distinto_invalida_la_cache(self):
        fastlu.splu_nd(viga(L=20)[3], original=BASE); k1 = next(iter(fastlu._ORD_CACHE)); fastlu.splu_nd(viga(L=24)[3], original=BASE); self.assertEqual(len(fastlu._ORD_CACHE), 1); self.assertNotIn(k1, fastlu._ORD_CACHE)

class Redireccion(unittest.TestCase):
    """install() cambia scipy.sparse.linalg.splu: cada prueba lo restaura."""
    def entorno(self, **env):
        p = mock.patch.dict(os.environ, env); p.start(); self.addCleanup(p.stop)
        q = mock.patch.object(spla, 'splu', BASE); q.start(); self.addCleanup(q.stop)
    def setUp(self): fastlu._ORD_CACHE.clear(); self.addCleanup(fastlu._ORD_CACHE.clear)
    def test_desactivada_por_defecto(self):
        self.entorno(AGENTCAD_FASTLU='0'); fastlu.install(); self.assertFalse(getattr(spla.splu, '_fastlu', False))
    def test_activa_redirige_colamd_grande(self):
        self.entorno(AGENTCAD_FASTLU='1', AGENTCAD_FASTLU_MIN='100'); fastlu.install(); self.assertTrue(spla.splu._fastlu)
        K = viga(L=20)[3]; self.assertEqual(spla.splu(K, permc_spec='COLAMD').metodo, 'nd')
    def test_respeta_el_umbral_y_otras_opciones(self):
        self.entorno(AGENTCAD_FASTLU='1', AGENTCAD_FASTLU_MIN='20000'); fastlu.install(); K = viga(L=20)[3]
        self.assertFalse(hasattr(spla.splu(K, permc_spec='COLAMD'), 'metodo'))                 # por debajo del umbral: SuperLU normal
        self.entorno(AGENTCAD_FASTLU='1', AGENTCAD_FASTLU_MIN='100'); fastlu.install()
        self.assertFalse(hasattr(spla.splu(K, permc_spec='MMD_AT_PLUS_A'), 'metodo'))          # otra ordenación pedida: no se toca
    def test_si_nd_falla_usa_el_splu_original(self):
        self.entorno(AGENTCAD_FASTLU='1', AGENTCAD_FASTLU_MIN='100'); fastlu.install(); K = viga(L=20)[3]; b = np.ones(K.shape[0])
        with mock.patch.object(fastlu, 'splu_nd', side_effect=RuntimeError('x')): lu = spla.splu(K, permc_spec='COLAMD')
        self.assertLess(rel(lu.solve(b), BASE(K, permc_spec='COLAMD').solve(b)), 1e-12)
    def test_idempotente(self):
        self.entorno(AGENTCAD_FASTLU='1'); fastlu.install(); f = spla.splu; fastlu.install(); self.assertIs(spla.splu, f)

@pesada
class PorEncimaDelUmbral(unittest.TestCase):
    """Un caso por encima de los 20.000 gdl donde ND actúa de verdad: misma solución que COLAMD. El relleno NO se exige menor: en una barra prismática delgada ND rellena
    ligeramente más que COLAMD (medido en validacion/RENDIMIENTO_LU.md); la ventaja de ND se da en cuerpos 3D compactos."""
    def test_igualdad_con_relleno_informado(self):
        fastlu._ORD_CACHE.clear(); v, fixed, free, K, Fs, Ff = viga(L=60, w=12, t=12, huecos=True); self.assertGreater(K.shape[0], 20000)
        ref = BASE(K, permc_spec='COLAMD'); nd = fastlu.splu_nd(K, original=BASE)
        for F in Fs: self.assertLess(rel(nd.solve(F), ref.solve(F)), TOL_REL)
        print(f'\n[{K.shape[0]} gdl] relleno COLAMD {ref.nnz / K.nnz:.2f}x, ND {nd.nnz / K.nnz:.2f}x')

if __name__ == '__main__': unittest.main()
