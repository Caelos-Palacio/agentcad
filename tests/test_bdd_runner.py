import unittest
from agentcad import bdd_runner as bd

TXT = '''# language: es
Característica: Suma
  Antecedentes:
    Dado un contador en 10
  Escenario: suma simple
    Cuando le sumo 5
    Y le sumo 1,5
    Entonces el contador es 16,5
  Escenario: falla
    Cuando le sumo 1
    Entonces el contador es 99
    Y este paso se salta
  Esquema del escenario: tabla
    Cuando le sumo <n>
    Entonces el contador es <t>
    Ejemplos:
      | n | t  |
      | 1 | 11 |
      | 2 | 12 |
  Escenario: paso sin definir
    Cuando hago algo inventado
'''

def reg():
    r = bd.Registro()
    @r.paso(r'un contador en (?P<n>[\d,.]+)')
    def _(ctx, n): ctx.c = bd.num(n)
    @r.paso(r'le sumo (?P<n>[\d,.]+)')
    def _(ctx, n): ctx.c += bd.num(n)
    @r.paso(r'el contador es (?P<n>[\d,.]+)')
    def _(ctx, n): assert ctx.c == bd.num(n), f'esperado {n}, obtenido {ctx.c}'
    return r

class Parseo(unittest.TestCase):
    def test_estructura(self):
        f = bd.parsear(TXT)
        self.assertEqual(f.nombre, 'Suma'); self.assertEqual(len(f.antecedentes), 1)
        self.assertEqual([e.nombre for e in f.escenarios], ['suma simple', 'falla', 'tabla [n=1, t=11]', 'tabla [n=2, t=12]', 'paso sin definir'])
        self.assertEqual(f.escenarios[0].pasos[1], ('Y', 'le sumo 1,5'))
        self.assertEqual(f.escenarios[2].pasos[0][1], 'le sumo 1')
    def test_num_coma_decimal(self):
        self.assertEqual(bd.num('1,5'), 1.5); self.assertEqual(bd.num('2'), 2.0); self.assertEqual(bd.num('1.2'), 1.2)

class Ejecucion(unittest.TestCase):
    def setUp(self): self.res = {r['escenario']: r for r in bd.ejecutar(bd.parsear(TXT), reg())}
    def test_ok(self): self.assertEqual(self.res['suma simple']['estado'], 'ok')
    def test_fallo_y_salto(self):
        r = self.res['falla']; self.assertEqual(r['estado'], 'fallo')
        self.assertEqual(r['paso_fallido'], 'el contador es 99'); self.assertIn('esperado 99', r['error'])
        self.assertEqual(r['saltados'], ['este paso se salta'])
    def test_esquema(self):
        self.assertEqual(self.res['tabla [n=1, t=11]']['estado'], 'ok'); self.assertEqual(self.res['tabla [n=2, t=12]']['estado'], 'ok')
    def test_indefinido(self):
        r = self.res['paso sin definir']; self.assertEqual(r['estado'], 'indefinido'); self.assertEqual(r['paso_fallido'], 'hago algo inventado')
    def test_contexto_se_reinicia(self):
        self.assertEqual(self.res['suma simple']['estado'], 'ok')       # si el contexto persistiera, 'tabla' fallaría con otro valor inicial
    def test_resumen_y_codigo_de_salida(self):
        r = bd.resumen(list(self.res.values())); self.assertEqual((r['ok'], r['fallo'], r['indefinido']), (3, 1, 1)); self.assertFalse(r['exito'])
class CLI(unittest.TestCase):
    def _montar(self, final):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp()); (d / 'a.feature').write_text('Característica: X\n  Escenario: e\n    Dado hago ' + final + '\n')
        (d / 'pasos.py').write_text('from agentcad import bdd_runner as bd\nREGISTRO = bd.Registro()\n@REGISTRO.paso(r"hago bien")\ndef _(ctx): pass\n')
        return d
    def test_main_exito_y_fallo(self):
        import contextlib, io
        d = self._montar('bien')
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(bd.main([str(d), '--pasos', str(d / 'pasos.py')]), 0)
        d = self._montar('mal')
        with contextlib.redirect_stdout(io.StringIO()) as o: self.assertEqual(bd.main([str(d), '--pasos', str(d / 'pasos.py')]), 1)
        self.assertIn('INDEFINIDO', o.getvalue())
if __name__ == '__main__': unittest.main()
