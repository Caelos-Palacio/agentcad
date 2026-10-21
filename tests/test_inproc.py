"""Pruebas en proceso de worker.py y server.py (las del proceso hijo/stdio real no cuentan en la cobertura de líneas)."""
import io, json, os, sys, tempfile, unittest
from unittest import mock
from agentcad import worker, server, tools

def correr_worker(tool, args):
    ent = io.StringIO(json.dumps(dict(tool=tool, args=args))); sal = io.StringIO()
    with mock.patch('sys.stdin', ent), mock.patch('sys.stdout', sal), mock.patch('sys.stderr', io.StringIO()):
        worker.main()
        sys.stdout = sys.__stdout__ if False else sys.stdout
    linea = [l for l in sal.getvalue().splitlines() if l.startswith(worker.MARCA)][-1]
    return json.loads(linea[len(worker.MARCA):])
from tests._marcas import pesada

@pesada
class WorkerEnProceso(unittest.TestCase):
    def setUp(self): os.environ['AGENTCAD_TEST_TOOLS'] = '1'; os.environ.pop('AGENTCAD_MEM_MB', None); os.environ.pop('AGENTCAD_TIMEOUT_S', None)
    def test_pseudo_herramientas(self):
        self.assertEqual(correr_worker('_dormir', {'segundos': 0})['estado'], 'ok')
        self.assertEqual(correr_worker('_reservar', {'mb': 1})['estado'], 'ok')
        r = correr_worker('_fallar', {}); self.assertEqual(r['codigo'], 'excepcion_interna')
    def test_herramienta_real(self):
        self.assertTrue(correr_worker('verify_registro', {})['integra'])
    def test_memoria_error_se_traduce(self):
        with mock.patch.object(tools, 'llamar_directo', side_effect=MemoryError()):
            self.assertEqual(correr_worker('describe_part', {'part': 'x'})['codigo'], 'memoria_excedida')
    def test_pseudo_deshabilitadas_por_defecto(self):
        os.environ['AGENTCAD_TEST_TOOLS'] = '0'
        self.assertEqual(correr_worker('_dormir', {})['codigo'], 'herramienta_desconocida')

@pesada
class ServidorEnProceso(unittest.TestCase):
    def setUp(self): os.environ['AGENTCAD_REGISTRO_DIR'] = tempfile.mkdtemp()
    def tearDown(self): os.environ.pop('AGENTCAD_REGISTRO_DIR', None)
    def test_initialize_version_desconocida_usa_la_ultima(self):
        r = server.manejar(dict(jsonrpc='2.0', id=1, method='initialize', params=dict(protocolVersion='1999-01-01')))
        self.assertEqual(r['result']['protocolVersion'], server.VERSIONES[0])
    def test_notificacion_no_responde_y_peticion_invalida(self):
        self.assertIsNone(server.manejar(dict(jsonrpc='2.0', method='notifications/initialized')))
        self.assertEqual(server.manejar([1])['error']['code'], -32600)
    def test_tools_call_sin_name(self):
        self.assertEqual(server.manejar(dict(jsonrpc='2.0', id=2, method='tools/call', params={}))['error']['code'], -32602)
    def test_llamada_ligera_y_herramienta_desconocida(self):
        r = server.manejar(dict(jsonrpc='2.0', id=3, method='tools/call', params=dict(name='verify_registro', arguments={})))
        self.assertFalse(r['result']['isError']); self.assertTrue(r['result']['structuredContent']['integra'])
        r = server.manejar(dict(jsonrpc='2.0', id=4, method='tools/call', params=dict(name='nada', arguments={})))
        self.assertTrue(r['result']['isError']); self.assertEqual(r['result']['structuredContent']['codigo'], 'herramienta_desconocida')
    def test_salida_que_viola_el_contrato_se_detecta(self):
        with mock.patch.object(tools, 'llamar_directo', return_value={'estado': 'ok'}):
            r = server.llamar('verify_registro', {})
        self.assertEqual(r['codigo'], 'salida_invalida')
    def test_bucle_main_con_json_roto_y_excepcion(self):
        lineas = '{roto\n\n' + json.dumps(dict(jsonrpc='2.0', id=5, method='ping')) + '\n'
        sal = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(lineas)), mock.patch('sys.stdout', sal): server.main()
        out = [json.loads(l) for l in sal.getvalue().splitlines()]
        self.assertEqual(out[0]['error']['code'], -32700); self.assertEqual(out[1]['result'], {})
        with mock.patch.object(server, 'manejar', side_effect=RuntimeError('x')), mock.patch('sys.stdin', io.StringIO(json.dumps(dict(jsonrpc='2.0', id=6, method='ping')) + '\n')), mock.patch('sys.stdout', sal):
            server.main()
        self.assertEqual(json.loads(sal.getvalue().splitlines()[-1])['error']['code'], -32603)
if __name__ == '__main__': unittest.main()
