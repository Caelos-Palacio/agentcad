import shutil
from pathlib import Path
from ._base import raiz, proy
MANIFIESTO = dict(nombre='backup', descripcion='Copia parámetros, ensamblaje, STL y los archivos de [respaldo] a build/backup_<etiqueta>/ (idempotente).',
    entradas={'etiqueta': {'type': 'string'}}, salidas={'ruta': {'type': 'string'}, 'ya_existia': {'type': 'boolean'}},
    precondiciones=['agentcad.toml declara rutas (o los defectos existen)'], efectos=['crea build/backup_<etiqueta>/'], ejemplo={'etiqueta': 'ej'}, pesado=False, deshacible=True,
    honestidad='copia de ficheros; no valida nada')
def _lista(ctx):
    """(archivos, directorios) relativos a la raíz: los de [respaldo] y, además, parámetros, ensamblaje y carpetas de STL."""
    pr = proy(ctx); r = pr.raiz; rel = lambda p: str(p.relative_to(r)) if p else None
    arch = [rel(pr.params), rel(pr.ensamblaje)] + list(pr['respaldo']['archivos']); dirs = [rel(d) for d in pr.dirs_stl] + list(pr['respaldo']['directorios'])
    return [a for a in dict.fromkeys(arch) if a], [d for d in dict.fromkeys(dirs) if d]
def ejecutar(e, ctx):
    r = raiz(ctx); d = r / 'build' / f"backup_{e['etiqueta']}"
    if d.exists(): return dict(ruta=str(d), ya_existia=True)
    d.mkdir(parents=True); arch, dirs = _lista(ctx)
    for a in arch:
        if (r / a).is_file(): (d / a).parent.mkdir(parents=True, exist_ok=True); shutil.copy2(r / a, d / a)
    for x in dirs:
        if (r / x).is_dir(): shutil.copytree(r / x, d / x)
    return dict(ruta=str(d), ya_existia=False)
def deshacer(e, ctx):
    r = raiz(ctx); d = r / 'build' / f"backup_{e['etiqueta']}"; arch, dirs = _lista(ctx)
    for a in arch:
        if (d / a).is_file(): shutil.copy2(d / a, r / a)
    for x in dirs:
        if (d / x).is_dir(): shutil.copytree(d / x, r / x, dirs_exist_ok=True)
    return dict(restaurado=str(d))
