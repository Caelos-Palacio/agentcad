"""Generador de bloques (TDD): `agentcad nuevo_bloque <nombre>` crea el manifiesto + esqueleto (estado borrador) y su prueba de contrato.
La prueba nace ROJA (el bloque es borrador y no implementado); un bloque sin prueba no se registra (bloques.cargar). Para promoverlo: implementar, quitar `estado='borrador'`."""
import re
from pathlib import Path
from . import bloques

BLOQUE = '''"""Bloque {nombre}: TODO una línea. Contrato en MANIFIESTO (agentcad/bloque_schema.json); prueba en tests/bloques/test_{nombre}.py."""
MANIFIESTO = dict(nombre='{nombre}', descripcion='TODO: describir en UNA línea qué hace el bloque.',
    entradas={{}}, salidas={{'ok': {{'type': 'boolean'}}}},
    precondiciones=[], efectos=[], pesado=False, deshacible=False,
    honestidad='TODO: digital vs físico; usar no_validado donde no haya modelo de carga.',
    estado='borrador', ejemplo={{}})
def ejecutar(e, ctx):
    raise NotImplementedError('bloque {nombre} sin implementar')
# def simular(e, ctx): ...   (obligatorio si pesado=True: devuelve salidas sintéticas leyendo sim.json)
# def deshacer(e, ctx): ...  (obligatorio si deshacible=True)
'''
PRUEBA = '''"""Prueba de contrato del bloque {nombre} (generada por `agentcad nuevo_bloque`). Añadir aquí las pruebas de comportamiento ANTES de implementar."""
import unittest
from tests.bloques import contrato

class Contrato(contrato.ContratoBloque):
    NOMBRE = '{nombre}'
    # def entradas_ejemplo(self, proyecto): return {{...}}   # si el ejemplo del manifiesto necesita rutas de la copia de trabajo

if __name__ == '__main__': unittest.main()
'''
def crear(nombre, raiz=None):
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,39}', nombre): raise ValueError('nombre inválido: minúsculas, dígitos y _, 3-40 caracteres, empezando por letra')
    b = bloques.AQUI / f'{nombre}.py'; t = bloques.PRUEBAS / f'test_{nombre}.py'
    if b.exists() or t.exists(): raise FileExistsError(f'ya existe el bloque o su prueba: {nombre}')
    if not t.parent.is_dir(): raise FileNotFoundError('nuevo_bloque necesita un checkout del repositorio (tests/bloques/)')
    t.write_text(PRUEBA.format(nombre=nombre)); b.write_text(BLOQUE.format(nombre=nombre))
    return [str(b), str(t)]
