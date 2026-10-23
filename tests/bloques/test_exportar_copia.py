"""Prueba de contrato del bloque exportar_copia y comportamiento real sobre directorios temporales (nunca fuera de ellos).
El destino simula un USB ya montado. Las pruebas comprueban que el bloque no formatea, no desmonta y no ejecuta subprocesos."""
import collections, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
from tests.bloques import contrato
from agentcad import bloques, pipeline as pl
from agentcad.bloques import exportar_copia

DU = collections.namedtuple('DU', 'total used free')
CLAVES = {'ok', 'copiados', 'ya_estaban', 'verificados', 'tamano_mb', 'necesario_mb', 'libre_antes_mb', 'libre_despues_mb', 'destino', 'registro', 'conflictos', 'mensaje'}


class Contrato(contrato.ContratoBloque):
    NOMBRE = 'exportar_copia'

    def entradas_ejemplo(self, proyecto):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        (proyecto.raiz / 'ejemplo.txt').write_text('contenido de ejemplo')
        return dict(archivos=['ejemplo.txt'], destino=t.name)

    def test_no_es_pesado_y_es_deshacible(self):
        self.assertFalse(self.mod.MANIFIESTO['pesado']); self.assertTrue(self.mod.MANIFIESTO['deshacible']); self.assertTrue(hasattr(self.mod, 'deshacer'))

    def test_cifras_de_espacio_sin_unidad_de_tabla(self):
        for k in ('tamano_mb', 'necesario_mb', 'libre_antes_mb', 'libre_despues_mb'): self.assertNotIn('unidad', self.mod.MANIFIESTO['salidas'][k], k)


class Real(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.r = Path(t.name).resolve()
        u = tempfile.TemporaryDirectory(); self.addCleanup(u.cleanup); self.usb = Path(u.name).resolve()     # simula el USB ya montado
        (self.r / 'agentcad.toml').write_text('[proyecto]\nnombre = "prueba"\n')
        env = mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(self.r), 'AGENTCAD_TRABAJO_DIR': str(self.r / 'trabajo'), 'AGENTCAD_LOCK_HELD': '1'})
        env.start(); self.addCleanup(env.stop)
        self.ctx = dict(raiz=str(self.r))

    def escribir(self, rel, datos=b'contenido'):
        p = self.r / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(datos); return rel

    def exportar(self, archivos, destino=None, **kw):
        return pl.ejecutar_bloque('exportar_copia', dict(archivos=archivos, destino=str(destino or self.usb), **kw), self.ctx)

    def deshacer(self, archivos, destino=None, **kw):
        return exportar_copia.deshacer(dict(archivos=archivos, destino=str(destino or self.usb), **kw), self.ctx)

    def registro(self, out): return json.loads((self.r / out['registro']).read_text(encoding='utf-8'))

    # --- copia y verificación -------------------------------------------------------------------------------------------
    def test_copia_un_archivo_y_compara_bytes(self):
        datos = bytes(range(256)) * 4000                       # ~1 MB, binario
        self.escribir('a.bin', datos)
        out = self.exportar(['a.bin'])
        self.assertEqual(set(out), CLAVES)
        self.assertTrue(out['ok'], out['mensaje']); self.assertEqual((out['copiados'], out['verificados'], out['ya_estaban']), (1, 1, 0))
        self.assertEqual((self.usb / 'a.bin').read_bytes(), datos)
        self.assertEqual(out['tamano_mb'], round(len(datos) / 1_000_000, 3)); self.assertEqual(out['destino'], str(self.usb))
        self.assertTrue(out['registro'].startswith('build/exportar_copia/'))
        self.assertEqual([(a['ruta_relativa_al_destino'], a['bytes']) for a in self.registro(out)['archivos']], [('a.bin', len(datos))])

    def test_copia_directorio_recursivo(self):
        self.escribir('datos/x.txt', b'1'); self.escribir('datos/sub/y.txt', b'22'); self.escribir('datos/sub/profundo/z.bin', b'333')
        out = self.exportar(['datos'])
        self.assertEqual((out['ok'], out['copiados'], out['verificados']), (True, 3, 3))
        for rel in ('x.txt', 'sub/y.txt', 'sub/profundo/z.bin'):
            self.assertEqual((self.usb / 'datos' / rel).read_bytes(), (self.r / 'datos' / rel).read_bytes())

    def test_identico_ya_presente_no_se_toca_ni_se_registra(self):
        self.escribir('a.bin', b'igual'); (self.usb / 'a.bin').write_bytes(b'igual')
        os.utime(self.usb / 'a.bin', ns=(1_000_000_000, 1_000_000_000))
        out = self.exportar(['a.bin'])
        self.assertEqual((out['ok'], out['copiados'], out['ya_estaban']), (True, 0, 1))
        self.assertEqual(os.stat(self.usb / 'a.bin').st_mtime_ns, 1_000_000_000)
        self.assertEqual(out['registro'], '')

    def test_mezcla_registra_solo_lo_copiado(self):
        self.escribir('a.bin', b'igual'); (self.usb / 'a.bin').write_bytes(b'igual'); self.escribir('b.bin', b'nuevo')
        out = self.exportar(['a.bin', 'b.bin'])
        self.assertEqual((out['copiados'], out['ya_estaban']), (1, 1))
        self.assertEqual([a['ruta_relativa_al_destino'] for a in self.registro(out)['archivos']], ['b.bin'])

    def test_verificacion_detecta_corrupcion_y_borra_la_copia(self):
        self.escribir('a.bin', b'uno'); self.escribir('b.bin', b'dos')
        with mock.patch.object(exportar_copia.filecmp, 'cmp', side_effect=[True, False]):
            out = self.exportar(['a.bin', 'b.bin'])
        self.assertFalse(out['ok']); self.assertIn('b.bin', out['mensaje']); self.assertEqual(out['copiados'], 1)
        self.assertTrue((self.usb / 'a.bin').is_file()); self.assertFalse((self.usb / 'b.bin').exists())
        self.assertEqual([a['ruta_relativa_al_destino'] for a in self.registro(out)['archivos']], ['a.bin'])
        self.assertEqual(self.deshacer(['a.bin', 'b.bin'])['borrados'], 1)
        self.assertFalse((self.usb / 'a.bin').exists())

    def test_reanudar_conserva_lo_ya_registrado(self):
        self.escribir('a.bin', b'uno'); self.escribir('b.bin', b'dos')
        with mock.patch.object(exportar_copia.filecmp, 'cmp', side_effect=[True, False]):
            self.exportar(['a.bin', 'b.bin'])                  # se detiene en la verificación de b.bin
        out = self.exportar(['a.bin', 'b.bin'])                # segunda pasada sin fallo
        self.assertEqual((out['ok'], out['copiados'], out['ya_estaban']), (True, 1, 1))
        self.assertEqual([a['ruta_relativa_al_destino'] for a in self.registro(out)['archivos']], ['a.bin', 'b.bin'])
        self.deshacer(['a.bin', 'b.bin'])
        self.assertFalse((self.usb / 'a.bin').exists()); self.assertFalse((self.usb / 'b.bin').exists())

    def test_fallo_de_escritura_borra_el_temporal(self):
        self.escribir('a.bin', b'datos')
        with mock.patch.object(exportar_copia.os, 'fsync', side_effect=OSError(28, 'No queda espacio')):
            with self.assertRaises(OSError): self.exportar(['a.bin'])
        self.assertEqual(list(self.usb.iterdir()), [])

    def test_temporal_de_un_corte_anterior_se_reemplaza(self):
        self.escribir('a.bin', b'bueno'); (self.usb / '.a.bin.agentcad-tmp').write_bytes(b'basura')
        out = self.exportar(['a.bin'])
        self.assertTrue(out['ok'], out['mensaje']); self.assertEqual((self.usb / 'a.bin').read_bytes(), b'bueno')
        self.assertFalse((self.usb / '.a.bin.agentcad-tmp').exists())

    # --- subcarpeta, conflictos y colisiones ----------------------------------------------------------------------------
    def test_subcarpeta_se_crea_y_deshacer_la_quita_si_queda_vacia(self):
        self.escribir('a.bin', b'a')
        out = self.exportar(['a.bin'], subcarpeta='lote/v2')
        self.assertTrue(out['ok'], out['mensaje']); self.assertEqual((self.usb / 'lote' / 'v2' / 'a.bin').read_bytes(), b'a')
        self.assertEqual(self.registro(out)['dirs_creados'], ['lote', 'lote/v2'])
        self.assertEqual(self.deshacer(['a.bin'], subcarpeta='lote/v2')['directorios_borrados'], 2)
        self.assertFalse((self.usb / 'lote').exists())

    def test_subcarpeta_previa_no_se_borra(self):
        (self.usb / 'previa').mkdir(); self.escribir('a.bin', b'a')
        out = self.exportar(['a.bin'], subcarpeta='previa')
        self.assertEqual(self.registro(out)['dirs_creados'], [])
        self.deshacer(['a.bin'], subcarpeta='previa')
        self.assertTrue((self.usb / 'previa').is_dir())

    def test_subcarpeta_con_archivos_ajenos_no_se_borra(self):
        self.escribir('b.bin', b'b'); self.exportar(['b.bin'], subcarpeta='lote2')
        (self.usb / 'lote2' / 'ajeno.txt').write_text('mío')
        d = self.deshacer(['b.bin'], subcarpeta='lote2')
        self.assertEqual((d['borrados'], d['directorios_borrados']), (1, 0))
        self.assertFalse((self.usb / 'lote2' / 'b.bin').exists()); self.assertTrue((self.usb / 'lote2' / 'ajeno.txt').is_file())

    def test_subcarpeta_que_sale_del_destino_rechazada(self):
        self.escribir('a.bin')
        with self.assertRaisesRegex(ValueError, 'subcarpeta'): self.exportar(['a.bin'], subcarpeta='../fuera')

    def test_conflicto_no_sobrescribe_y_no_copia_nada(self):
        self.escribir('a.bin', b'origen'); self.escribir('b.bin', b'otro'); (self.usb / 'a.bin').write_bytes(b'distinto')
        out = self.exportar(['a.bin', 'b.bin'])
        self.assertFalse(out['ok']); self.assertIn('a.bin', out['conflictos'])
        self.assertEqual((self.usb / 'a.bin').read_bytes(), b'distinto'); self.assertFalse((self.usb / 'b.bin').exists())
        self.assertEqual((out['copiados'], out['registro']), (0, ''))

    def test_colision_de_nombres_entre_origenes(self):
        self.escribir('x/n.txt', b'1'); self.escribir('y/n.txt', b'2')
        out = self.exportar(['x/n.txt', 'y/n.txt'])
        self.assertFalse(out['ok']); self.assertIn('n.txt', out['conflictos']); self.assertEqual(list(self.usb.iterdir()), [])

    def test_origenes_inexistentes_fuera_de_raiz_o_vacios(self):
        with self.assertRaises(FileNotFoundError): self.exportar(['no_existe.bin'])
        with self.assertRaisesRegex(ValueError, 'bajo la raíz'): self.exportar(['/etc/passwd'])
        with self.assertRaisesRegex(ValueError, 'vacía'): self.exportar([])

    def test_informa_siempre_las_cifras_de_espacio(self):
        self.escribir('a.bin', b'a')
        out = self.exportar(['a.bin'])
        for k in ('libre_antes_mb', 'libre_despues_mb', 'necesario_mb', 'tamano_mb'): self.assertIsInstance(out[k], float, k)

    def test_espacio_insuficiente_no_copia_y_informa_cifras(self):
        self.escribir('grande.bin', b'x' * 2_000_000)
        with mock.patch.object(exportar_copia.shutil, 'disk_usage', return_value=DU(10_000_000, 9_000_000, 1_000_000)):
            out = self.exportar(['grande.bin'])
        self.assertFalse(out['ok']); self.assertTrue(out['mensaje'].startswith('espacio_insuficiente'), out['mensaje'])
        self.assertEqual((out['copiados'], out['registro']), (0, '')); self.assertEqual(list(self.usb.iterdir()), [])
        self.assertEqual((out['libre_antes_mb'], out['necesario_mb']), (1.0, 2.0))

    # --- destino -------------------------------------------------------------------------------------------------------
    def test_destino_inexistente_lanza_error(self):
        self.escribir('a.bin')
        with self.assertRaises(FileNotFoundError): self.exportar(['a.bin'], destino=self.usb / 'no_existe')

    def test_destino_que_es_archivo_lanza_error(self):
        self.escribir('a.bin'); f = self.usb / 'fichero'; f.write_text('x')
        with self.assertRaises(NotADirectoryError): self.exportar(['a.bin'], destino=f)

    def test_destino_raiz_del_sistema_rechazado(self):
        self.escribir('a.bin')
        with self.assertRaisesRegex(ValueError, 'raíz'): self.exportar(['a.bin'], destino='/')

    def test_destino_dentro_del_origen_rechazado(self):
        self.escribir('datos/f.txt'); (self.r / 'datos' / 'usb').mkdir()
        with self.assertRaisesRegex(ValueError, 'bucle'): self.exportar(['datos'], destino=self.r / 'datos' / 'usb')
        with self.assertRaisesRegex(ValueError, 'bucle'): self.exportar(['datos'], destino=self.r, subcarpeta='datos/copia')

    def test_destinos_permitidos_del_toml(self):
        self.escribir('a.bin', b'a'); otro = tempfile.TemporaryDirectory(); self.addCleanup(otro.cleanup)
        (self.r / 'agentcad.toml').write_text(f'[exportar]\ndestinos_permitidos = [{json.dumps(str(self.usb))}]\n')
        with self.assertRaisesRegex(ValueError, 'destinos_permitidos'): self.exportar(['a.bin'], destino=otro.name)
        self.assertTrue(self.exportar(['a.bin'])['ok'])

    def test_sin_permiso_de_escritura_lanza_error(self):
        self.escribir('a.bin')
        with mock.patch.object(exportar_copia.os, 'access', return_value=False):
            with self.assertRaises(PermissionError): self.exportar(['a.bin'])

    # --- enlaces simbólicos ----------------------------------------------------------------------------------------------
    def test_enlaces_simbolicos_del_origen_se_omiten(self):
        self.escribir('datos/real.txt', b'real')
        os.symlink(self.r / 'datos' / 'real.txt', self.r / 'datos' / 'enlace.txt')
        os.symlink(self.r, self.r / 'datos' / 'enlace_dir')
        out = self.exportar(['datos'])
        self.assertTrue(out['ok']); self.assertEqual(out['copiados'], 1)
        self.assertFalse((self.usb / 'datos' / 'enlace.txt').exists()); self.assertFalse((self.usb / 'datos' / 'enlace_dir').exists())
        self.assertIn('enlace.txt', out['mensaje'])

    # --- deshacer ------------------------------------------------------------------------------------------------------
    def test_deshacer_borra_solo_lo_copiado(self):
        self.escribir('igual.bin', b'mismo'); (self.usb / 'igual.bin').write_bytes(b'mismo'); (self.usb / 'ajeno.txt').write_text('mío')
        self.escribir('nuevo.bin', b'nuevo')
        self.exportar(['igual.bin', 'nuevo.bin'])
        d = self.deshacer(['igual.bin', 'nuevo.bin'])
        self.assertEqual((d['borrados'], d['conservados']), (1, 0))
        self.assertFalse((self.usb / 'nuevo.bin').exists())
        self.assertEqual((self.usb / 'igual.bin').read_bytes(), b'mismo'); self.assertEqual((self.usb / 'ajeno.txt').read_text(), 'mío')

    def test_deshacer_conserva_lo_modificado_despues(self):
        self.escribir('a.bin', b'original'); self.exportar(['a.bin'])
        (self.usb / 'a.bin').write_bytes(b'editado a mano')
        d = self.deshacer(['a.bin'])
        self.assertEqual((d['borrados'], d['conservados']), (0, 1)); self.assertEqual((self.usb / 'a.bin').read_bytes(), b'editado a mano')

    def test_deshacer_es_idempotente_y_sin_registro_no_hace_nada(self):
        self.escribir('a.bin', b'a')
        self.assertEqual(self.deshacer(['a.bin'])['borrados'], 0)           # sin registro previo
        self.exportar(['a.bin'])
        self.assertEqual(self.deshacer(['a.bin'])['borrados'], 1)
        self.assertEqual(self.deshacer(['a.bin'])['borrados'], 0)           # segunda vez: nada que hacer

    # --- modo simulado -------------------------------------------------------------------------------------------------
    def test_simulado_no_escribe_nada_e_informa(self):
        self.escribir('a.bin', b'x' * 1000)
        s = pl.ejecutar_bloque('exportar_copia', dict(archivos=['a.bin'], destino=str(self.usb), subcarpeta='lote'), dict(raiz=str(self.r), simulado=True))
        self.assertTrue(s['ok']); self.assertTrue(s['mensaje'].startswith('ensayo (simulado)'), s['mensaje'])
        self.assertEqual((s['copiados'], s['verificados'], s['registro']), (0, 0, ''))
        self.assertEqual(s['libre_despues_mb'], s['libre_antes_mb']); self.assertGreater(s['necesario_mb'], 0)
        self.assertEqual(list(self.usb.iterdir()), []); self.assertFalse((self.r / 'build').exists())

    def test_simulado_detecta_conflicto_sin_tocarlo(self):
        self.escribir('a.bin', b'origen'); (self.usb / 'a.bin').write_bytes(b'otro')
        s = pl.ejecutar_bloque('exportar_copia', dict(archivos=['a.bin'], destino=str(self.usb)), dict(raiz=str(self.r), simulado=True))
        self.assertFalse(s['ok']); self.assertIn('conflicto', s['mensaje']); self.assertEqual((self.usb / 'a.bin').read_bytes(), b'otro')


class Seguridad(unittest.TestCase):
    PROHIBIDAS = ('subprocess', 'os.system', 'os.popen', 'os.spawn', 'Popen', 'mkfs', 'umount', 'eject', 'fdisk', 'parted', 'rmtree')

    def test_el_modulo_no_contiene_comandos_de_particiones_ni_subprocesos(self):
        codigo = Path(exportar_copia.__file__).read_text(encoding='utf-8')
        for palabra in self.PROHIBIDAS: self.assertNotIn(palabra, codigo, palabra)


class Catalogo(unittest.TestCase):
    def test_linea_del_catalogo_con_marca_D_y_sin_P(self):
        lineas = [l for l in bloques.catalogo().splitlines() if l.startswith('exportar_copia ')]
        self.assertEqual(len(lineas), 1, lineas)
        self.assertTrue(lineas[0].startswith('exportar_copia [D]'), lineas[0])


class RegistroManipulado(unittest.TestCase):
    def test_deshacer_ignora_rutas_con_punto_punto(self):
        import json, os, tempfile
        from pathlib import Path
        from unittest import mock
        from agentcad import pipeline as pl
        from agentcad.bloques import exportar_copia as ex
        with tempfile.TemporaryDirectory() as t:
            t = Path(t).resolve(); (t / 'o').mkdir(); (t / 'o' / 'a.txt').write_text('x'); (t / 'usb').mkdir(); (t / 'ajeno.txt').write_text('no tocar')
            ctx = dict(raiz=str(t / 'o')); e = dict(archivos=['a.txt'], destino=str(t / 'usb'))
            with mock.patch.dict(os.environ, {'AGENTCAD_PROYECTO': str(t / 'o'), 'AGENTCAD_TRABAJO_DIR': str(t / 'o' / 'trabajo'), 'AGENTCAD_RAICES_EXTRA': str(t)}):
                r = pl.ejecutar_bloque('exportar_copia', e, ctx); self.assertTrue(r['ok'], r['mensaje'])
                reg = Path(ctx['raiz']) / r['registro']; d = json.loads(reg.read_text()); d['archivos'].append(dict(ruta_relativa_al_destino='../ajeno.txt', sha256=ex._sha(t / 'ajeno.txt'), bytes=8)); reg.write_text(json.dumps(d))
                ex.deshacer(e, ctx)
            self.assertTrue((t / 'ajeno.txt').is_file()); self.assertFalse((t / 'usb' / 'a.txt').exists())


if __name__ == '__main__': unittest.main()
