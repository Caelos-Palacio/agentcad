import copy, json, os, tempfile, unittest
from pathlib import Path
from agentcad import spec as sp, config

ESQUEMA = Path(config.ROOT / 'spec_schema.json')

def spec_ok():
    return dict(esquema='agentcad.spec/1', pieza='placa_x', version=1, descripcion='d', prioridades=['seguridad', 'masa'],
        orientacion_impresion=dict(rot_deg=[0, 0, 0], soporte='no', fuente='agentcad.toml [impresion]'),
        zonas_obligatorias=[dict(id='agujeros', tipo='agujeros_conservados', referencia='linea_base:placa_soporte', tolerancia_mm=0.1)],
        cargas=[dict(id='mano', descripcion='apoyo de la mano', valor=30.0, unidad='N', fuente='agentcad.toml [estructura.placa_soporte]', supuesto=False)],
        requisitos=[dict(id='pared', metrica='fabricabilidad.pared_min_mm', op='>=', valor=1.2, unidad='mm', prioridad=1),
                    dict(id='masa', metrica='describe.masa_estimada_g', op='<=', valor=30.0, unidad='g', prioridad=2)])

class Esquema(unittest.TestCase):
    def test_esquema_versionado_y_obligatorios(self):
        s = json.loads(ESQUEMA.read_text())
        self.assertIn('version', s); self.assertEqual(s['$schema'][:4], 'http')
        for c in ('esquema', 'pieza', 'version', 'prioridades', 'orientacion_impresion', 'zonas_obligatorias', 'cargas', 'requisitos'): self.assertIn(c, s['required'])
        self.assertIn('supuesto', s['$defs']['carga']['required']); self.assertIn('fuente', s['$defs']['carga']['required'])
        for c in ('metrica', 'op', 'valor', 'unidad'): self.assertIn(c, s['$defs']['requisito']['required'])

class Validador(unittest.TestCase):
    def malo(self, mut):
        s = spec_ok(); mut(s); r = sp.check_spec_file(s); self.assertFalse(r['valido'], r); return ' | '.join(r['errores'])
    def test_valida(self):
        r = sp.check_spec_file(spec_ok()); self.assertTrue(r['valido'], r); self.assertEqual(r['errores'], [])
    def test_falta_cargas(self): self.assertIn('cargas', self.malo(lambda s: s.pop('cargas')))
    def test_falta_orientacion(self): self.assertIn('orientacion_impresion', self.malo(lambda s: s.pop('orientacion_impresion')))
    def test_carga_sin_supuesto_ni_fuente(self):
        m = self.malo(lambda s: s['cargas'][0].pop('supuesto')); self.assertIn('supuesto', m)
        m = self.malo(lambda s: s['cargas'][0].update(fuente='')); self.assertIn('fuente', m)
    def test_supuesto_no_booleano(self): self.assertIn('supuesto', self.malo(lambda s: s['cargas'][0].update(supuesto='si')))
    def test_requisito_sin_unidad(self): self.assertIn('unidad', self.malo(lambda s: s['requisitos'][0].pop('unidad')))
    def test_op_invalido(self): self.assertIn('op', self.malo(lambda s: s['requisitos'][0].update(op='==')))
    def test_umbral_no_numerico(self): self.assertIn('valor', self.malo(lambda s: s['requisitos'][0].update(valor='1,2')))
    def test_ids_duplicados(self): self.assertIn("duplicado", self.malo(lambda s: s['requisitos'][1].update(id='pared')))
    def test_metrica_desconocida(self):
        m = self.malo(lambda s: s['requisitos'][0].update(metrica='fabricabilidad.inventada')); self.assertIn('inventada', m); self.assertIn('métricas conocidas', m)
    def test_seccion_desconocida(self): self.assertIn('sección', self.malo(lambda s: s['requisitos'][0].update(metrica='magia.x')))
    def test_unidad_incoherente_con_la_metrica(self):
        m = self.malo(lambda s: s['requisitos'][0].update(unidad='g')); self.assertIn("unidad 'g'", m); self.assertIn('mm', m)
    def test_orientacion_mal_formada(self): self.assertIn('rot_deg', self.malo(lambda s: s['orientacion_impresion'].update(rot_deg=[0, 0])))
    def test_zona_caja_sin_caja(self):
        self.assertIn('caja_mm', self.malo(lambda s: s['zonas_obligatorias'].append(dict(id='c', tipo='caja_material', fraccion_min=0.9))))
    def test_zona_agujeros_sin_referencia(self): self.assertIn('referencia', self.malo(lambda s: s['zonas_obligatorias'][0].pop('referencia')))
    def test_zona_caja_sin_fraccion(self):
        self.assertIn('fraccion_min', self.malo(lambda s: s['zonas_obligatorias'].append(dict(id='c', tipo='caja_material', caja_mm=[[0, 0, 0], [1, 1, 1]]))))
    def test_prioridad_de_requisito_no_declarada(self):
        self.assertIn('prioridades', self.malo(lambda s: s['requisitos'][0].update(clase_prioridad='inventada')))
    def test_propiedad_extra(self): self.assertIn('inesperada', self.malo(lambda s: s.update(inesperada=1)))
    def test_esquema_version_desconocido(self): self.assertIn('esquema', self.malo(lambda s: s.update(esquema='agentcad.spec/99')))
    def test_aviso_orientacion_distinta_del_perfil(self):
        s = spec_ok(); s['pieza'] = 'pieza_vertical'; s['orientacion_impresion']['rot_deg'] = [0, 0, 0]       # [impresion.pieza_vertical] dice [-90,0,0]
        r = sp.check_spec_file(s); self.assertTrue(any('impresion' in a for a in r['avisos'])); self.assertTrue(r['valido'])
    def test_aviso_supuestos(self):
        s = spec_ok(); s['cargas'][0]['supuesto'] = True; r = sp.check_spec_file(s); self.assertTrue(any('supuesto' in a for a in r['avisos']))
    def test_ruta_inexistente_y_json_roto(self):
        self.assertFalse(sp.check_spec_file('/no/existe.json')['valido'])
        f = Path(tempfile.mkdtemp()) / 'x.json'; f.write_text('{roto'); r = sp.check_spec_file(str(f)); self.assertFalse(r['valido']); self.assertIn('JSON', r['errores'][0])
    def test_acepta_ruta(self):
        f = Path(tempfile.mkdtemp()) / 'x.json'; f.write_text(json.dumps(spec_ok())); self.assertTrue(sp.check_spec_file(str(f))['valido'])

class Repositorio(unittest.TestCase):
    def test_todas_las_specs_del_repositorio_son_validas_segun_el_esquema_formal(self):
        fs = sorted(config.specs_dir().glob('*.json')); self.assertTrue(fs)
        for f in fs:
            with self.subTest(f.name):
                r = sp.check_spec_file(str(f)); self.assertTrue(r['valido'], r['errores'])
                self.assertEqual(json.loads(f.read_text())['pieza'], f.stem)
if __name__ == '__main__': unittest.main()
