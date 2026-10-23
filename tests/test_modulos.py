"""Humo: todos los módulos del paquete compilan e importan (un error de sintaxis en un módulo sin pruebas propias pasaba desapercibido, p. ej. demo_agente)."""
import importlib, pkgutil, unittest
import agentcad

class Importables(unittest.TestCase):
    def test_todos_los_modulos_importan(self):
        for m in pkgutil.walk_packages(agentcad.__path__, 'agentcad.'):
            if m.name.endswith('__main__'): continue
            with self.subTest(modulo=m.name): importlib.import_module(m.name)

if __name__ == '__main__': unittest.main()
