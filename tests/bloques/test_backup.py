"""Prueba de contrato del bloque backup + comportamiento: copia, no sobrescritura y restauración."""
import unittest
from tests.bloques import contrato
from agentcad import pipeline as pl
from agentcad.bloques import backup

class Contrato(contrato.ContratoBloque):
    NOMBRE = 'backup'

    def test_crea_copia_de_params(self):
        s = pl.ejecutar_bloque(self.NOMBRE, dict(etiqueta='prueba'), self.p.ctx)
        self.assertFalse(s['ya_existia'])
        self.assertEqual(self.p.leer('build/backup_prueba/params.scad'), self.p.leer('params.scad'))

    def test_segunda_llamada_no_sobrescribe(self):
        pl.ejecutar_bloque(self.NOMBRE, dict(etiqueta='prueba'), self.p.ctx)
        original = self.p.leer('build/backup_prueba/params.scad')
        (self.p.raiz / 'params.scad').write_text(original + '\n// cambio posterior\n')
        s = pl.ejecutar_bloque(self.NOMBRE, dict(etiqueta='prueba'), self.p.ctx)
        self.assertTrue(s['ya_existia'])
        self.assertEqual(self.p.leer('build/backup_prueba/params.scad'), original)

    def test_deshacer_restaura_params_modificado(self):
        dentro = dict(etiqueta='prueba'); pl.ejecutar_bloque(self.NOMBRE, dentro, self.p.ctx)
        original = self.p.leer('params.scad')
        (self.p.raiz / 'params.scad').write_text(original + '\n// editado\n')
        backup.deshacer(dentro, self.p.ctx)
        self.assertEqual(self.p.leer('params.scad'), original)

if __name__ == '__main__': unittest.main()
