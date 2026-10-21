"""Escenarios Gherkin (español) de pipelines con el ejecutor propio; cada escenario es un subTest."""
import unittest
from pathlib import Path
from agentcad import bdd_runner as bd
AQUI = Path(__file__).resolve().parent / 'features' / 'pipelines'
class Escenarios(unittest.TestCase):
    def test_gherkin_en_español(self):
        for f in AQUI.glob('*.feature'): self.assertIn('# language: es', f.read_text())
    def test_todos_los_escenarios(self):
        res = bd.correr_directorio(AQUI, AQUI / 'pasos_pipeline.py'); self.assertGreaterEqual(len(res), 4)
        for r in res:
            with self.subTest(r['escenario']): self.assertEqual(r['estado'], 'ok', f"{r['paso_fallido']}: {r['error']}")
if __name__ == '__main__': unittest.main()
