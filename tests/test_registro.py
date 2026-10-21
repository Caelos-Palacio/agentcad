import json, os, tempfile, unittest
from pathlib import Path
from tests import fixtures as fx
from agentcad import registro as rg, geom

class Registro(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='agentcad-reg-')); os.environ['AGENTCAD_REGISTRO_DIR'] = str(self.dir)
    def tearDown(self): os.environ.pop('AGENTCAD_REGISTRO_DIR', None)
    def lineas(self): return [json.loads(l) for l in (self.dir / 'registro.jsonl').read_text().splitlines()]

    def test_registra_con_hash_parametros_version(self):
        ruta = fx.cubo(10)
        r = rg.record_result('check_printability', ruta, parametros={'paso_mm': 0.24}, resultado={'veredicto': 'cumple', 'pared_min_mm': 10.0})
        self.assertEqual(r['estado'], 'ok'); L = self.lineas(); self.assertEqual(len(L), 1)
        e = L[0]
        self.assertEqual(e['nivel_validacion'], 'digital'); self.assertEqual(e['herramienta'], 'check_printability')
        self.assertEqual(e['parametros'], {'paso_mm': 0.24}); self.assertEqual(len(e['hash_entradas']), 64)
        self.assertEqual(e['entradas']['sha256_pieza'], geom.sha256_fichero(ruta))
        self.assertIn('agentcad', e['version']); self.assertIn('manifold3d', e['version']['librerias'])
        self.assertEqual(e['resultado']['veredicto'], 'cumple')
    def test_hash_entradas_determinista_y_sensible(self):
        ruta = fx.cubo(10)
        a = rg.record_result('t', ruta, {'a': 1}, {'x': 1})['hash_entradas']; b = rg.record_result('t', ruta, {'a': 1}, {'x': 2})['hash_entradas']
        c = rg.record_result('t', ruta, {'a': 2}, {'x': 1})['hash_entradas']
        self.assertEqual(a, b); self.assertNotEqual(a, c)         # el hash es de ENTRADAS (pieza+parámetros), no del resultado
    def test_cadena_integra_y_detecta_manipulacion(self):
        for i in range(3): rg.record_result('t', fx.cubo(10), {'i': i}, {'ok': True})
        self.assertTrue(rg.verificar_cadena()['integra'])
        f = self.dir / 'registro.jsonl'; L = f.read_text().splitlines(); L[1] = L[1].replace('"ok":true', '"ok":false'); f.write_text('\n'.join(L) + '\n')
        v = rg.verificar_cadena(); self.assertFalse(v['integra']); self.assertEqual(v['primera_linea_rota'], 2)
    def test_nunca_fisico_sin_ensayo(self):
        r = rg.record_result('t', fx.cubo(10), {}, {}, nivel_validacion='fisico')
        self.assertEqual((r['estado'], r['codigo']), ('error', 'nivel_no_permitido'))
        self.assertFalse((self.dir / 'registro.jsonl').exists())
    def test_ensayo_incompleto_no_basta(self):
        r = rg.record_result('t', fx.cubo(10), {}, {}, ensayo={'valor_medido': 3.2})
        self.assertEqual(r['estado'], 'error'); self.assertEqual(r['codigo'], 'ensayo_incompleto')
    def test_con_ensayo_medido_completo_es_fisico(self):
        ens = dict(tipo='flexion_3_puntos', valor_medido=41.5, unidad='N', instrumento='dinamómetro', fecha='2026-10-20', operador='C', evidencia='fotos/ensayo1.jpg')
        r = rg.record_result('ensayo_manual', fx.cubo(10), {}, {}, ensayo=ens)
        self.assertEqual(r['estado'], 'ok'); self.assertEqual(r['nivel_validacion'], 'fisico')
        self.assertEqual(self.lineas()[0]['ensayo']['valor_medido'], 41.5)
    def test_ensayo_con_valor_no_numerico(self):
        ens = dict(tipo='x', valor_medido='alto', unidad='N', instrumento='i', fecha='f', operador='o', evidencia='e')
        self.assertEqual(rg.record_result('t', fx.cubo(10), {}, {}, ensayo=ens)['codigo'], 'ensayo_incompleto')
    def test_herramienta_invalida(self):
        self.assertEqual(rg.record_result('', fx.cubo(10))['codigo'], 'parametro_invalido')
    def test_nivel_digital_explicito_es_valido(self):
        self.assertEqual(rg.record_result('t', fx.cubo(10), nivel_validacion='digital')['nivel_validacion'], 'digital')
    def test_pieza_no_resoluble_se_registra_sin_hash_de_fichero(self):
        rg.record_result('t', 'pieza_inexistente_xyz'); self.assertIsNone(self.lineas()[0]['entradas']['sha256_pieza'])
    def test_verificar_sin_archivo_y_con_json_roto(self):
        self.assertTrue(rg.verificar_cadena()['integra'])
        (self.dir / 'registro.jsonl').write_text('{roto\n'); self.assertEqual(rg.verificar_cadena()['primera_linea_rota'], 1)
    def test_resultado_no_serializable_error(self):
        r = rg.record_result('t', fx.cubo(10), {}, {'x': object()})
        self.assertEqual(r['codigo'], 'no_serializable')
if __name__ == '__main__': unittest.main()
