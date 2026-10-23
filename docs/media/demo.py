#!/usr/bin/env python3
"""Deterministic motion-graphics demo for the README.

Regenerate:  python docs/media/demo.py        (writes docs/media/demo.gif)

Every frame is a pure function of time: render(t) -> PIL.Image. No mutable globals,
no wall-clock, no unseeded randomness. The terminal text is REAL output captured from
`agentcad bloque puerta_pared_min` and `python -m agentcad.demo_agente` run on
ejemplos/soporte_simple (lines abridged with "..." where marked); the isometric plate is an
illustration of the check, not a rendering of the STL.
"""
import math, os, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DUR = 800, 450, 15, 10.0           # 150 frames, seamless loop (t and t+DUR are identical)
SS = 2                                        # supersampling factor
BG, FG, MUTED, ACCENT, OK, ERR, WARN = '#0d1117', '#e6edf3', '#8b949e', '#58a6ff', '#3fb950', '#f85149', '#d29922'
PANEL = '#12181f'; LINE = '#262d36'

FONT_PATHS = [os.path.expanduser('~/.local/share/fonts/JetBrainsMonoNerd/JetBrainsMonoNerdFont-Regular.ttf'),
              '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 'DejaVuSansMono.ttf']
def font(px):
    for p in FONT_PATHS:
        try: return ImageFont.truetype(p, px * SS)
        except OSError: pass
    return ImageFont.load_default()
F_TERM, F_SMALL, F_CHIP, F_BIG = font(12), font(10), font(11), font(26)

# --- real captured output: (start_time_s, chars_per_s, text, color) -------------------------------
CMD1 = '$ agentcad bloque puerta_pared_min --entradas ...'
OUT1 = '{"ok": true, "pared_min_mm": 1.4736, ...}'
CMD2 = '$ python -m agentcad.demo_agente'
OUT2 = ['1. describe_part: 9.9441 g, 4 agujeros, 1 componente(s)',
        "2.2. {'d': 10.0, 'rib': 1.2, 'keep': 1.5}: 10 ventanas,",
        '     9.9441 -> 6.6446 g, spec: cumple',
        '4. verify_registro: integra=True (12 lineas)']
LINES = [(0.5, 38, CMD1, FG), (1.7, 400, OUT1, OK), (3.3, 34, CMD2, FG),
         (4.3, 300, OUT2[0], MUTED), (5.0, 300, OUT2[1], FG), (5.5, 300, OUT2[2], OK), (7.3, 300, OUT2[3], OK)]
T_SCAN = (1.7, 3.0)      # wall-thickness scan sweeps the plate
T_HEX0, T_HEXDT = 5.0, 0.12   # hexagonal windows appear one by one (10 windows)
M0, M1 = 9.9441, 6.6446  # g, from the captured output
FADE_IN, FADE_OUT = 0.4, 9.3

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease(x):             # ease-in-out cubic
    x = clamp(x); return 4*x**3 if x < 0.5 else 1 - (-2*x + 2)**3 / 2
def seg(t, a, b): return ease((t - a) / (b - a))
def mix(c1, c2, k):
    a = [int(c1[i:i+2], 16) for i in (1, 3, 5)]; b = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
def fade(c, k): return mix(BG, c, clamp(k))

# --- isometric projection of a plate 60 x 40 x 3 mm ----------------------------------------------
OX, OY, S = 612, 218, 3.1
def iso(x, y, z=0.0):
    return ((OX + (x - y) * math.cos(math.radians(30)) * S) * SS, (OY + (x + y) * 0.5 * S - z * S * 1.6 - 40) * SS)
PL, PW, PT = 60.0, 40.0, 3.0
HEX = [(x, y) for row, y in enumerate((9.5, 20.0, 30.5)) for x in ((14, 26, 38, 50) if row != 1 else (8, 20, 32, 44, 56))]
HEX = [h for h in HEX if not ((h[0] < 12 and h[1] < 12) or (h[0] > 48 and h[1] < 12) or (h[0] < 12 and h[1] > 28) or (h[0] > 48 and h[1] > 28))][:10]
HOLES = [(5, 5), (55, 5), (5, 35), (55, 35)]

def poly(d, pts, fill, outline=None, w=1):
    d.polygon(pts, fill=fill)
    if outline: d.line(pts + [pts[0]], fill=outline, width=w * SS, joint='curve')

def hexagon(cx, cy, r, z, k=1.0):
    return [iso(cx + r * k * math.cos(math.radians(a)), cy + r * k * math.sin(math.radians(a)), z) for a in range(0, 360, 60)]

def draw_plate(d, t, a):
    top = fade('#1f3a5f', a); left = fade('#16283f', a); right = fade('#101c2c', a); edge = fade(ACCENT, a * 0.9)
    A, B, C, D = (iso(0, 0, PT), iso(PL, 0, PT), iso(PL, PW, PT), iso(0, PW, PT))
    poly(d, [iso(0, PW, PT), iso(PL, PW, PT), iso(PL, PW, 0), iso(0, PW, 0)], left, edge)
    poly(d, [iso(PL, 0, PT), iso(PL, PW, PT), iso(PL, PW, 0), iso(PL, 0, 0)], right, edge)
    poly(d, [A, B, C, D], top, edge)
    # mounting holes (given, kept)
    for (hx, hy) in HOLES:
        d.polygon([iso(hx + 2.2 * math.cos(math.radians(g)), hy + 2.2 * math.sin(math.radians(g)), PT) for g in range(0, 360, 20)], fill=fade(BG, a), outline=fade(MUTED, a * 0.8))
    # hex windows: grow with ease, appear in sequence
    for i, (hx, hy) in enumerate(HEX):
        k = seg(t, T_HEX0 + i * T_HEXDT, T_HEX0 + i * T_HEXDT + 0.45)
        if k <= 0: continue
        pts = hexagon(hx, hy, 4.6, PT, k)
        d.polygon(pts, fill=fade(BG, a), outline=fade(ACCENT, a * (0.4 + 0.6 * k)))
    # wall-thickness scan: a plane sweeping along x
    s = seg(t, *T_SCAN)
    if 0 < s < 1:
        x = PL * s; ga = a * math.sin(math.pi * s) ** 0.5
        d.line([iso(x, 0, PT), iso(x, PW, PT)], fill=fade(WARN, ga), width=2 * SS)
        d.polygon([iso(x, 0, PT), iso(x, PW, PT), iso(x, PW, PT + 9), iso(x, 0, PT + 9)], fill=fade(mix(BG, WARN, 0.16), ga))

def text(d, xy, s, f, fill, anchor='la'): d.text((xy[0] * SS, xy[1] * SS), s, font=f, fill=fill, anchor=anchor)

def chip(d, x, y, label, k, color):
    if k <= 0: return
    a = clamp(k); yy = y + (1 - k) * 6
    w = 8 + len(label) * 7.0 + 16
    d.rounded_rectangle([x * SS, yy * SS, (x + w) * SS, (yy + 20) * SS], radius=4 * SS, outline=fade(color, a), width=SS, fill=fade(mix(BG, color, 0.12), a))
    d.ellipse([(x + 8) * SS, (yy + 7) * SS, (x + 14) * SS, (yy + 13) * SS], fill=fade(color, a))
    text(d, (x + 20, yy + 4), label, F_CHIP, fade(FG, a))

def render(t):
    """Frame at time t seconds (pure: same t -> same pixels)."""
    t = t % DUR
    a = ease(t / FADE_IN) if t < FADE_IN else (1 - ease((t - FADE_OUT) / (DUR - FADE_OUT)) if t > FADE_OUT else 1.0)
    img = Image.new('RGB', (W * SS, H * SS), BG); d = ImageDraw.Draw(img)
    # terminal panel
    d.rounded_rectangle([24 * SS, 24 * SS, 468 * SS, 408 * SS], radius=8 * SS, fill=PANEL, outline=LINE, width=SS)
    for i, c in enumerate((ERR, WARN, OK)): d.ellipse([(40 + i * 16) * SS, 38 * SS, (48 + i * 16) * SS, 46 * SS], fill=fade(c, 0.85))
    text(d, (446, 36), 'examples/soporte_simple', F_SMALL, MUTED, 'ra')
    d.line([24 * SS, 58 * SS, 468 * SS, 58 * SS], fill=LINE, width=SS)
    y = 72; last = None
    for (t0, cps, s, col) in LINES:
        n = int(clamp((t - t0) * cps, 0, len(s))) if t >= t0 else 0
        if n == 0: continue
        text(d, (40, y), s[:n], F_TERM, fade(col, a)); last = (y, n, s)
        y += 20 + (10 if s is OUT1 or s == OUT2[3] and False else 0)
        if s == OUT1: y += 14
    # cursor (period 1 s divides the loop)
    cy, cn, cs = last if last else (72, 0, '')
    if int(t * 2) % 2 == 0 and a > 0.5:
        cx = 40 + cn * 7.22
        d.rectangle([cx * SS, (cy + 1) * SS, (cx + 7) * SS, (cy + 15) * SS], fill=fade(ACCENT, a))
    # right: the part and the checks
    text(d, (500, 36), 'placa_soporte', F_CHIP, fade(FG, a)); text(d, (500, 52), '60 x 40 x 3 mm, 4 holes', F_SMALL, fade(MUTED, a))
    draw_plate(d, t, a)
    n_hex = sum(1 for i in range(len(HEX)) if t >= T_HEX0 + i * T_HEXDT + 0.2)
    mass = M0 + (M1 - M0) * sum(seg(t, T_HEX0 + i * T_HEXDT, T_HEX0 + i * T_HEXDT + 0.45) for i in range(len(HEX))) / len(HEX)
    text(d, (500, 292), 'estimated mass', F_SMALL, fade(MUTED, a))
    text(d, (500, 306), f'{mass:5.2f} g', F_BIG, fade(FG if t < T_HEX0 else ACCENT if t < 7.3 else OK, a))
    chip(d, 500, 352, 'min wall 1.47 mm >= 1.2', seg(t, 3.0, 3.5), OK)
    chip(d, 500, 378, 'spec: cumple', seg(t, 6.6, 7.1), OK)
    chip(d, 648, 378, 'log intact', seg(t, 7.6, 8.1), OK)
    text(d, (24, 424), 'digital verification only: never labelled physical', F_SMALL, fade(MUTED, a * 0.9))
    text(d, (776, 424), 'agentcad', F_SMALL, fade(ACCENT, a), 'ra')
    return img.resize((W, H), Image.LANCZOS)

def main(out=None):
    out = Path(out or Path(__file__).with_name('demo.gif'))
    n = int(round(DUR * FPS))
    frames = [render(i / FPS) for i in range(n)]
    pal = frames[0].quantize(colors=48, method=Image.Quantize.MEDIANCUT)
    # one shared palette built from key frames so every frame maps to the same colours
    sheet = Image.new('RGB', (W, H * 4)); [sheet.paste(frames[i], (0, H * j)) for j, i in enumerate((20, 70, 110, 125))]
    pal = sheet.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    durations = [70, 70, 60] * (n // 3)               # 15 fps average (66.67 ms) with centisecond GIF timing
    q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0, optimize=False, disposal=1)
    print(f'{out}  {out.stat().st_size / 1e6:.2f} MB  {n} frames')

if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--frame': render(float(sys.argv[2])).save(sys.argv[3])
    else: main(*sys.argv[1:2])
