#!/usr/bin/env python3
"""Mazzo di fiori 3D in ASCII che ruota nel terminale.

La scena è una nuvola di punti 3D (petali, tulipani, foglie, steli, carta
da regalo, nastro). Ogni frame: rotazione attorno all'asse verticale,
proiezione prospettica, z-buffer e illuminazione -> carattere + colore.

Uso:
    python3 bouquet3d.py                 # gira finché premi Ctrl+C
    python3 bouquet3d.py --speed 0.5     # rotazione più lenta
    python3 bouquet3d.py --text "per te" # cambia la dedica
    python3 bouquet3d.py --tulipani      # solo tulipani bianchi
    python3 bouquet3d.py --no-color
    python3 bouquet3d.py --once          # stampa un solo frame
Consigliato: terminale grande (es. 120x60) e font piccolo.
"""
import argparse
import math
import random
import shutil
import sys
import time
from functools import lru_cache

# ------------------------------------------------------------------ colori
PINK, RED, PURPLE = (255, 120, 185), (225, 35, 55), (165, 90, 230)
YELLOW, ORANGE, WHITE = (255, 210, 40), (255, 135, 30), (250, 250, 250)
GOLD_CENTER, DARK_CENTER = (250, 195, 40), (95, 55, 20)
STEM, LEAF, LEAF_DARK = (70, 160, 60), (110, 210, 90), (40, 130, 50)
PAPER_A, PAPER_B = (255, 255, 255), (255, 50, 150)
RIBBON = (235, 50, 130)
SAGE_A, SAGE_B = (175, 215, 175), (125, 170, 125)   # verde salvia chiaro/scuro
RED_A, RED_B = (235, 40, 50), (170, 15, 35)          # rosso chiaro/scuro
RIBBON_WHITE = (255, 255, 255)

FLOWER_TYPES = [            # (petali, centro, n. petali, dimensione centro)
    (PINK, GOLD_CENTER, 8, 0.28),     # cosmos rosa
    (RED, DARK_CENTER, 8, 0.28),      # rosso
    (PURPLE, GOLD_CENTER, 7, 0.26),   # viola
    (YELLOW, DARK_CENTER, 14, 0.38),  # girasole
    (ORANGE, DARK_CENTER, 9, 0.30),   # arancione
    (WHITE, GOLD_CENTER, 12, 0.25),   # margherita
]
TULIP_COLORS = [RED, PINK, YELLOW]
WHITE_TULIPS = [(255, 255, 255), (255, 252, 235), (250, 250, 255)]
TULIP_BASE = (170, 215, 140)

RAMP = ".,-~:;=!*#%@"
LIGHT = None  # impostata sotto (vettore normalizzato)


# ------------------------------------------------------------------ vettori
def norm(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def add(p, d, k=1.0):
    return (p[0] + d[0] * k, p[1] + d[1] * k, p[2] + d[2] * k)


def basis(axis):
    """Due vettori perpendicolari all'asse (piano del fiore)."""
    helper = (0.0, 1.0, 0.0) if abs(axis[1]) < 0.9 else (1.0, 0.0, 0.0)
    u = norm(cross(helper, axis))
    return u, cross(axis, u)


def mix(c1, c2, t):
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))


LIGHT = norm((-0.45, 0.35, 0.9))


# ------------------------------------------------------------------ scena
class Scene:
    def __init__(self):
        self.pts = []  # (x, y, z, nx, ny, nz, rgb)

    def add(self, p, n, col):
        self.pts.append((p[0], p[1], p[2], n[0], n[1], n[2], col))


def make_flower(sc, pos, axis, R, petal, center, n_petals, cfrac, rnd):
    u, v = basis(axis)
    rot = rnd.uniform(0, math.tau)
    for k in range(n_petals):
        th0 = rot + math.tau * k / n_petals
        for i in range(16):
            t = (i + 0.5) / 16
            r = cfrac + (1 - cfrac) * t
            half = (math.pi / n_petals) * 0.95 * math.sin(math.pi * (0.12 + 0.8 * t)) ** 0.7
            cup = 0.3 * r * r * R
            base = mix(mix(petal, (0, 0, 0), 0.25 * (1 - t)), WHITE, 0.18 * t)
            for j in range(9):
                k = 2 * (j + 0.5) / 9 - 1
                a = th0 + half * k
                col = mix(base, (0, 0, 0), 0.45) if abs(k) > 0.8 else base  # bordo petalo
                dx = (u[0] * math.cos(a) + v[0] * math.sin(a),
                      u[1] * math.cos(a) + v[1] * math.sin(a),
                      u[2] * math.cos(a) + v[2] * math.sin(a))
                p = add(add(pos, dx, r * R), axis, cup)
                n = norm(add(axis, dx, -0.6 * r))
                sc.add(p, n, col)
    # centro a cupola, puntinato
    cR = cfrac * R * 1.05
    for i in range(7):
        th = (i + 0.5) / 7 * (math.pi / 2)
        ring = max(6, int(28 * math.sin(th)))
        for j in range(ring):
            ph = math.tau * j / ring
            d = add(add((0, 0, 0), u, math.cos(ph) * math.sin(th)), v, math.sin(ph) * math.sin(th))
            d = add(d, axis, math.cos(th))
            p = add(add(pos, d, cR), axis, -0.35 * cR)
            col = center if (i + j) % 3 else mix(center, (0, 0, 0), 0.35)
            sc.add(p, norm(d), col)


def make_tulip(sc, pos, axis, R, col, base_tint=None):
    """Tulipano: 3 petali esterni + 3 interni sfalsati, con pieghe più scure."""
    u, v = basis(axis)
    for layer, (rot, scale, tip) in enumerate(((0.0, 1.0, 0.8), (math.pi / 3, 0.86, 0.86))):
        for i in range(26):
            t = (i + 0.5) / 26
            rr = R * scale * (0.12 + 0.5 * math.sin(math.pi * (0.18 + 0.62 * t)))
            h = t * R * 1.5
            shade = mix(mix(col, (0, 0, 0), 0.3), col, min(1, t * 1.6))
            if base_tint and t < 0.3:                      # sfumatura alla base
                shade = mix(base_tint, shade, t / 0.3)
            for j in range(44):
                ph = math.tau * j / 44 + rot
                lobe = abs(math.cos(1.5 * (ph - rot)))
                if t > tip + (1 - tip) * lobe:             # punte dei petali
                    continue
                c = mix(shade, (0, 0, 0), 0.3) if lobe < 0.18 and layer == 0 else shade  # piega
                d = add(add((0, 0, 0), u, math.cos(ph)), v, math.sin(ph))
                p = add(add(pos, d, rr), axis, h)
                sc.add(p, norm(add(d, axis, -0.3)), c)


def make_stem(sc, a, b, col, steps=50):
    for i in range(steps):
        t = i / (steps - 1)
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        for ox, oz in ((0.012, 0), (-0.012, 0), (0, 0.012), (0, -0.012)):
            sc.add((p[0] + ox, p[1], p[2] + oz), norm((ox, 0, oz)), col)


def make_leaf(sc, base, theta, length, rnd, up=0.45, width=0.11, droop=0.35):
    d = norm((math.cos(theta) * 0.8, up, math.sin(theta) * 0.8))
    s = (-math.sin(theta), 0.0, math.cos(theta))
    for i in range(30):
        t = (i + 0.5) / 30
        w = width * math.sin(math.pi * t) ** 0.8
        spine = add(base, d, t * length)
        spine = add(spine, (0, 1, 0), -droop * t * t * length)  # si piega in giù
        for j in range(9):
            k = 2 * (j + 0.5) / 9 - 1
            p = add(spine, s, k * w)
            p = add(p, (0, 1, 0), 0.03 * (1 - k * k))          # piega centrale
            n = norm(cross(d, s))
            col = LEAF_DARK if abs(k) < 0.15 else mix(LEAF, LEAF_DARK, abs(k) * 0.4)
            sc.add(p, n, col)


def make_wrap(sc, neck_y, top_y, paper=(PAPER_A, PAPER_B), ribbon=RIBBON):
    """Cono di carta a righe + nastro con fiocco."""
    for i in range(55):
        t = (i + 0.5) / 55
        y = neck_y + (top_y - neck_y) * t
        r = 0.1 + 0.45 * t
        for j in range(150):
            ph = math.tau * j / 150
            if t > 0.9 + 0.1 * math.cos(5 * ph):                # bordo ondulato
                continue
            col = paper[0] if int(ph / math.tau * 18) % 2 else paper[1]
            x, z = r * math.cos(ph), r * math.sin(ph)
            sc.add((x, y, z), norm((math.cos(ph), -0.45, math.sin(ph))), col)
    # gambi sotto la carta
    for i in range(30):
        y = neck_y - 0.5 * i / 29
        for j in range(18):
            ph = math.tau * j / 18
            sc.add((0.07 * math.cos(ph), y, 0.07 * math.sin(ph)), (math.cos(ph), 0, math.sin(ph)), STEM)
    # nastro
    for i in range(6):
        y = neck_y + 0.01 + 0.012 * i
        for j in range(60):
            ph = math.tau * j / 60
            sc.add((0.12 * math.cos(ph), y, 0.12 * math.sin(ph)), (math.cos(ph), 0, math.sin(ph)), ribbon)
    # fiocco (due anelli) e codine, sul davanti (z+)
    cy = neck_y + 0.04
    for side in (-1, 1):
        for j in range(60):
            ph = math.tau * j / 60
            x = side * (0.08 + 0.07 * (1 + math.cos(ph)) / 2 * 1.4)
            y = cy + 0.045 * math.sin(ph)
            sc.add((x, y, 0.14), (0, 0, 1), ribbon)
        for i in range(25):
            t = i / 24
            sc.add((side * (0.02 + 0.08 * t), cy - 0.02 - 0.22 * t, 0.14), (0, 0, 1), ribbon)


def build_tulip_scene(seed=5):
    """Mazzo di soli tulipani bianchi con foglie lunghe."""
    rnd = random.Random(seed)
    sc = Scene()
    neck = (0.0, -0.55, 0.0)
    C, D, N = (0.0, -0.16, 0.0), 0.78, 8
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(N):
        el = math.radians(80 - 42 * math.sqrt(i / (N - 1)))
        az = i * golden + rnd.uniform(-0.15, 0.15)
        d = (math.cos(el) * math.cos(az), math.sin(el), math.cos(el) * math.sin(az))
        pos = add(C, d, D * rnd.uniform(0.9, 1.06))
        axis = norm(add(d, (0, 1, 0), 0.5))             # i tulipani guardano più in su
        make_stem(sc, pos, neck, STEM)
        make_tulip(sc, add(pos, axis, -0.05), axis, rnd.uniform(0.16, 0.19),
                   WHITE_TULIPS[i % len(WHITE_TULIPS)], TULIP_BASE)
    for k in range(7):
        th = k * math.tau / 7 + 0.2
        make_leaf(sc, (0.16 * math.cos(th), 0.0, 0.16 * math.sin(th)), th,
                  rnd.uniform(0.5, 0.65), rnd, up=1.1, width=0.08, droop=0.6)
    make_wrap(sc, neck[1], 0.12, paper=(RED_A, RED_B), ribbon=RIBBON_WHITE)
    return sc.pts


def build_scene(seed=21):
    rnd = random.Random(seed)
    sc = Scene()
    neck = (0.0, -0.55, 0.0)
    C, D, N = (0.0, 0.05, 0.0), 0.78, 9
    golden = math.pi * (3 - math.sqrt(5))
    tulip_slots = {2, 6}
    fi = 0
    for i in range(N):
        el = math.radians(82 - 60 * math.sqrt(i / (N - 1)))
        az = i * golden
        d = (math.cos(el) * math.cos(az), math.sin(el), math.cos(el) * math.sin(az))
        pos = add(C, d, D * rnd.uniform(0.92, 1.05))
        axis = norm(d)
        make_stem(sc, add(pos, axis, -0.03), neck, STEM)
        if i in tulip_slots:
            make_tulip(sc, add(pos, axis, -0.12), axis, 0.2, TULIP_COLORS[i % len(TULIP_COLORS)])
        else:
            petal, center, n, cf = FLOWER_TYPES[fi % len(FLOWER_TYPES)]
            fi += 1
            R = 0.27 if n >= 12 else 0.22
            make_flower(sc, pos, axis, R, petal, center, n, cf, rnd)
    for k in range(6):
        th = k * math.tau / 6 + 0.4
        make_leaf(sc, (0.2 * math.cos(th), 0.02, 0.2 * math.sin(th)), th, 0.55, rnd)
    make_wrap(sc, neck[1], 0.12)
    return sc.pts


# ------------------------------------------------------------------ render
@lru_cache(maxsize=None)
def ansi256(r, g, b):
    q = lambda c: max(0, min(5, round(c / 255 * 5)))
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


class Renderer:
    def __init__(self, pts, W, H, text, color):
        self.pts, self.W, self.H, self.text, self.color = pts, W, H, text, color
        self.scale = (H - 3) / 2.05          # unità scena -> righe
        self.cx, self.cy = W / 2, 1 + 1.0 * self.scale
        rnd = random.Random(7)
        self.sparkles = [(rnd.randrange(W), rnd.randrange(H - 3), rnd.uniform(0, math.tau),
                          rnd.uniform(1.5, 4), rnd.choice([(255, 255, 255), (255, 230, 120), (255, 160, 210)]))
                         for _ in range(W * H // 90)]

    def frame(self, angle, t):
        W, H = self.W, self.H
        ca, sa = math.cos(angle), math.sin(angle)
        tilt = 0.35
        ct, st = math.cos(tilt), math.sin(tilt)
        lx, ly, lz = LIGHT
        dist, sx_k, sy_k = 4.0, self.scale * 2.0, self.scale
        cx, cy = self.cx, self.cy
        zbuf = [-1e9] * (W * H)
        cell = [None] * (W * H)
        for x, y, z, nx, ny, nz, col in self.pts:
            x1 = x * ca + z * sa
            z1 = -x * sa + z * ca
            y2 = y * ct - z1 * st
            z2 = y * st + z1 * ct
            f = dist / (dist - z2)
            px = int(cx + x1 * f * sx_k)
            py = int(cy - y2 * f * sy_k)
            if 0 <= px < W and 0 <= py < H:
                idx = py * W + px
                if z2 > zbuf[idx]:
                    zbuf[idx] = z2
                    nx1 = nx * ca + nz * sa
                    nz1 = -nx * sa + nz * ca
                    ny2 = ny * ct - nz1 * st
                    nz2 = ny * st + nz1 * ct
                    cell[idx] = (abs(nx1 * lx + ny2 * ly + nz2 * lz), col)

        # contorni: vicino pieno ma molto più lontano -> punto più scuro
        # (i vicini vuoti si ignorano: sono buchi della nuvola di punti)
        edge = [False] * (W * H)
        gap = 0.09
        for idx in range(W * H):
            if cell[idx] is None:
                continue
            z = zbuf[idx] - gap
            x = idx % W
            for n in ((idx - 1) if x > 0 else -1, (idx + 1) if x < W - 1 else -1,
                      idx - W, idx + W if idx < W * (H - 1) else -1):
                if n >= 0 and -1e8 < zbuf[n] < z:
                    edge[idx] = True
                    break

        # stelline che brillano
        for sx, sy, ph, sp, scol in self.sparkles:
            idx = sy * W + sx
            if cell[idx] is None:
                v = math.sin(t * sp + ph)
                if v > 0.55:
                    cell[idx] = ("*" if v > 0.9 else "+" if v > 0.75 else ".", scol)

        lines = []
        for row in range(H):
            out, cur = [], None
            for col_i, c in enumerate(cell[row * W:(row + 1) * W]):
                if c is None:
                    ch, code = " ", None
                elif isinstance(c[0], str):
                    ch, code = c[0], ansi256(*c[1])
                else:
                    light = 0.2 + 0.8 * c[0]
                    ch = RAMP[min(len(RAMP) - 1, int(light * len(RAMP)))]
                    r, g, b = c[1]
                    k = 0.8 + 0.2 * light
                    if edge[row * W + col_i]:
                        k, ch = 0.55, RAMP[max(0, RAMP.index(ch) - 3)]
                    code = ansi256(int(r * k), int(g * k), int(b * k))
                if self.color and code != cur and ch != " ":
                    out.append(f"\033[38;5;{code}m")
                    cur = code
                out.append(ch)
            lines.append("".join(out))
        # dedica
        txt = self.text
        pad = " " * max(0, (W - len(txt)) // 2)
        lines.append(pad + (f"\033[1;38;5;205m{txt}\033[0m" if self.color else txt))
        return "\n".join(lines) + ("\033[0m" if self.color else "")


def main():
    ap = argparse.ArgumentParser(description="Mazzo di fiori 3D in ASCII")
    ap.add_argument("--speed", type=float, default=1.0, help="velocità di rotazione")
    ap.add_argument("--fps", type=float, default=20)
    ap.add_argument("--text", default="for you ♥")
    ap.add_argument("--tulipani", action="store_true", help="mazzo di soli tulipani bianchi")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--once", action="store_true", help="stampa un frame ed esce")
    ap.add_argument("--angle", type=float, default=0.6, help="angolo per --once (radianti)")
    args = ap.parse_args()

    cols, rows = shutil.get_terminal_size((120, 60))
    W, H = cols, max(20, rows - 2)
    color = not args.no_color and (sys.stdout.isatty() or args.once is False)
    r = Renderer(build_tulip_scene() if args.tulipani else build_scene(), W, H, args.text, color and not args.no_color)

    if args.once:
        print(r.frame(args.angle, 0.0))
        return

    try:
        sys.stdout.write("\033[?25l\033[2J")
        t0 = time.time()
        while True:
            t = time.time() - t0
            sys.stdout.write("\033[H" + r.frame(t * 0.8 * args.speed, t))
            sys.stdout.flush()
            time.sleep(max(0, 1 / args.fps - (time.time() - t0 - t)))
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[0m\033[?25h\n")


if __name__ == "__main__":
    main()
