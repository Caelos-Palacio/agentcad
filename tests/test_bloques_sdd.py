"""SDD de bloques: pruebas DERIVADAS de bloque_schema.json y de los manifiestos (una por bloque y regla) + nuevo_bloque (TDD: sin prueba no se registra)."""
import json, shutil, unittest
from pathlib import Path
from agentcad import bloques, nuevo_bloque, pipeline as pl, schema

class Esquemas(unittest.TestCase):
    def test_esquemas_son_json_y_tienen_id(self):
        for n in ('bloque_schema.json', 'pipeline_schema.json'): self.assertIn('$id', json.loads((Path(bloques.AQUI).parent / n).read_text()))
    def test_ningun_bloque_quedo_sin_registrar(self): self.assertEqual(bloques.ERRORES, {}, bloques.ERRORES) if bloques.cargar() else self.fail()
    def test_manifiesto_invalido_se_rechaza(self):
        m = dict(bloques.cargar()['puerta_masa'].MANIFIESTO)
        for k in ('descripcion', 'entradas', 'honestidad'): self.assertTrue(bloques.validar_manifiesto({a: b for a, b in m.items() if a != k}), k)
        self.assertTrue(bloques.validar_manifiesto({**m, 'descripcion': 'dos\nlíneas largas'})); self.assertTrue(bloques.validar_manifiesto({**m, 'pesado': 'si'}))
        self.assertTrue(bloques.validar_manifiesto({**m, 'entradas': {'x': {'type': 'complejo'}}})); self.assertTrue(bloques.validar_manifiesto({**m, 'raro': 1}))
    def test_default_incoherente_con_su_tipo(self):
        m = dict(bloques.cargar()['puerta_masa'].MANIFIESTO); m['entradas'] = {'x': {'type': 'integer', 'default': 'a'}}; self.assertTrue(bloques.validar_manifiesto(m))
for _n in sorted(bloques.cargar()):
    def _t(n):
        def f(self):
            m = bloques.cargar()[n].MANIFIESTO; self.assertEqual(bloques.validar_manifiesto(m), [])
            self.assertTrue((bloques.PRUEBAS / f'test_{n}.py').is_file()); self.assertEqual(m['deshacible'], hasattr(bloques.cargar()[n], 'deshacer'))
            self.assertIn('ok', m['salidas'] if n.startswith('puerta_') else {'ok': 0}, 'las puertas devuelven ok')
            self.assertTrue(m['honestidad'].strip())
        return f
    setattr(Esquemas, f'test_derivada_{_n}', _t(_n))

class Catalogo(unittest.TestCase):
    def test_una_linea_por_bloque_y_ayuda(self):
        c = bloques.catalogo().splitlines(); self.assertEqual(len([l for l in c if not l.startswith('#')]), len(bloques.cargar()))
        for n in bloques.cargar(): self.assertIn(n, bloques.ayuda(n))
    def test_presupuesto_de_tokens_del_catalogo(self):          # ~4 caracteres/token (cota prudente); el catálogo debe caber en pocos miles de tokens
        self.assertLess(len(bloques.catalogo()) / 3.5, 2500)

class NuevoBloque(unittest.TestCase):
    N = 'bloque_efimero_xyz'
    def tearDown(self):
        for p in (bloques.AQUI / f'{self.N}.py', bloques.PRUEBAS / f'test_{self.N}.py'): p.unlink(missing_ok=True)
        bloques.cargar(forzar=True)
    def test_genera_manifiesto_esqueleto_y_prueba(self):
        rutas = nuevo_bloque.crear(self.N); self.assertTrue(all(Path(r).is_file() for r in rutas)); bloques.cargar(forzar=True)
        self.assertEqual(bloques.cargar()[self.N].MANIFIESTO['estado'], 'borrador'); self.assertIn('borrador', bloques.catalogo())
    def test_la_prueba_nace_roja_y_el_ejecutor_rechaza_borradores(self):
        import subprocess, sys
        nuevo_bloque.crear(self.N); r = subprocess.run([sys.executable, '-W', 'ignore', '-m', 'unittest', f'tests.bloques.test_{self.N}'], capture_output=True, text=True, cwd=str(bloques.AQUI.parents[1]))
        self.assertNotEqual(r.returncode, 0); self.assertIn('borrador', r.stderr)
        bloques.cargar(forzar=True); p = dict(esquema='agentcad.pipeline/1', nombre='xyz', descripcion='x', parametros={}, pasos=[{'id': 'a', 'bloque': self.N}]); self.assertIn('borrador', ' '.join(pl.validar(p)))
    def test_sin_prueba_no_se_registra(self):
        nuevo_bloque.crear(self.N); (bloques.PRUEBAS / f'test_{self.N}.py').unlink(); bloques.cargar(forzar=True)
        self.assertNotIn(self.N, bloques.cargar()); self.assertIn('sin prueba de contrato', bloques.ERRORES[self.N]); self.assertIn('NO registrado', bloques.catalogo())
    def test_nombre_invalido_o_repetido(self):
        for mal in ('X', 'con espacio', '1abc', '../x'):
            with self.assertRaises(ValueError): nuevo_bloque.crear(mal)
        with self.assertRaises(FileExistsError): nuevo_bloque.crear('puerta_masa')
if __name__ == '__main__': unittest.main()
