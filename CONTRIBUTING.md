# Contribuir

agentcad se desarrolla con TDD: primero una prueba que falle, luego el código.

1. Entorno: Python >= 3.12 y `python -m pip install -e .` (numpy, scipy, trimesh, manifold3d, python-fcl, matplotlib, pillow).
2. Pruebas: `python -m unittest discover -s tests -t .` (completas, ~1 min) o `AGENTCAD_RAPIDAS=1 ...` (sin las pesadas). No hace falta pytest.
3. Nuevo bloque: `agentcad nuevo_bloque <nombre>` crea el manifiesto, el esqueleto (borrador) y una prueba de contrato en rojo. Un bloque sin prueba no se registra.
4. Principio central: **lo digital nunca se etiqueta como físico**. Una herramienta que no tenga un modelo validado devuelve `no_validado`/`no_evaluable`, no una cifra. Toda salida nueva lleva `nivel_validacion: "digital"` y sus límites.
5. Determinismo: mismas entradas, mismas salidas. Nada de aleatoriedad sin semilla ni dependencias del reloj en los resultados.
6. Idioma: documentación, mensajes y nombres de dominio en español; el resumen del README también en inglés.
7. No se versionan datos de usuario: `registro/`, `trabajo/`, cachés, binarios de herramientas ni credenciales (ver `.gitignore`).
