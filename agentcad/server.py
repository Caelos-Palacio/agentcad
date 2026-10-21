"""Servidor MCP por stdio (JSON-RPC 2.0, un mensaje JSON por línea) sin dependencias externas.
Arranque:  cd <raíz del proyecto con agentcad.toml> && python -m agentcad.server"""
import json, sys
from . import __version__, schema, tools, runner

VERSIONES = ('2025-06-18', '2025-03-26', '2024-11-05')

def _listado():
    return [dict(name=t['name'], description=t['description'], inputSchema=t['inputSchema'], outputSchema=t['outputSchema']) for t in tools.TOOLS.values()]

def llamar(nombre, args):
    t = tools.TOOLS.get(nombre)
    if t is None: return dict(estado='error', codigo='herramienta_desconocida', mensaje=f'herramientas: {sorted(tools.TOOLS)}')
    err = schema.validate(args, t['inputSchema'])
    if err: return dict(estado='error', codigo='argumentos_invalidos', mensaje='; '.join(err[:6]))
    r = tools.llamar_directo(nombre, args) if not t['pesada'] else runner.ejecutar(nombre, args, timeout_s=t['timeout_s'], mem_mb=t['mem_mb'])
    err = schema.validate(r, t['outputSchema'])
    if err: return dict(estado='error', codigo='salida_invalida', mensaje='la herramienta violó su contrato: ' + '; '.join(err[:4]))
    return r

def manejar(msg):
    """Procesa un mensaje JSON-RPC; devuelve la respuesta (dict) o None si es notificación."""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or 'method' not in msg:
        return dict(jsonrpc='2.0', id=msg.get('id') if isinstance(msg, dict) else None, error=dict(code=-32600, message='petición inválida'))
    mid, m, p = msg.get('id'), msg['method'], msg.get('params') or {}
    if 'id' not in msg: return None
    ok = lambda r: dict(jsonrpc='2.0', id=mid, result=r)
    if m == 'initialize':
        v = p.get('protocolVersion'); v = v if v in VERSIONES else VERSIONES[0]
        return ok(dict(protocolVersion=v, capabilities=dict(tools=dict(listChanged=False)), serverInfo=dict(name='agentcad', version=__version__),
                       instructions='Herramientas de verificación digital para piezas impresas en 3D. Todo valor es medido por código; nivel_validacion es siempre "digital".'))
    if m == 'ping': return ok({})
    if m == 'tools/list': return ok(dict(tools=_listado()))
    if m == 'tools/call':
        if not isinstance(p.get('name'), str): return dict(jsonrpc='2.0', id=mid, error=dict(code=-32602, message='falta name'))
        r = llamar(p['name'], p.get('arguments') or {})
        return ok(dict(content=[dict(type='text', text=json.dumps(r, ensure_ascii=False))], structuredContent=r, isError=r.get('estado') == 'error'))
    return dict(jsonrpc='2.0', id=mid, error=dict(code=-32601, message=f'método no soportado: {m}'))

def main():
    for linea in sys.stdin:
        if not linea.strip(): continue
        try: msg = json.loads(linea)
        except ValueError: resp = dict(jsonrpc='2.0', id=None, error=dict(code=-32700, message='JSON inválido'))
        else:
            try: resp = manejar(msg)
            except Exception as e: resp = dict(jsonrpc='2.0', id=msg.get('id') if isinstance(msg, dict) else None, error=dict(code=-32603, message=f'{type(e).__name__}: {e}'))
        if resp is not None: sys.stdout.write(json.dumps(resp, ensure_ascii=False) + '\n'); sys.stdout.flush()

if __name__ == '__main__': main()
