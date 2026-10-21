"""Base de las pruebas de CONTRATO de bloques (SDD: derivadas del esquema bloque_schema.json y del manifiesto). Cada test_<bloque>.py hereda de ContratoBloque
y fija NOMBRE; añade sus pruebas de comportamiento. Usa copias de trabajo simuladas en directorios temporales: NUNCA toca cad/ ni build/ reales."""
import json, tempfile, unittest
from pathlib import Path
from agentcad import bloques, pipeline as pl, sim_fixture

class Proyecto:
    """Copia de trabajo simulada con limpieza automática. `ctx` es el contexto que reciben los bloques."""
    def __init__(self, fallos=None):
        self._t = tempfile.TemporaryDirectory(prefix='agentcad-test-'); self.info = sim_fixture.crear(Path(self._t.name) / 'p', fallos=fallos)
        self.raiz = Path(self.info['raiz']); self.ctx = dict(raiz=str(self.raiz), simulado=True); self.base_g = self.info['base_g']
    def limpiar(self): self._t.cleanup()
    def leer(self, rel): return (self.raiz / rel).read_text()

class ContratoBloque(unittest.TestCase):
    NOMBRE = None
    def setUp(self):
        if self.NOMBRE is None: self.skipTest('clase base')
        self.p = Proyecto(); self.addCleanup(self.p.limpiar); self.mod = bloques.cargar().get(self.NOMBRE)
    def entradas_ejemplo(self, proyecto): return dict(self.mod.MANIFIESTO.get('ejemplo', {}))
    def test_registrado(self): self.assertIsNotNone(self.mod, bloques.ERRORES.get(self.NOMBRE))
    def test_manifiesto_valido(self): self.assertEqual(bloques.validar_manifiesto(self.mod.MANIFIESTO), [])
    def test_descripcion_corta_de_una_linea(self):
        d = self.mod.MANIFIESTO['descripcion']; self.assertNotIn('\n', d); self.assertLessEqual(len(d), 200)
    def test_deshacer_coherente(self): self.assertEqual(self.mod.MANIFIESTO['deshacible'], hasattr(self.mod, 'deshacer'))
    def test_pesado_es_simulable(self):
        if self.mod.MANIFIESTO['pesado']: self.assertTrue(hasattr(self.mod, 'simular'), 'un bloque pesado debe poder ensayarse en modo simulado')
    def test_no_es_borrador(self): self.assertNotEqual(self.mod.MANIFIESTO.get('estado'), 'borrador', 'implementa el bloque y quita estado=borrador')
    def test_ejemplo_cumple_el_contrato_de_salidas(self):
        sal = pl.ejecutar_bloque(self.NOMBRE, self.entradas_ejemplo(self.p), self.p.ctx)     # valida tipos y salidas declaradas
        self.assertEqual(set(sal), set(self.mod.MANIFIESTO['salidas']))
    def test_rechaza_entrada_desconocida(self):
        with self.assertRaises(pl.PipelineError): pl.ejecutar_bloque(self.NOMBRE, {**self.entradas_ejemplo(self.p), 'no_existe': 1}, self.p.ctx)
    def test_rechaza_tipo_incorrecto(self):
        m = self.mod.MANIFIESTO['entradas']
        if not m: self.skipTest('sin entradas')
        k = next(iter(m)); malo = {'string': 5, 'number': 'x', 'integer': 'x', 'boolean': 'x', 'array': 'x', 'object': 'x'}.get(m[k]['type'])
        if malo is None: self.skipTest('entrada de tipo any')
        with self.assertRaises(pl.PipelineError): pl.ejecutar_bloque(self.NOMBRE, {**self.entradas_ejemplo(self.p), k: malo}, self.p.ctx)
