"""Marcas de pruebas. AGENTCAD_RAPIDAS=1 omite las PESADAS (FEM, voxelización fina, procesos con límites de tiempo/memoria, aligerado);
las que necesitan OpenSCAD se omiten si `openscad` no está en el PATH (la suite actual no tiene ninguna: el ejemplo se genera con manifold3d)."""
import os, shutil, unittest
pesada = unittest.skipIf(os.environ.get('AGENTCAD_RAPIDAS') == '1', 'prueba pesada (AGENTCAD_RAPIDAS=1)')
requiere_openscad = unittest.skipIf(shutil.which('openscad') is None, 'requiere OpenSCAD en el PATH')
