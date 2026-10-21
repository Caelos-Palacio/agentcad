"""R3: límites de tiempo y memoria por herramienta, y cola con flock."""
import fcntl, os, subprocess, sys, tempfile, time, unittest
from agentcad import runner

os.environ['AGENTCAD_TEST_TOOLS'] = '1'
from tests._marcas import pesada

@pesada
class Limites(unittest.TestCase):
    def setUp(self): self.lock = tempfile.mktemp(prefix='agentcad-lock-')
    def test_ejecucion_normal(self):
        r = runner.ejecutar('_dormir', {'segundos': 0.1}, timeout_s=20, mem_mb=3000, lock=self.lock)
        self.assertEqual(r['estado'], 'ok')
    def test_timeout_mata_el_proceso(self):
        t = time.time(); r = runner.ejecutar('_dormir', {'segundos': 30}, timeout_s=2, mem_mb=3000, lock=self.lock)
        self.assertEqual((r['estado'], r['codigo']), ('error', 'timeout')); self.assertLess(time.time() - t, 15)
    def test_timeout_en_codigo_nativo_sin_cooperar(self):
        r = runner.ejecutar('_bucle_nativo', {}, timeout_s=2, mem_mb=3000, lock=self.lock)
        self.assertEqual(r['codigo'], 'timeout')
    def test_limite_de_memoria(self):
        r = runner.ejecutar('_reservar', {'mb': 3000}, timeout_s=30, mem_mb=1200, lock=self.lock)
        self.assertEqual((r['estado'], r['codigo']), ('error', 'memoria_excedida'))
    def test_dentro_del_limite_de_memoria(self):
        r = runner.ejecutar('_reservar', {'mb': 100}, timeout_s=30, mem_mb=1200, lock=self.lock)
        self.assertEqual(r['estado'], 'ok')
    def test_excepcion_de_la_herramienta_es_error_estructurado(self):
        r = runner.ejecutar('_fallar', {}, timeout_s=20, mem_mb=3000, lock=self.lock)
        self.assertEqual((r['estado'], r['codigo']), ('error', 'excepcion_interna')); self.assertIn('RuntimeError', r['mensaje'])
    def test_herramienta_desconocida(self):
        self.assertEqual(runner.ejecutar('nada', {}, timeout_s=5, mem_mb=1000, lock=self.lock)['codigo'], 'herramienta_desconocida')

@pesada
class CasosLimite(unittest.TestCase):
    def setUp(self): self.lock = tempfile.mktemp(prefix='agentcad-lock-')
    def test_vigilancia_externa_mata_lo_que_ignora_la_alarma(self):
        t = time.time(); r = runner.ejecutar('_ignora_alarma', {}, timeout_s=1, mem_mb=3000, lock=self.lock, espera_lock_s=1)
        self.assertEqual(r['codigo'], 'timeout'); self.assertLess(time.time() - t, 30)
    def test_abort_nativo_se_informa_como_memoria(self):
        self.assertEqual(runner.ejecutar('_abortar', {}, timeout_s=10, mem_mb=3000, lock=self.lock)['codigo'], 'memoria_excedida')
    def test_salida_inesperada(self):
        r = runner.ejecutar('_salir', {}, timeout_s=10, mem_mb=3000, lock=self.lock)
        self.assertEqual((r['estado'], r['codigo']), ('error', 'fallo_proceso'))

@pesada
class Cola(unittest.TestCase):
    def setUp(self):
        self.lock = tempfile.mktemp(prefix='agentcad-lock-'); self._held = os.environ.pop('AGENTCAD_LOCK_HELD', None)   # estas pruebas SÍ necesitan que el runner tome el lock
    def tearDown(self):
        if self._held is not None: os.environ['AGENTCAD_LOCK_HELD'] = self._held
    def test_espera_del_lock_agotada(self):
        fh = open(self.lock, 'w'); fcntl.flock(fh, fcntl.LOCK_EX)           # otro agente tiene la cola
        try:
            t = time.time(); r = runner.ejecutar('_dormir', {'segundos': 0.1}, timeout_s=20, mem_mb=3000, lock=self.lock, espera_lock_s=2)
            self.assertEqual((r['estado'], r['codigo']), ('error', 'cola_ocupada')); self.assertLess(time.time() - t, 12)
        finally: fh.close()
    def test_toma_el_lock_cuando_se_libera(self):
        fh = open(self.lock, 'w'); fcntl.flock(fh, fcntl.LOCK_EX)
        p = subprocess.Popen([sys.executable, '-c', f'import time,fcntl;f=open({self.lock!r});time.sleep(0.01)'])  # no-op
        fcntl.flock(fh, fcntl.LOCK_UN); fh.close(); p.wait()
        self.assertEqual(runner.ejecutar('_dormir', {'segundos': 0.1}, timeout_s=20, mem_mb=3000, lock=self.lock)['estado'], 'ok')
    def test_con_lock_ya_tomado_por_el_llamador_no_hay_interbloqueo(self):
        fh = open(self.lock, 'w'); fcntl.flock(fh, fcntl.LOCK_EX); os.environ['AGENTCAD_LOCK_HELD'] = '1'
        try: self.assertEqual(runner.ejecutar('_dormir', {'segundos': 0.1}, timeout_s=20, mem_mb=3000, lock=self.lock, espera_lock_s=2)['estado'], 'ok')
        finally: os.environ.pop('AGENTCAD_LOCK_HELD'); fh.close()
if __name__ == '__main__': unittest.main()
