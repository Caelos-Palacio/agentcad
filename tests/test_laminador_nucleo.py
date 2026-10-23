"""Pruebas del NÚCLEO del laminado (agentcad/laminador.py y agentcad/laminador_falso.py): escritor de 3MF por objetos, copia del datadir, perfiles planos, diagnóstico,
laminador FALSO (gcode sintético) y reintento de choques de soporte. Todo es SINTÉTICO y digital: el laminador falso no predice ningún laminado real."""
import json, os, re, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock
import numpy as np, trimesh
from agentcad import laminador as lam


def stl_dos_cubos(ruta, sep=30.0):
    a = trimesh.creation.box(extents=(20, 20, 10)); a.apply_translation((10, 10, 5))
    b = trimesh.creation.box(extents=(20, 20, 10)); b.apply_translation((30 + sep, 10, 5))
    trimesh.util.concatenate([a, b]).export(ruta)


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.addCleanup(self.t.cleanup); self.r = Path(self.t.name).resolve()
        env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_LOCK_HELD': '1', 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo')}); env.start(); self.addCleanup(env.stop)
        os.environ.pop('AGENTCAD_FALSO_CHOQUE', None)


class Escritor3mf(Base):
    def objs(self):
        a = trimesh.creation.box(extents=(10, 10, 5)); a.apply_translation((5, 5, 2.5))
        return [dict(nombre='pieza_1', vertices=np.asarray(a.vertices), caras=np.asarray(a.faces), ajustes={'layer_height': 0.2, 'enable_support': True, 'nombre_raro': 'a"b<c&d'})]

    def test_escribe_un_zip_con_las_entradas_esperadas_y_ajustes_por_objeto(self):
        f = self.r / 'p.3mf'; lam.escribir_3mf(f, self.objs(), (100.0, 110.0), b'{"a": 1}')
        with zipfile.ZipFile(f) as z:
            n = set(z.namelist())
            self.assertTrue({'[Content_Types].xml', '_rels/.rels', '3D/3dmodel.model', 'Metadata/model_settings.config', 'Metadata/project_settings.config'} <= n)
            self.assertEqual(z.read('Metadata/project_settings.config'), b'{"a": 1}')
            cfg = z.read('Metadata/model_settings.config').decode()
        self.assertIn('key="layer_height" value="0.2"', cfg); self.assertIn('key="enable_support" value="1"', cfg)       # bool -> "1", número -> texto
        import xml.etree.ElementTree as ET
        raiz = ET.fromstring(cfg); vals = {m.get('key'): m.get('value') for m in raiz.iter('metadata')}
        self.assertEqual(vals['nombre_raro'], 'a"b<c&d')                       # XML bien formado: el valor con comillas, < y & sobrevive escapado

    def test_ida_y_vuelta_leer_3mf(self):
        f = self.r / 'p.3mf'; lam.escribir_3mf(f, self.objs(), (100.0, 110.0), b'{}')
        o = lam.leer_3mf(f); self.assertEqual(len(o), 1); self.assertEqual(o[0]['nombre'], 'pieza_1')
        self.assertEqual(o[0]['ajustes']['layer_height'], '0.2'); self.assertEqual(o[0]['ajustes']['enable_support'], '1')
        mn, mx = o[0]['bbox'][0], o[0]['bbox'][1]                              # con el desplazamiento de la cama aplicado
        self.assertEqual(np.round(mx - mn, 3).tolist(), [10.0, 10.0, 5.0]); self.assertAlmostEqual(float(mn[0]), 100.0, 3); self.assertAlmostEqual(float(mn[1]), 110.0, 3)

    def test_determinista_bit_a_bit(self):
        a, b = self.r / 'a.3mf', self.r / 'b.3mf'
        lam.escribir_3mf(a, self.objs(), (1.0, 2.0), b'{}'); lam.escribir_3mf(b, self.objs(), (1.0, 2.0), b'{}')
        self.assertEqual(a.read_bytes(), b.read_bytes())


class CuboPlantilla(Base):
    def test_cubo_es_una_malla_cerrada_con_volumen_positivo(self):
        """Regresión: un cubo con las caras al revés (volumen negativo) lo rechaza el laminador real («Loading of a model file failed»)."""
        lam.escribir_stl_cubo(self.r / 'c.stl', 10.0); m = trimesh.load(str(self.r / 'c.stl'))
        self.assertTrue(m.is_watertight); self.assertTrue(m.is_winding_consistent); self.assertAlmostEqual(float(m.volume), 1000.0, 3)


class Objetos(Base):
    def test_separa_componentes_y_los_nombra_por_posicion(self):
        stl_dos_cubos(self.r / 'p.stl'); o = lam.objetos_de_stl(self.r / 'p.stl', separar=True, prefijo='pieza')
        self.assertEqual([x['nombre'] for x in o], ['pieza_1', 'pieza_2']); self.assertLess(o[0]['vertices'][:, 0].min(), o[1]['vertices'][:, 0].min())
    def test_sin_separar_es_un_solo_objeto(self):
        stl_dos_cubos(self.r / 'p.stl'); self.assertEqual(len(lam.objetos_de_stl(self.r / 'p.stl', separar=False, prefijo='pieza')), 1)
    def test_ajustes_por_objeto_con_comodin(self):
        a = lam.ajustes_objeto({'*': {'wall_loops': 3}, 'pieza_2': {'wall_loops': 4, 'enable_support': 1}}, 'pieza_2', {'sparse_infill_density': '15%'})
        self.assertEqual(a, {'sparse_infill_density': '15%', 'wall_loops': 4, 'enable_support': 1})
        self.assertEqual(lam.ajustes_objeto({'*': {'wall_loops': 3}}, 'pieza_1', {}), {'wall_loops': 3})

    def test_colocacion_centra_y_comprueba_la_cama(self):
        stl_dos_cubos(self.r / 'p.stl'); o = lam.objetos_de_stl(self.r / 'p.stl', True, 'pieza')
        dx, dy = lam.colocar(o, cama=(220.0, 220.0), z_max=250.0, centrar=True, margen=0.0)
        mn = min(x['vertices'][:, 0].min() for x in o) + dx; mx = max(x['vertices'][:, 0].max() for x in o) + dx
        self.assertAlmostEqual((mn + mx) / 2, 110.0, 3)
        with self.assertRaisesRegex(ValueError, 'cama'): lam.colocar(o, cama=(40.0, 40.0), z_max=250.0, centrar=True, margen=0.0)
        with self.assertRaisesRegex(ValueError, 'altura'): lam.colocar(o, cama=(220.0, 220.0), z_max=5.0, centrar=True, margen=0.0)

    def test_holgura_minima_entre_objetos(self):
        stl_dos_cubos(self.r / 'p.stl', sep=8.0); o = lam.objetos_de_stl(self.r / 'p.stl', True, 'pieza')
        self.assertAlmostEqual(lam.holgura_min(o), 8.0, 3)


class Datadir(Base):
    def test_copia_ignora_registros_y_no_toca_el_origen(self):
        o = self.r / 'origen'; (o / 'system' / 'V' / 'machine').mkdir(parents=True); (o / 'system' / 'V' / 'machine' / 'm.json').write_text('{}')
        (o / 'log').mkdir(); (o / 'log' / 'x.log').write_text('x'); (o / 'user_backup-1').mkdir(); (o / 'cache').mkdir()
        antes = sorted(str(p.relative_to(o)) for p in o.rglob('*'))
        d = lam.copiar_datadir(o, self.r / 'copia')
        self.assertTrue((d / 'system' / 'V' / 'machine' / 'm.json').is_file()); self.assertFalse((d / 'log').exists()); self.assertFalse((d / 'user_backup-1').exists())
        self.assertEqual(antes, sorted(str(p.relative_to(o)) for p in o.rglob('*')))
    def test_rechaza_copiar_sobre_si_mismo_o_dentro(self):
        o = self.r / 'origen'; o.mkdir()
        with self.assertRaises(ValueError): lam.copiar_datadir(o, o)
        with self.assertRaises(ValueError): lam.copiar_datadir(o, o / 'dentro')
    def test_origen_inexistente(self):
        with self.assertRaises(FileNotFoundError): lam.copiar_datadir(self.r / 'no', self.r / 'copia')

    def test_perfil_plano_resuelve_inherits(self):
        base = self.r / 'dd' / 'system' / 'V' / 'process'; base.mkdir(parents=True)
        (base / 'padre.json').write_text(json.dumps({'a': 1, 'b': 2, 'name': 'padre'})); (base / 'hijo.json').write_text(json.dumps({'b': 3, 'c': 4, 'name': 'hijo', 'inherits': 'padre'}))
        self.assertEqual(lam.perfil_plano(self.r / 'dd', 'process', 'hijo'), {'a': 1, 'b': 3, 'c': 4, 'name': 'hijo', 'inherits': 'padre'})
        with self.assertRaises(FileNotFoundError): lam.perfil_plano(self.r / 'dd', 'process', 'no_existe')
    def test_perfil_plano_detecta_ciclos(self):
        base = self.r / 'dd' / 'system' / 'V' / 'filament'; base.mkdir(parents=True)
        (base / 'a.json').write_text(json.dumps({'inherits': 'b'})); (base / 'b.json').write_text(json.dumps({'inherits': 'a'}))
        with self.assertRaises(ValueError): lam.perfil_plano(self.r / 'dd', 'filament', 'a')


class Diagnostico(Base):
    def test_choque_con_soporte(self):
        d = lam.diagnosticar(155, 'Error: gcode path conflicts found between objects', hay_soporte=True, tiempo_excedido=False)
        self.assertEqual(d['causa'], 'choque_de_soportes'); self.assertTrue(d['reintentable'])
    def test_choque_sin_soporte_no_reintenta_con_soportes(self):
        d = lam.diagnosticar(155, 'gcode path conflicts', hay_soporte=False, tiempo_excedido=False); self.assertEqual(d['causa'], 'choque_de_trayectorias'); self.assertFalse(d['reintentable'])
    def test_otros(self):
        self.assertEqual(lam.diagnosticar(-11, '', True, False)['causa'], 'caida_del_laminador')
        self.assertEqual(lam.diagnosticar(0, '', True, True)['causa'], 'tiempo_excedido')
        self.assertEqual(lam.diagnosticar(2, 'otra cosa', True, False)['causa'], 'fallo_del_laminador')
        self.assertEqual(lam.diagnosticar(0, '', True, False)['causa'], 'sin_gcode')


class ResumenGcode(Base):
    def test_lee_cabecera_y_pie_estilo_orca(self):
        g = self.r / 'a.gcode'
        g.write_text('; HEADER_BLOCK_START\n; total layer number: 73\n; max_z_height: 14.64\n; HEADER_BLOCK_END\n;LAYER_CHANGE\nG1 X1 Y1 E1\n'
                     + '; filament used [g] = 25.95\n; total filament used [g] = 25.95\n; estimated printing time (normal mode) = 1h 15m 28s\n; estimated printing time (silent mode) = 2h 5m 7s\n')
        r = lam.resumen_gcode(g); self.assertEqual(r['capas'], 73); self.assertAlmostEqual(r['filamento_g'], 25.95); self.assertAlmostEqual(r['tiempo_min'], 75 + 28 / 60, 2)
    def test_sin_cabecera_cuenta_cambios_de_capa(self):
        g = self.r / 'b.gcode'; g.write_text(';LAYER_CHANGE\nG1 X1 E1\n;LAYER_CHANGE\nG1 X2 E1\n')
        r = lam.resumen_gcode(g); self.assertEqual(r['capas'], 2); self.assertIsNone(r['filamento_g']); self.assertIsNone(r['tiempo_min'])


def perfil_falso(**extra): return {**dict(comando=['@falso'], cama_x_mm=220.0, cama_y_mm=220.0, z_max_mm=250.0), **extra}


class LaminarConFalso(Base):
    def correr(self, ajustes=None, sep=30.0, perfil=None, **kw):
        stl_dos_cubos(self.r / 'p.stl', sep=sep)
        return lam.laminar(self.r, self.r / 'p.stl', ajustes or {}, perfil or perfil_falso(), salida=self.r / 'trabajo' / 'lam', **kw)

    def test_lamina_y_resume(self):
        r = self.correr()
        self.assertTrue(r['ok'], r['diagnostico']); self.assertEqual(r['objetos'], 2); self.assertEqual(r['intentos'], 1); self.assertTrue(r['simulado'])
        g = Path(r['gcode']); self.assertTrue(g.is_file()); self.assertGreater(r['capas'], 10); self.assertGreater(r['tiempo_min'], 0); self.assertGreater(r['filamento_g'], 0)
        self.assertIn('EXCLUDE_OBJECT_START', g.read_text()); self.assertLess(g.stat().st_size, 400_000)

    def test_manifiesto_con_unidades_y_hashes(self):
        r = self.correr(); m = json.loads(Path(r['manifiesto']).read_text())
        self.assertEqual(m['esquema'], 'agentcad.laminado/1'); self.assertEqual(m['nivel_validacion'], 'digital'); self.assertTrue(m['simulado'])
        self.assertEqual(m['unidades'], {'tiempo_min': 'min', 'filamento_g': 'g', 'cama_x_mm': 'mm', 'cama_y_mm': 'mm', 'z_max_mm': 'mm', 'holgura_min_mm': 'mm'})
        for k in ('placa', '3mf', 'gcode'): self.assertRegex(m['sha256'][k], r'^[0-9a-f]{64}$')
        self.assertEqual(m['resumen']['capas'], r['capas']); self.assertEqual(m['intentos'][0]['rc'], 0); self.assertIn('aviso', m)

    def test_determinista(self):
        a = self.correr(); b = self.correr(); self.assertEqual(Path(a['gcode']).read_bytes(), Path(b['gcode']).read_bytes())

    def test_ajustes_por_objeto_llegan_al_3mf(self):
        r = self.correr(ajustes={'pieza_2': {'enable_support': 1, 'layer_height': 0.16}})
        o = {x['nombre']: x for x in lam.leer_3mf(Path(r['gcode']).parent / 'placa.3mf')}
        self.assertEqual(o['pieza_2']['ajustes']['layer_height'], '0.16'); self.assertEqual(o['pieza_2']['ajustes']['enable_support'], '1'); self.assertNotIn('enable_support', o['pieza_1']['ajustes'] | {})
        self.assertIn('Support', Path(r['gcode']).read_text())

    def test_alturas_de_capa_distintas_cambian_las_capas(self):
        a = self.correr(ajustes={'*': {'layer_height': 0.2}}); b = self.correr(ajustes={'*': {'layer_height': 0.1}})
        self.assertGreater(b['capas'], a['capas'])

    def test_objeto_fuera_de_la_cama(self):
        with self.assertRaisesRegex(ValueError, 'cama'): self.correr(perfil=perfil_falso(cama_x_mm=40.0, cama_y_mm=40.0))

    def test_choque_de_soportes_reintenta_con_organic_y_angulo_5(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_FALSO_CHOQUE': '1'}):
            r = self.correr(ajustes={'*': {'enable_support': 1, 'support_type': 'tree(auto)'}})
        self.assertTrue(r['ok'], r['diagnostico']); self.assertEqual(r['intentos'], 2); self.assertIn('choque_de_soportes', r['diagnostico']); self.assertIn('organic', r['diagnostico'])
        m = json.loads(Path(r['manifiesto']).read_text()); self.assertEqual(m['intentos'][0]['causa'], 'choque_de_soportes'); self.assertEqual(m['intentos'][0]['rc'], 155)
        self.assertEqual(m['intentos'][1]['rc'], 0); self.assertEqual(m['intentos'][1]['ajustes_proceso']['support_style'], 'organic'); self.assertEqual(m['intentos'][1]['ajustes_proceso']['tree_support_branch_angle'], '5')

    def test_choque_sin_remedio_informa_sin_inventar_gcode(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_FALSO_CHOQUE': 'siempre'}):
            r = self.correr(ajustes={'*': {'enable_support': 1}})
        self.assertFalse(r['ok']); self.assertEqual(r['gcode'], ''); self.assertEqual(r['intentos'], 2); self.assertIn('choque_de_soportes', r['diagnostico'])

    def test_sin_reintentos_declarados_no_reintenta(self):
        with mock.patch.dict(os.environ, {'AGENTCAD_FALSO_CHOQUE': '1'}):
            r = self.correr(ajustes={'*': {'enable_support': 1}}, perfil=perfil_falso(reintentos_soporte=[]))
        self.assertFalse(r['ok']); self.assertEqual(r['intentos'], 1)

    def test_aviso_de_holgura_con_soporte_en_arbol(self):
        r = self.correr(ajustes={'*': {'enable_support': 1, 'support_type': 'tree(auto)'}}, sep=8.0)
        m = json.loads(Path(r['manifiesto']).read_text()); self.assertAlmostEqual(m['holgura_min_mm'], 8.0, 2); self.assertTrue(any('holgura' in a for a in m['avisos']))

    def test_no_deja_la_copia_del_datadir(self):
        r = self.correr(); self.assertFalse(list(Path(r['gcode']).parent.rglob('dd')))

    def test_placa_3mf_se_lamina_tal_cual(self):
        stl_dos_cubos(self.r / 'p.stl'); o = lam.objetos_de_stl(self.r / 'p.stl', True, 'pieza'); dx, dy = lam.colocar(o, (220.0, 220.0), 250.0, True, 0.0)
        lam.escribir_3mf(self.r / 'ya.3mf', o, (dx, dy), b'{}')
        r = lam.laminar(self.r, self.r / 'ya.3mf', {}, perfil_falso(), salida=self.r / 'trabajo' / 'lam3'); self.assertTrue(r['ok'], r['diagnostico']); self.assertEqual(r['objetos'], 2)

    def test_la_orden_del_laminador_usa_solo_copia_del_datadir(self):
        """Con un datadir real (sintético aquí) la orden debe llevar --datadir apuntando a la COPIA, nunca al origen."""
        o = self.r / 'origen'; (o / 'system' / 'V' / 'machine').mkdir(parents=True); (o / 'system' / 'V' / 'machine' / 'M.json').write_text(json.dumps({'name': 'M'}))
        (o / 'system' / 'V' / 'process').mkdir(); (o / 'system' / 'V' / 'process' / 'P.json').write_text(json.dumps({'name': 'P', 'layer_height': '0.2'}))
        (o / 'system' / 'V' / 'filament').mkdir(); (o / 'system' / 'V' / 'filament' / 'F.json').write_text(json.dumps({'name': 'F'}))
        r = self.correr(perfil=perfil_falso(datadir=str(o), maquina='M', proceso='P', filamento='F', ajustes_proceso={'wall_loops': '3'}))
        self.assertTrue(r['ok'], r['diagnostico']); m = json.loads(Path(r['manifiesto']).read_text())
        self.assertTrue(all('--datadir' in c['orden'] for c in m['intentos'])); self.assertNotIn(str(o), ' '.join(m['intentos'][0]['orden']))
        pj = json.loads((Path(r['gcode']).parent / 'proceso.json').read_text()); self.assertEqual(pj['wall_loops'], '3'); self.assertEqual(pj['layer_height'], '0.2')


class Huella(Base):
    def test_cambia_con_la_placa_los_ajustes_y_el_perfil(self):
        stl_dos_cubos(self.r / 'p.stl')
        h = lambda aj=None, pf=None, f='p.stl': lam.huella(self.r, self.r / f, aj or {}, pf or perfil_falso(), simulado=True)
        base = h(); self.assertEqual(base, h())
        self.assertNotEqual(base, h(aj={'*': {'wall_loops': 4}})); self.assertNotEqual(base, h(pf=perfil_falso(cama_x_mm=250.0)))
        stl_dos_cubos(self.r / 'q.stl', sep=40.0); self.assertNotEqual(base, h(f='q.stl'))
        self.assertNotEqual(base, lam.huella(self.r, self.r / 'p.stl', {}, perfil_falso(), simulado=False))

    def test_cache_valida_pide_que_exista_el_gcode(self):
        from agentcad.bloques import laminar
        g = self.r / 'a.gcode'; g.write_text('x')
        self.assertTrue(laminar.cache_valida(dict(ok=True, gcode='a.gcode'), dict(raiz=str(self.r)))); g.unlink()
        self.assertFalse(laminar.cache_valida(dict(ok=True, gcode='a.gcode'), dict(raiz=str(self.r))))
        self.assertTrue(laminar.cache_valida(dict(ok=False, gcode=''), dict(raiz=str(self.r))))     # un fallo determinista también se cachea


class LaminadorFalsoCli(Base):
    def test_cli_exporta_plantilla_y_lamina(self):
        import subprocess, sys
        stl_dos_cubos(self.r / 'p.stl'); out = self.r / 'o'; out.mkdir()
        env = dict(os.environ, PYTHONPATH=str(Path(lam.__file__).resolve().parent.parent))
        c = [sys.executable, '-m', 'agentcad.laminador_falso']
        r = subprocess.run(c + ['--datadir', str(self.r), '--export-3mf', 't.3mf', '--outputdir', str(out), str(self.r / 'p.stl')], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('Metadata/project_settings.config', zipfile.ZipFile(out / 't.3mf').namelist())
        o = lam.objetos_de_stl(self.r / 'p.stl', True, 'pieza'); lam.escribir_3mf(self.r / 'p.3mf', o, (0.0, 0.0), zipfile.ZipFile(out / 't.3mf').read('Metadata/project_settings.config'))
        r = subprocess.run(c + ['--datadir', str(self.r), '--slice', '0', '--outputdir', str(out), str(self.r / 'p.3mf')], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(len(list(out.glob('*.gcode'))), 1)
    def test_cli_sin_archivo_falla(self):
        import subprocess, sys
        r = subprocess.run([sys.executable, '-m', 'agentcad.laminador_falso', '--slice', '0', '--outputdir', str(self.r), str(self.r / 'no.3mf')], capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=str(Path(lam.__file__).resolve().parent.parent)))
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__': unittest.main()
