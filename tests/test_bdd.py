"""Ejecuta los escenarios Gherkin de tests/features/*.feature con el ejecutor propio (cada escenario es un subTest)."""
import unittest
from pathlib import Path
from agentcad import bdd_runner as bd
AQUI = Path(__file__).resolve().parent
from tests._marcas import pesada

@pesada
class Escenarios(unittest.TestCase):
    def test_hay_escenarios_en_español(self):
        fs = sorted((AQUI / 'features').glob('*.feature')); self.assertGreaterEqual(len(fs), 3)
        for f in fs: self.assertIn('# language: es', f.read_text())
    def test_todos_los_escenarios(self):
        res = bd.correr_directorio(AQUI / 'features', AQUI / 'features' / 'pasos.py')
        self.assertGreaterEqual(len(res), 9)
        for r in res:
            with self.subTest(r['escenario']):
                self.assertEqual(r['estado'], 'ok', f"{r['paso_fallido']}: {r['error']}")
if __name__ == '__main__': unittest.main()
