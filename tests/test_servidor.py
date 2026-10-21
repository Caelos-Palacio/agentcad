"""Servidor MCP por stdio (JSON-RPC 2.0, un mensaje JSON por línea) arrancado como proceso real."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from tests import fixtures as fx
PROY = Path(__file__).resolve().parents[2]
from tests._marcas import pesada

@pesada
class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, AGENTCAD_LOCK_HELD='1', AGENTCAD_REGISTRO_DIR=tempfile.mkdtemp())
        cls.p = subprocess.Popen([sys.executable, '-m', 'agentcad.server'], cwd=PROY, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    @classmethod
    def tearDownClass(cls): cls.p.stdin.close(); cls.p.wait(timeout=10)
    def rpc(self, id, method, params=None):
        self.p.stdin.write(json.dumps(dict(jsonrpc='2.0', id=id, method=method, params=params or {})) + '\n'); self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())
    def test_00_initialize(self):
        r = self.rpc(1, 'initialize', dict(protocolVersion='2025-06-18', capabilities={}, clientInfo=dict(name='t', version='0')))
        self.assertEqual(r['id'], 1); self.assertIn('tools', r['result']['capabilities']); self.assertEqual(r['result']['serverInfo']['name'], 'agentcad')
        self.p.stdin.write(json.dumps(dict(jsonrpc='2.0', method='notifications/initialized')) + '\n'); self.p.stdin.flush()   # sin respuesta
    def test_01_ping_y_lista(self):
        self.assertEqual(self.rpc(2, 'ping')['result'], {})
        r = self.rpc(3, 'tools/list'); nombres = {t['name'] for t in r['result']['tools']}
        self.assertTrue({'describe_part', 'check_interference', 'check_printability', 'evaluate_structure', 'apply_hex_lightening', 'record_result', 'check_spec'} <= nombres)
        for t in r['result']['tools']: self.assertIn('inputSchema', t); self.assertIn('outputSchema', t)
    def test_02_llamada_real_estructurada(self):
        r = self.rpc(4, 'tools/call', dict(name='describe_part', arguments=dict(part=fx.cubo(10), radio_vecinas_mm=0)))
        res = r['result']; self.assertFalse(res['isError'])
        self.assertAlmostEqual(res['structuredContent']['volumen_mm3'], 1000.0, delta=0.01)
        self.assertEqual(json.loads(res['content'][0]['text'])['componentes'], 1)
    def test_03_error_de_herramienta_es_iserror(self):
        res = self.rpc(5, 'tools/call', dict(name='describe_part', arguments=dict(part='no_existe')))['result']
        self.assertTrue(res['isError']); self.assertEqual(res['structuredContent']['codigo'], 'pieza_no_encontrada')
    def test_04_argumentos_invalidos(self):
        res = self.rpc(6, 'tools/call', dict(name='describe_part', arguments=dict(part=3)))['result']
        self.assertTrue(res['isError']); self.assertEqual(res['structuredContent']['codigo'], 'argumentos_invalidos')
    def test_05_metodo_desconocido_y_json_roto(self):
        self.assertEqual(self.rpc(7, 'foo/bar')['error']['code'], -32601)
        self.p.stdin.write('{no es json\n'); self.p.stdin.flush(); self.assertEqual(json.loads(self.p.stdout.readline())['error']['code'], -32700)
    def test_06_record_result_via_servidor(self):
        res = self.rpc(8, 'tools/call', dict(name='record_result', arguments=dict(herramienta='t', pieza=fx.cubo(10), resultado={'a': 1})))['result']
        self.assertEqual(res['structuredContent']['nivel_validacion'], 'digital')
if __name__ == '__main__': unittest.main()
