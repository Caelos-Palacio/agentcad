"""R3 contrato: cada herramienta tiene esquema JSON de entrada y salida, rechaza argumentos inválidos y sus salidas reales validan."""
import json, unittest
from tests import fixtures as fx
from agentcad import tools, schema
from tests._marcas import pesada

@pesada
class Contrato(unittest.TestCase):
    def test_mas_de_seis_herramientas_con_nombre_descripcion_y_esquemas(self):
        T = tools.TOOLS
        self.assertGreaterEqual(len(T), 7)
        for n in ('describe_part', 'check_interference', 'check_printability', 'evaluate_structure', 'apply_hex_lightening', 'record_result', 'check_spec'):
            self.assertIn(n, T)
        for n, t in T.items():
            self.assertTrue(t['description']); self.assertEqual(t['inputSchema']['type'], 'object'); self.assertIs(t['inputSchema'].get('additionalProperties'), False)
            self.assertIn('outputSchema', t); self.assertGreater(t['timeout_s'], 0); self.assertGreater(t['mem_mb'], 100)
    def test_todos_los_esquemas_son_json(self):
        json.dumps({n: (t['inputSchema'], t['outputSchema']) for n, t in tools.TOOLS.items()})
    def test_argumentos_invalidos_se_rechazan(self):
        casos = [('describe_part', {}), ('describe_part', {'part': 5}), ('describe_part', {'part': 'x', 'extra': 1}),
                 ('check_printability', {'part': 'x', 'paso_mm': 'ancho'}), ('apply_hex_lightening', {'part': 'x', 'd': 6}),
                 ('record_result', {'herramienta': 'x', 'pieza': 'y', 'nivel_validacion': 'otro'}), ('evaluate_structure', {'part': 'x', 'cases': 'a'})]
        for n, a in casos:
            self.assertTrue(schema.validate(a, tools.TOOLS[n]['inputSchema']), (n, a))
    def test_argumentos_validos_se_aceptan(self):
        ok = [('describe_part', {'part': 'placa_soporte'}), ('check_interference', {'part': 'placa_soporte', 'pose': 'neutra'}), ('check_interference', {'part': 'placa_soporte', 'pose': {'giro': 3}}),
              ('apply_hex_lightening', {'part': 'p', 'd': 6, 'rib': 1.6, 'keep': 1.8}), ('check_spec', {'part': 'p', 'registrar': True})]
        for n, a in ok: self.assertEqual(schema.validate(a, tools.TOOLS[n]['inputSchema']), [], (n, a))
    def test_salidas_reales_validan_contra_su_esquema(self):
        ruta = fx.cubo(10)
        for n, a in [('describe_part', {'part': ruta, 'radio_vecinas_mm': 0}), ('check_printability', {'part': ruta}), ('evaluate_structure', {'part': ruta}),
                     ('check_interference', {'part': ruta}), ('describe_part', {'part': 'no_existe'}), ('check_printability', {'part': 'no_existe'})]:
            out = tools.llamar_directo(n, a)
            self.assertEqual(schema.validate(out, tools.TOOLS[n]['outputSchema']), [], (n, out))
    def test_llamar_valida_entrada_y_devuelve_error_estructurado(self):
        r = tools.llamar_directo('describe_part', {'part': 5})
        self.assertEqual((r['estado'], r['codigo']), ('error', 'argumentos_invalidos'))
        self.assertEqual(tools.llamar_directo('no_hay', {})['codigo'], 'herramienta_desconocida')

@pesada
class R4DigitalNoFisico(unittest.TestCase):
    def recorre(self, o, hallazgos):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == 'nivel_validacion': hallazgos.append(v)
                self.recorre(v, hallazgos)
        elif isinstance(o, list):
            for v in o: self.recorre(v, hallazgos)
    def test_ninguna_herramienta_emite_fisico(self):
        import os, tempfile
        os.environ['AGENTCAD_REGISTRO_DIR'] = tempfile.mkdtemp()
        ruta = fx.placa_con_pilares(nombre='placa_r4.stl')
        llamadas = [('describe_part', {'part': ruta, 'radio_vecinas_mm': 0}), ('check_interference', {'part': ruta}), ('check_printability', {'part': ruta}),
                    ('evaluate_structure', {'part': ruta}), ('apply_hex_lightening', {'part': ruta, 'd': 6, 'rib': 2, 'keep': 2, 'comprobar': False}),
                    ('record_result', {'herramienta': 'x', 'pieza': ruta, 'resultado': {'a': 1}}),
                    ('record_result', {'herramienta': 'x', 'pieza': ruta, 'nivel_validacion': 'fisico'}),
                    ('check_spec', {'part': ruta, 'spec': {'pieza': 'p', 'version': 1, 'requisitos': []}, 'registrar': True})]
        for n, a in llamadas:
            out = tools.llamar_directo(n, a); h = []; self.recorre(out, h)
            self.assertNotIn('fisico', h, n); self.assertNotIn('fisico', json.dumps(out).lower().replace('"fisico"', 'X') if False else h)
            if out.get('estado') == 'ok': self.assertTrue(h and all(x == 'digital' for x in h), (n, h))
        os.environ.pop('AGENTCAD_REGISTRO_DIR')
    def test_el_esquema_de_salida_prohibe_fisico_salvo_en_record_result(self):
        for n, t in tools.TOOLS.items():
            s = json.dumps(t['outputSchema'])
            if n == 'record_result': continue
            self.assertNotIn('fisico', s)
if __name__ == '__main__': unittest.main()
