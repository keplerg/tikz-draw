#!/usr/bin/env python3
"""
tikz2view.py - Convert TikZ pictures to tikz-draw project (JSON) files.

Reads every tikzpicture in a .tex file and writes a project that tikz-draw.html
can open. It understands everything the editor exports, plus common hand-written
TikZ:

  points      \\coordinate, \\fill (A) circle (2pt), coordinate labels,
              Cartesian, polar (30:2), relative +(..)/++(..) and simple calc
  lines       (A) -- (B), multi-point paths, -- cycle, -| and |-,
              arrows (arrows.meta tips, scale=, >=Tip), embedded nodes
  curves      .. controls (C1) and (C2) .., closed Bezier curves
  arcs        arc[start angle=, end angle= / delta angle=, radius=], arc (s:e:r)
  shapes      circle, ellipse (with rotate around), rectangle (rotated), grid
  fills       fill=, fill opacity=, pattern=, pattern color=, \\filldraw,
              \\fill regions (polygons and areas bounded by curves)
  text        \\node labels (position, distance, font size, colour, rotation)
  images      \\node {\\includegraphics[...]{file}} (embedded when the file exists)
  colours     \\definecolor (RGB, rgb, HTML, gray), \\colorlet, xcolor mixes red!30
  macros      \\def, \\newcommand, \\pgfmathsetmacro (simple values)

Anything it cannot represent is reported as a warning instead of being dropped
silently.

Usage:
    python tikz2view.py input.tex
    python tikz2view.py input.tex -o output.json
    cat input.tex | python tikz2view.py -o output.json
"""

import argparse
import ast
import base64
import json
import math
import operator
import re
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Editor vocabulary (kept in step with tikz-draw.html)
# ---------------------------------------------------------------------------

EDITOR_COLORS = {
    'black': '#000000', 'white': '#FFFFFF', 'red': '#FF0000', 'green': '#00FF00',
    'blue': '#0000FF', 'cyan': '#00FFFF', 'magenta': '#FF00FF', 'yellow': '#FFFF00',
    'orange': '#FF8000', 'purple': '#800080', 'brown': '#804000', 'gray': '#808080',
    'lightgray': '#C0C0C0', 'darkgray': '#404040',
}
# Other xcolor names; imported as custom colours.
XCOLOR_EXTRA = {
    'pink': '#FFBFBF', 'lime': '#BFFF00', 'olive': '#808000', 'teal': '#008080',
    'violet': '#800080',
}
LINE_STYLES = {
    'solid', 'dashed', 'dotted', 'dashdotted', 'dashdotdotted', 'loosely dashed',
    'densely dashed', 'loosely dotted', 'densely dotted', 'loosely dashdotted',
    'densely dashdotted',
}
LINE_STYLE_ALIASES = {
    'loosely dashdotdotted': 'loosely dashdotted', 'densely dashdotdotted': 'densely dashdotted',
}
THICKNESS_PT = {
    'ultra thin': 0.1, 'very thin': 0.2, 'thin': 0.4, 'thick': 0.8,
    'very thick': 1.2, 'ultra thick': 1.6,
}
PATTERNS = {
    'horizontal lines', 'vertical lines', 'north east lines', 'north west lines', 'grid',
    'crosshatch', 'dots', 'crosshatch dots', 'fivepointed stars', 'sixpointed stars',
    'bricks', 'checkerboard',
}
POSITIONS = ['above left', 'above right', 'below left', 'below right', 'above', 'below', 'left', 'right']
ANCHOR_POSITIONS = {
    'south': 'above', 'north': 'below', 'east': 'left', 'west': 'right',
    'south west': 'above right', 'south east': 'above left',
    'north west': 'below right', 'north east': 'below left',
}
FONT_SIZES = {
    'tiny': 'tiny', 'scriptsize': 'scriptsize', 'footnotesize': 'footnotesize', 'small': 'small',
    'normalsize': 'normal', 'large': 'large', 'Large': 'Large', 'LARGE': 'LARGE',
    'huge': 'huge', 'Huge': 'Huge',
}
ARROW_TIPS = {
    'Stealth', 'Latex', 'Triangle', 'Kite', 'Diamond', 'Turned Square', 'Square', 'Rectangle',
    'Circle', 'Ellipse', 'Straight Barb', 'Arc Barb', 'Hooks', 'Tee Barb', 'Bar', 'Bracket',
    'Parenthesis', 'To', 'Computer Modern Rightarrow', 'Classical TikZ Rightarrow', 'Implies',
    'Butt Cap', 'Round Cap', 'Triangle Cap', 'Fast Round', 'Fast Triangle', 'Rays',
}
ARROW_ALIASES = {'latex': 'latex', 'LaTeX': 'LaTeX', 'stealth': 'Stealth', 'to': 'To',
                 'triangle 45': 'Triangle', 'triangle 60': 'Triangle', '|': 'Bar'}
NODE_POS = {'midway': 0.5, 'at start': 0.0, 'at end': 1.0, 'near start': 0.25, 'near end': 0.75,
            'very near start': 0.125, 'very near end': 0.875}
UNIT_CM = {'cm': 1.0, 'mm': 0.1, 'pt': 1 / 28.45274, 'bp': 2.54 / 72, 'in': 2.54, 'em': 0.35, 'ex': 0.15}
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml'}

TOL = 1e-4  # Geometric tolerance in cm; exports carry 6 decimals.

# ---------------------------------------------------------------------------
# Safe arithmetic (TikZ math: trig functions take degrees)
# ---------------------------------------------------------------------------

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_FUNCS = {
    'sin': lambda d: math.sin(math.radians(d)), 'cos': lambda d: math.cos(math.radians(d)),
    'tan': lambda d: math.tan(math.radians(d)), 'asin': lambda v: math.degrees(math.asin(v)),
    'acos': lambda v: math.degrees(math.acos(v)), 'atan': lambda v: math.degrees(math.atan(v)),
    'atan2': lambda y, x: math.degrees(math.atan2(y, x)), 'sqrt': math.sqrt, 'abs': abs,
    'exp': math.exp, 'ln': math.log, 'log10': math.log10, 'min': min, 'max': max,
    'round': round, 'floor': math.floor, 'ceil': math.ceil, 'int': int,
    'veclen': lambda x, y: math.hypot(x, y), 'deg': math.degrees, 'rad': math.radians,
}
_CONSTS = {'pi': math.pi, 'e': math.e}


def eval_number(text):
    """Evaluate a TikZ arithmetic expression without eval(); raise ValueError if not numeric."""
    text = text.strip().replace('^', '**')
    if not text:
        raise ValueError('empty expression')
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError as err:
        raise ValueError(f'cannot evaluate {text!r}') from err

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return float(_FUNCS[node.func.id](*[walk(arg) for arg in node.args]))
        raise ValueError(f'unsupported expression {text!r}')

    return walk(tree)


def eval_length(text, default_unit='cm'):
    """A length in cm. Returns (value_cm, unit_used)."""
    text = text.strip()
    match = re.fullmatch(r'(.*?)\s*(cm|mm|pt|bp|in|em|ex)', text)
    if match and match.group(1):
        return eval_number(match.group(1)) * UNIT_CM[match.group(2)], match.group(2)
    return eval_number(text) * UNIT_CM[default_unit], default_unit


def fmt_num(value):
    """Round away float noise (e.g. 0.30000000000000004)."""
    rounded = round(value, 9)
    return 0.0 if rounded == 0 else rounded


# ---------------------------------------------------------------------------
# Text scanning helpers
# ---------------------------------------------------------------------------

PAIRS = {'{': '}', '[': ']', '(': ')'}


def read_group(text, i):
    """text[i] is an opening bracket; return (inner, index after the closing bracket)."""
    opener = text[i]
    closer = PAIRS[opener]
    depth = 0
    j = i
    while j < len(text):
        ch = text[j]
        if ch == '\\':
            j += 2
            continue
        if ch == '{' and opener != '{':
            _, j = read_group(text, j)
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise ValueError(f'unbalanced {opener!r}')


def split_top(text, sep=','):
    """Split on `sep` outside braces, brackets and parentheses."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch in '{[(':
            depth += 1
        elif ch in '}])':
            depth -= 1
        elif depth == 0 and text.startswith(sep, i):
            parts.append(text[start:i])
            start = i + len(sep)
            i = start
            continue
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def strip_comments(text):
    lines = []
    for line in text.split('\n'):
        match = re.search(r'(?<!\\)%', line)
        lines.append(line[:match.start()] if match else line)
    return '\n'.join(lines)


def split_statements(text):
    """Split a picture body on top-level semicolons."""
    statements, depth, start, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch in '{[(':
            depth += 1
        elif ch in '}])':
            depth = max(0, depth - 1)
        elif ch == ';' and depth == 0:
            statements.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


def expand_macros(text, macros):
    if not macros:
        return text
    names = sorted(macros, key=len, reverse=True)
    pattern = re.compile(r'\\(' + '|'.join(re.escape(n) for n in names) + r')(?![A-Za-z])')
    for _ in range(10):
        new = pattern.sub(lambda m: macros[m.group(1)], text)
        if new == text:
            break
        text = new
    return text


def remove_macro_definitions(text):
    for match in list(re.finditer(r'\\(?:def|newcommand\*?|renewcommand\*?|pgfmathsetmacro)\s*\{?\\[A-Za-z]+\}?\s*(?=\{)',
                                  text))[::-1]:
        try:
            _, end = read_group(text, match.end())
            text = text[:match.start()] + ' ' + text[end:]
        except ValueError:
            pass
    return text


def collect_macros(text):
    """\\def, \\newcommand and \\pgfmathsetmacro with simple (argument-free) bodies."""
    macros = {}
    for match in re.finditer(r'\\(?:def|newcommand\*?|renewcommand\*?)\s*\{?\\([A-Za-z]+)\}?\s*(?=\{)', text):
        try:
            body, _ = read_group(text, match.end())
        except ValueError:
            continue
        macros[match.group(1)] = body.strip()
    for match in re.finditer(r'\\pgfmathsetmacro\s*\{?\\([A-Za-z]+)\}?\s*(?=\{)', text):
        try:
            body, _ = read_group(text, match.end())
            macros[match.group(1)] = repr(eval_number(expand_macros(body, macros)))
        except ValueError:
            continue
    return macros


# ---------------------------------------------------------------------------
# Geometry that mirrors the editor's fill primitives (fillPrimitivesFor)
# ---------------------------------------------------------------------------

def fill_arc_sweep(start_deg, end_deg):
    delta = end_deg - start_deg
    if delta >= 360 or (delta < 0 and math.fmod(delta, 360) == 0):
        return 2 * math.pi
    return math.fmod(math.fmod(delta, 360) + 360, 360) * math.pi / 180


def prim_point(p, t):
    if p['kind'] == 'line':
        return (p['p0'][0] + t * (p['p1'][0] - p['p0'][0]), p['p0'][1] + t * (p['p1'][1] - p['p0'][1]))
    if p['kind'] == 'cubic':
        s = 1 - t
        a, b, c, d = s * s * s, 3 * s * s * t, 3 * s * t * t, t * t * t
        return (a * p['p0'][0] + b * p['p1'][0] + c * p['p2'][0] + d * p['p3'][0],
                a * p['p0'][1] + b * p['p1'][1] + c * p['p2'][1] + d * p['p3'][1])
    angle = p['start'] + t * p['sweep']
    x, y = p['rx'] * math.cos(angle), p['ry'] * math.sin(angle)
    cos, sin = math.cos(p['rotation']), math.sin(p['rotation'])
    return (p['cx'] + x * cos - y * sin, p['cy'] + x * sin + y * cos)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def prim_param(p, point):
    """Parameter of the point on primitive p nearest to `point` (and its distance)."""
    if p['kind'] == 'line':
        dx, dy = p['p1'][0] - p['p0'][0], p['p1'][1] - p['p0'][1]
        length2 = dx * dx + dy * dy
        t = 0.0 if not length2 else ((point[0] - p['p0'][0]) * dx + (point[1] - p['p0'][1]) * dy) / length2
        t = min(1.0, max(0.0, t))
        return t, dist(prim_point(p, t), point)
    if p['kind'] == 'arc':
        cos, sin = math.cos(-p['rotation']), math.sin(-p['rotation'])
        x, y = point[0] - p['cx'], point[1] - p['cy']
        lx, ly = x * cos - y * sin, x * sin + y * cos
        angle = math.atan2(ly / p['ry'], lx / p['rx'])
        t = math.fmod(math.fmod(angle - p['start'], 2 * math.pi) + 2 * math.pi, 2 * math.pi) / p['sweep']
        if t > 1:
            # Outside a partial arc: snap to the nearer end.
            ends = [(0.0, dist(prim_point(p, 0.0), point)), (1.0, dist(prim_point(p, 1.0), point))]
            return min(ends, key=lambda e: e[1])
        return t, dist(prim_point(p, t), point)
    # Cubic: coarse search, then refine by ternary search on the bracket.
    best = min((i / 200 for i in range(201)), key=lambda t: dist(prim_point(p, t), point))
    lo, hi = max(0.0, best - 0.005), min(1.0, best + 0.005)
    for _ in range(60):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if dist(prim_point(p, m1), point) < dist(prim_point(p, m2), point):
            hi = m2
        else:
            lo = m1
    t = (lo + hi) / 2
    return t, dist(prim_point(p, t), point)


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

class Point:
    __slots__ = ('x', 'y', 'name')

    def __init__(self, x, y, name=None):
        self.x, self.y, self.name = x, y, name

    @property
    def xy(self):
        return (self.x, self.y)


class TikZConverter:
    def __init__(self, base_dir=Path('.'), macros=None, preamble_colors=None):
        self.base_dir = base_dir
        self.macros = macros or {}
        self.objects = []
        self.coords = {}           # name -> coordinate dict
        self.custom_colors = dict(preamble_colors or {})
        self.warnings = []
        self.id_counter = 0
        self.reserved = set()
        self.scale = 1.0
        self.transform = None      # (degrees, (ox, oy)) while reading a rotated statement
        self.pending_regions = []

    # -- bookkeeping ---------------------------------------------------------

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def new_id(self, prefix):
        self.id_counter += 1
        return f'{prefix}_{self.id_counter}'

    def add(self, obj):
        obj.setdefault('locked', False)
        obj.setdefault('expanded', False)
        self.objects.append(obj)
        return obj

    def generate_coord_name(self):
        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        index = 1
        while True:
            name, n = '', index
            while n > 0:
                n, r = divmod(n - 1, 26)
                name = letters[r] + name
            if name not in self.coords and name not in self.reserved:
                return name
            index += 1

    def define_coord(self, name, x, y):
        if name in self.coords:
            self.coords[name]['x'], self.coords[name]['y'] = fmt_num(x), fmt_num(y)
            return self.coords[name]
        coord = self.add({
            'type': 'TikZCoordinate', 'id': self.new_id('coord'), 'x': fmt_num(x), 'y': fmt_num(y),
            'name': name, 'showPoint': False, 'pointSize': 2, 'color': 'black', 'label': '',
            'anchor': 'above right',
        })
        self.coords[name] = coord
        return coord

    def coord_for(self, point):
        """Name of a coordinate at this point, reusing one already there."""
        if point.name and point.name in self.coords:
            return point.name
        for name, coord in self.coords.items():
            if abs(coord['x'] - point.x) <= TOL and abs(coord['y'] - point.y) <= TOL:
                return name
        name = self.generate_coord_name()
        self.define_coord(name, point.x, point.y)
        return name

    # -- colours -------------------------------------------------------------

    def color_hex(self, name):
        name = name.strip()
        if name in self.custom_colors:
            return self.custom_colors[name]
        if name in EDITOR_COLORS:
            return EDITOR_COLORS[name]
        if name in XCOLOR_EXTRA:
            return XCOLOR_EXTRA[name]
        if '!' in name:
            return self.mix_hex(name)
        return None

    def mix_hex(self, expr):
        """xcolor mix: c1!p!c2!q!c3 ... (missing last colour means white)."""
        parts = [p.strip() for p in expr.split('!')]
        if len(parts) % 2 == 0:
            parts.append('white')
        rgb = self.hex_rgb(self.color_hex(parts[0]) if '!' not in parts[0] else None)
        if rgb is None:
            return None
        for i in range(1, len(parts), 2):
            try:
                pct = float(parts[i]) / 100
            except ValueError:
                return None
            other = self.hex_rgb(self.color_hex(parts[i + 1]))
            if other is None:
                return None
            rgb = tuple(pct * a + (1 - pct) * b for a, b in zip(rgb, other))
        # Round halves up like xcolor (Python's round() would turn 178.5 into 178).
        return '#{:02x}{:02x}{:02x}'.format(*(int(v + 0.5) for v in rgb))

    @staticmethod
    def hex_rgb(hex_color):
        if not hex_color:
            return None
        h = hex_color.lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def color(self, name):
        """Editor colour name for a TikZ colour, registering custom colours as needed."""
        name = name.strip()
        if name == 'none':
            return 'none'
        if name in EDITOR_COLORS or name in self.custom_colors:
            return name
        hex_color = self.color_hex(name)
        if hex_color is None:
            return None
        safe = re.sub(r'[^A-Za-z0-9]', '', name) or 'custom'
        self.custom_colors[safe] = hex_color
        return safe

    def define_color(self, name, model, spec):
        try:
            model = model.strip()
            if model == 'RGB':
                r, g, b = (int(eval_number(v)) for v in spec.split(','))
            elif model == 'rgb':
                r, g, b = (round(eval_number(v) * 255) for v in spec.split(','))
            elif model == 'HTML':
                r, g, b = self.hex_rgb(spec.strip())
            elif model == 'gray':
                r = g = b = round(eval_number(spec) * 255)
            elif model == 'cmyk':
                c, m, y, k = (eval_number(v) for v in spec.split(','))
                r, g, b = (round(255 * (1 - v) * (1 - k)) for v in (c, m, y))
            else:
                self.warn(f'Colour model {model!r} for {name!r} is not supported')
                return
            self.custom_colors[name.strip()] = '#{:02x}{:02x}{:02x}'.format(r, g, b)
        except (ValueError, TypeError):
            self.warn(f'Could not read colour {name!r}')

    # -- options -------------------------------------------------------------

    def parse_options(self, texts):
        """Merge one or more [..] option strings into a style dict."""
        style = {'flags': set()}
        for text in texts:
            for part in split_top(text):
                self.apply_option(style, part)
        return style

    def apply_option(self, style, part):
        # Arrow specs may contain '=' inside their tips, e.g. -{Latex[scale=1.5]}.
        if '-' in part and self.parse_arrow(part) is not None:
            style['arrow'] = part
            return
        key, _, value = part.partition('=')
        key, value = key.strip(), value.strip()
        has_value = '=' in part
        if not has_value:
            if part in LINE_STYLES or part in LINE_STYLE_ALIASES:
                style['lineStyle'] = LINE_STYLE_ALIASES.get(part, part)
            elif part in THICKNESS_PT:
                style['thickness'] = part
            elif part == 'semithick':
                style['thickness'] = 'thick'
            elif part in POSITIONS:
                style['position'] = part
            elif part in NODE_POS:
                style['pos'] = NODE_POS[part]
            elif part in ('draw', 'fill', 'sloped', 'even odd rule', 'nonzero rule', 'circle',
                          'midway', 'auto', 'swap', "'", 'transform shape', 'inner sep'):
                style['flags'].add(part)
            elif part.startswith('\\') and part[1:] in FONT_SIZES:
                style['fontSize'] = FONT_SIZES[part[1:]]
            elif self.parse_arrow(part) is not None:
                style['arrow'] = part
            elif self.color(part) is not None:
                style['color'] = self.color(part)
            else:
                self.warn(f'Option {part!r} is not supported and was ignored')
            return
        if key in ('color', 'draw'):
            color = self.color(value)
            if color:
                style['color'] = color
                style['flags'].add('draw')
        elif key == 'fill':
            color = self.color(value)
            if color:
                style['fill'] = color
        elif key == 'text':
            color = self.color(value)
            if color:
                style['text'] = color
        elif key == 'pattern':
            if value in PATTERNS:
                style['pattern'] = value
            else:
                self.warn(f'Pattern {value!r} is not supported')
        elif key == 'pattern color':
            color = self.color(value)
            if color:
                style['patternColor'] = color
        elif key in ('fill opacity', 'opacity'):
            try:
                style['fillOpacity' if key == 'fill opacity' else 'opacity'] = eval_number(value)
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == 'line width':
            try:
                width_pt = eval_length(value, 'pt')[0] / UNIT_CM['pt']
                style['thickness'] = min(THICKNESS_PT, key=lambda k: abs(THICKNESS_PT[k] - width_pt))
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == 'step':
            try:
                style['step'] = eval_length(value)[0]
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == 'rotate around':
            match = re.fullmatch(r'\{?\s*([^:]+):\s*\((.*)\)\s*\}?', value)
            center = self.resolve_point(match.group(2), None) if match else None
            try:
                if not match or center is None:
                    raise ValueError(part)
                style['rotate'] = eval_number(match.group(1))
                style['rotateAbout'] = center.xy
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == 'rotate':
            try:
                style['rotate'] = eval_number(value.replace('--', ''))
                if value.startswith('--'):
                    style['rotate'] = -style['rotate']
                style['rotateAbout'] = (0.0, 0.0)
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == 'font':
            match = re.search(r'\\(' + '|'.join(FONT_SIZES) + r')\b', value)
            if match:
                style['fontSize'] = FONT_SIZES[match.group(1)]
        elif key in POSITIONS:
            style['position'] = key
            try:
                style['distance'] = eval_length(value, 'pt')[0] / UNIT_CM['pt']
            except ValueError:
                pass
        elif key == 'anchor':
            if value in ANCHOR_POSITIONS:
                style['position'] = ANCHOR_POSITIONS[value]
        elif key == 'pos':
            try:
                style['pos'] = eval_number(value)
            except ValueError:
                self.warn(f'Could not read {part!r}')
        elif key == '>':
            tip = self.tip_name(value.strip('{}'))
            if tip:
                style['defaultTip'] = tip[0]
        elif key == 'label':
            style['label'] = value
        elif key in ('scale', 'xscale', 'yscale', 'shift', 'xshift', 'yshift'):
            self.warn(f'Transformation {part!r} on a path is not supported and was ignored')
        elif key in ('radius', 'x radius', 'y radius', 'start angle', 'end angle', 'delta angle',
                     'inner sep', 'outer sep', 'minimum size', 'out', 'in', 'looseness'):
            style[key] = value
        else:
            self.warn(f'Option {part!r} is not supported and was ignored')

    def tip_name(self, text):
        """(editor tip name, scale) for one arrow tip, or None."""
        text = text.strip()
        if text.startswith('{') and text.endswith('}'):
            text = text[1:-1].strip()
        scale = None
        match = re.fullmatch(r'([^\[\]]+?)\s*(?:\[(.*)\])?', text)
        if not match:
            return None
        name, opts = match.group(1).strip(), match.group(2)
        if opts:
            for opt in split_top(opts):
                key, _, value = opt.partition('=')
                if key.strip() == 'scale':
                    try:
                        scale = eval_number(value)
                    except ValueError:
                        pass
                elif key.strip() not in ('', 'open', 'round', 'sep'):
                    self.warn(f'Arrow tip option {opt!r} is not supported')
                if key.strip() == 'open':
                    self.warn('Open arrow tips are drawn filled')
        if name in ('<', '>'):
            return name, scale
        if name in ARROW_TIPS:
            return name, scale
        if name in ARROW_ALIASES:
            return ARROW_ALIASES[name], scale
        return None

    def parse_arrow(self, text):
        """Split an arrow spec like '->' or '{Stealth[scale=2]}-Latex' into (start, end, scale)."""
        if text in ('-', ''):
            return None
        depth, cut = 0, None
        for i, ch in enumerate(text):
            if ch in '{[':
                depth += 1
            elif ch in '}]':
                depth -= 1
            elif ch == '-' and depth == 0:
                if cut is not None:
                    return None
                cut = i
        if cut is None:
            return None
        start_text, end_text = text[:cut].strip(), text[cut + 1:].strip()
        start = self.tip_name(start_text) if start_text else ('', None)
        end = self.tip_name(end_text) if end_text else ('', None)
        if start is None or end is None or (not start[0] and not end[0]):
            return None
        if start[0] == '>' or end[0] == '<':
            return None
        scale = start[1] or end[1]
        return start[0], end[0], scale

    def arrow_fields(self, style, reverse=False):
        if 'arrow' not in style:
            return 'none', 1.0
        start, end, scale = self.parse_arrow(style['arrow'])
        default = style.get('defaultTip')
        if default:
            start = default if start == '<' else start
            end = default if end == '>' else end
        if reverse:
            # The editor draws arcs counter-clockwise, so a clockwise arc swaps its ends.
            flip = {'>': '<', '<': '>'}
            start, end = flip.get(end, end), flip.get(start, start)
        return f'{start}-{end}', fmt_num(scale) if scale else 1.0

    # -- coordinates ---------------------------------------------------------

    def transformed(self, x, y, vector=False):
        """Apply the current statement's rotation to a numeric point (or offset vector)."""
        if not self.transform:
            return x, y
        angle, (ox, oy) = self.transform
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        if vector:
            return x * c - y * s, x * s + y * c
        dx, dy = x - ox, y - oy
        return ox + dx * c - dy * s, oy + dx * s + dy * c

    def resolve_point(self, spec, current, vector=False):
        """A Point for a coordinate spec (inside parentheses), or None.

        Named coordinates are absolute; numeric ones follow the statement's rotation."""
        point = self.resolve_raw_point(spec, current)
        if point is None or point.name:
            return point
        return Point(*self.transformed(point.x, point.y, vector))

    def resolve_raw_point(self, spec, current):
        spec = spec.strip()
        if spec.startswith('$') and spec.endswith('$'):
            return self.resolve_calc(spec[1:-1], current)
        # Perpendicular coordinates: (A |- B) is (A.x, B.y); (A -| B) is (B.x, A.y).
        perpendicular = re.fullmatch(r'(.+?)\s*(\|-|-\|)\s*(.+)', spec)
        if perpendicular and ',' not in spec:
            a = self.resolve_point(perpendicular.group(1).strip('() '), current)
            b = self.resolve_point(perpendicular.group(3).strip('() '), current)
            if a is None or b is None:
                return None
            return Point(a.x, b.y) if perpendicular.group(2) == '|-' else Point(b.x, a.y)
        named = re.fullmatch(r"([A-Za-z_][\w']*)(?:\.[\w ]+)?", spec)
        if named:
            name = named.group(1)
            if name in self.coords:
                c = self.coords[name]
                return Point(c['x'], c['y'], name)
            self.warn(f'Unknown coordinate ({name})')
            return None
        try:
            if ':' in spec and ',' not in spec:
                angle_text, radius_text = spec.split(':', 1)
                angle = eval_number(angle_text)
                radius = eval_length(radius_text)[0] * self.scale
                return Point(radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle)))
            parts = split_top(spec)
            if len(parts) == 2:
                return Point(eval_length(parts[0])[0] * self.scale, eval_length(parts[1])[0] * self.scale)
        except ValueError:
            pass
        self.warn(f'Could not read coordinate ({spec})')
        return None

    def resolve_calc(self, expr, current):
        """Simple calc: (A)!t!(B), and sums like (A)+(1,2) or 0.5*(A)."""
        expr = expr.strip()
        partway = re.fullmatch(r'\((.+?)\)\s*!\s*([^!]+?)\s*!\s*\((.+?)\)', expr)
        if partway:
            a, b = self.resolve_point(partway.group(1), current), self.resolve_point(partway.group(3), current)
            try:
                t = eval_number(partway.group(2))
            except ValueError:
                a = None
            if a and b:
                return Point(a.x + t * (b.x - a.x), a.y + t * (b.y - a.y))
            return None
        total, sign, i = [0.0, 0.0], 1, 0
        terms = re.finditer(r'\s*([+-])?\s*(?:([\d.]+)\s*\*\s*)?\((.*?)\)', expr)
        found = False
        for term in terms:
            found = True
            sign = -1 if term.group(1) == '-' else 1
            factor = float(term.group(2)) if term.group(2) else 1.0
            point = self.resolve_point(term.group(3), current)
            if point is None:
                return None
            total[0] += sign * factor * point.x
            total[1] += sign * factor * point.y
        if found:
            return Point(*total)
        self.warn(f'calc expression ${expr}$ is not supported')
        return None

    # -- path walking --------------------------------------------------------

    def tokenize(self, text):
        tokens, i = [], 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
            elif text.startswith('++(', i) or text.startswith('+(', i):
                rel = '++' if text.startswith('++', i) else '+'
                inner, i = read_group(text, i + len(rel))
                tokens.append(('rel', rel, inner))
            elif ch == '(':
                inner, i = read_group(text, i)
                tokens.append(('coord', inner))
            elif ch == '[':
                inner, i = read_group(text, i)
                tokens.append(('opts', inner))
            elif ch == '{':
                inner, i = read_group(text, i)
                tokens.append(('group', inner))
            elif text.startswith('--', i):
                tokens.append(('op', '--'))
                i += 2
            elif text.startswith('..', i):
                tokens.append(('op', '..'))
                i += 2
            elif text.startswith('-|', i) or text.startswith('|-', i):
                tokens.append(('op', text[i:i + 2]))
                i += 2
            else:
                match = re.match(r'[A-Za-z]+', text[i:])
                if match:
                    tokens.append(('word', match.group(0)))
                    i += match.end()
                else:
                    self.warn(f'Unexpected {ch!r} in a path')
                    i += 1
        return tokens

    def walk_path(self, text, style, events, state, basis=None):
        """Read a path, appending ('piece'|'move'|'shape'|'node'|'nodeat') events."""
        tokens = self.tokenize(text)
        pending_nodes = []
        i = 0

        def take_point(index):
            """Point for tokens[index] (absolute or relative); returns (Point, next index)."""
            if index >= len(tokens):
                return None, index
            tok = tokens[index]
            if tok[0] == 'coord':
                if tok[1].strip() == 'cycle':
                    return 'cycle', index + 1
                return self.resolve_point(tok[1], state['current']), index + 1
            if tok[0] == 'rel' and state['current']:
                delta = self.resolve_point(tok[2], state['current'], vector=True)
                if delta is None:
                    return None, index + 1
                base = state.get('anchor') or state['current']
                point = Point(base.x + delta.x, base.y + delta.y)
                return (point, tok[1]), index + 1
            if tok == ('word', 'cycle'):
                return 'cycle', index + 1
            return None, index

        def settle(point):
            """Unwrap relative points; '+' does not move the current point."""
            if isinstance(point, tuple):
                return point[0], point[1] == '++'
            return point, True

        while i < len(tokens):
            tok = tokens[i]
            kind = tok[0]
            if kind in ('coord', 'rel'):
                point, i = take_point(i)
                point, moves = settle(point)
                if point is None or point == 'cycle':
                    continue
                events.append(('move', point))
                state['current'] = state['anchor'] = state['start'] = point
                continue
            if kind == 'opts':
                i += 1
                continue
            if kind == 'op' and tok[1] in ('--', '-|', '|-'):
                i += 1
                while i < len(tokens) and tokens[i] == ('word', 'node'):
                    i = self.read_node(tokens, i, pending_nodes)
                point, i = take_point(i)
                if point == 'cycle':
                    if state['start'] is not None:
                        events.append(('piece', {'kind': 'line', 'to': state['start'], 'nodes': pending_nodes,
                                                 'cycle': True}))
                        state['current'] = state['anchor'] = state['start']
                    pending_nodes = []
                    continue
                point, moves = settle(point)
                if point is None or state['current'] is None:
                    pending_nodes = []
                    continue
                if tok[1] != '--':
                    corner = (Point(point.x, state['current'].y) if tok[1] == '-|'
                              else Point(state['current'].x, point.y))
                    events.append(('piece', {'kind': 'line', 'to': corner, 'nodes': []}))
                events.append(('piece', {'kind': 'line', 'to': point, 'nodes': pending_nodes}))
                pending_nodes = []
                # The path continues from the new point, but a later ++ offset is measured
                # from the last point reached without a single +.
                state['current'] = point
                if moves:
                    state['anchor'] = point
                continue
            if kind == 'op' and tok[1] == '..':
                i += 1
                if i < len(tokens) and tokens[i] == ('word', 'controls'):
                    i += 1
                c1, i = take_point(i)
                c1, _ = settle(c1)
                c2 = c1
                if i < len(tokens) and tokens[i] == ('word', 'and'):
                    c2, i = take_point(i + 1)
                    c2, _ = settle(c2)
                if i < len(tokens) and tokens[i] == ('op', '..'):
                    i += 1
                end, i = take_point(i)
                end = state['start'] if end == 'cycle' else settle(end)[0]
                if None in (c1, c2, end) or state['current'] is None:
                    self.warn('Could not read a Bezier curve')
                    continue
                events.append(('piece', {'kind': 'cubic', 'c1': c1, 'c2': c2, 'to': end, 'nodes': []}))
                state['current'] = state['anchor'] = end
                continue
            if kind == 'word':
                word = tok[1]
                i += 1
                if word == 'node':
                    nodes = []
                    i = self.read_node(tokens, i - 1, nodes)
                    for node in nodes:
                        events.append(('node', node, state['current']))
                elif word == 'coordinate':
                    name, label = None, None
                    if i < len(tokens) and tokens[i][0] == 'opts':
                        label = self.parse_options([tokens[i][1]]).get('label')
                        i += 1
                    if i < len(tokens) and tokens[i][0] == 'coord':
                        name = tokens[i][1].strip()
                        i += 1
                    at = state['current']
                    if i < len(tokens) and tokens[i] == ('word', 'at'):
                        at, i = take_point(i + 1)
                        at, _ = settle(at)
                    if name and at is not None:
                        coord = self.define_coord(name, at.x, at.y)
                        state['current'] = state['anchor'] = Point(at.x, at.y, name)
                        if label:
                            # label=[options]position:text, e.g. label=above:$C$
                            match = re.fullmatch(r'(?:\[[^\]]*\])?\s*(?:([a-z ]+):)?(.*)', label.strip('{} '))
                            position = (match.group(1) or 'above').strip()
                            coord['label'] = match.group(2).strip()
                            coord['anchor'] = position if position in POSITIONS else 'above'
                elif word == 'arc':
                    i = self.read_arc(tokens, i, state, events, basis)
                elif word in ('circle', 'ellipse'):
                    i = self.read_round(tokens, i, word, state, events)
                elif word in ('rectangle', 'grid'):
                    corner, i = take_point(i)
                    corner, _ = settle(corner)
                    if corner is not None and corner != 'cycle' and state['current'] is not None:
                        events.append(('shape', {'kind': word, 'from': state['current'], 'to': corner}))
                        state['current'] = state['anchor'] = corner
                elif word == 'cycle':
                    continue
                elif word == 'to':
                    self.warn('"to" paths are imported as straight lines')
                    if i < len(tokens) and tokens[i][0] == 'opts':
                        i += 1
                    tokens.insert(i, ('op', '--'))
                elif word in ('edge', 'plot', 'parabola', 'sin', 'cos', 'let', 'pic', 'child', 'decorate'):
                    self.warn(f'Path operation "{word}" is not supported')
                    return
                else:
                    self.warn(f'Unexpected word "{word}" in a path')
                continue
            if kind == 'group':
                # A scoped group such as {[x={(c cm,s cm)},y={(-s cm,c cm)}] arc[...]}.
                inner = tok[1].strip()
                i += 1
                inner_basis = basis
                if inner.startswith('['):
                    opts, rest = read_group(inner, 0)
                    inner_basis = self.read_basis(opts) or basis
                    inner = inner[rest:]
                self.walk_path(inner, style, events, state, inner_basis)
                continue
            i += 1

    def read_basis(self, opts):
        values = {}
        for part in split_top(opts):
            key, _, value = part.partition('=')
            match = re.fullmatch(r'\{?\s*\(([^,]+),([^)]+)\)\s*\}?', value.strip())
            if key.strip() in ('x', 'y') and match:
                try:
                    values[key.strip()] = (eval_length(match.group(1))[0], eval_length(match.group(2))[0])
                except ValueError:
                    return None
        if 'x' in values and 'y' in values:
            return values['x'], values['y']
        return None

    def read_node(self, tokens, i, out):
        """tokens[i] is 'node'; parse [opts] (name) at (P) {text}. Returns next index."""
        i += 1
        opts, name, at, text = [], None, None, None
        while i < len(tokens):
            tok = tokens[i]
            if tok[0] == 'opts':
                opts.append(tok[1])
            elif tok[0] == 'coord' and name is None and at is None:
                name = tok[1].strip()
            elif tok == ('word', 'at') and i + 1 < len(tokens) and tokens[i + 1][0] == 'coord':
                at = self.resolve_point(tokens[i + 1][1], None)
                i += 1
            elif tok[0] == 'group':
                text = tok[1]
                i += 1
                break
            else:
                break
            i += 1
        out.append({'opts': opts, 'name': name, 'at': at, 'text': text})
        return i

    def read_arc(self, tokens, i, state, events, basis):
        current = state['current']
        if current is None or i >= len(tokens) or tokens[i][0] not in ('opts', 'coord'):
            self.warn('Could not read an arc')
            return i + 1
        tok = tokens[i]
        values = {}
        try:
            if tok[0] == 'opts':
                for part in split_top(tok[1]):
                    key, _, value = part.partition('=')
                    values[key.strip()] = value.strip()
            else:
                parts = tok[1].split(':')
                values['start angle'], values['end angle'] = parts[0], parts[1]
                radii = parts[2].split(' and ')
                values['x radius'] = radii[0]
                values['y radius'] = radii[-1]
            start = eval_number(values['start angle'])
            if 'delta angle' in values:
                delta = eval_number(values['delta angle'])
            else:
                delta = eval_number(values['end angle']) - start
            rx = eval_length(values.get('x radius', values.get('radius', '1')))[0] * self.scale
            ry = eval_length(values.get('y radius', values.get('radius', '1')))[0] * self.scale
        except (ValueError, KeyError, IndexError):
            self.warn('Could not read an arc')
            return i + 1
        if basis is None and self.transform:
            c, s = math.cos(math.radians(self.transform[0])), math.sin(math.radians(self.transform[0]))
            basis = ((c, s), (-s, c))
        (xx, xy), (yx, yy) = basis or ((1.0, 0.0), (0.0, 1.0))
        rotation = math.atan2(xy, xx)

        def offset(angle_deg):
            c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
            return (rx * c * xx + ry * s * yx, rx * c * xy + ry * s * yy)

        ox, oy = offset(start)
        cx, cy = current.x - ox, current.y - oy
        ex, ey = offset(start + delta)
        end = Point(cx + ex, cy + ey)
        mx, my = offset(start + delta / 2)
        events.append(('piece', {'kind': 'arc', 'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry,
                                 'rotation': rotation, 'start': start, 'delta': delta,
                                 'from': current, 'mid': Point(cx + mx, cy + my), 'to': end, 'nodes': []}))
        state['current'] = state['anchor'] = end
        return i + 1

    def read_round(self, tokens, i, word, state, events):
        current = state['current']
        if current is None or i >= len(tokens) or tokens[i][0] not in ('opts', 'coord'):
            self.warn(f'Could not read a {word}')
            return i + 1
        tok = tokens[i]
        try:
            if tok[0] == 'opts':
                values = {k.strip(): v.strip() for k, _, v in
                          (p.partition('=') for p in split_top(tok[1]))}
                rx_text = values.get('x radius', values.get('radius'))
                ry_text = values.get('y radius', values.get('radius'))
            else:
                radii = tok[1].split(' and ')
                rx_text, ry_text = radii[0], radii[-1]
            rx, unit = eval_length(rx_text)
            ry = eval_length(ry_text)[0]
        except (ValueError, TypeError, AttributeError):
            self.warn(f'Could not read a {word}')
            return i + 1
        events.append(('shape', {'kind': 'round', 'center': current, 'rx': rx * self.scale,
                                 'ry': ry * self.scale, 'unit': unit, 'raw': rx}))
        return i + 1

    # -- statements ----------------------------------------------------------

    def convert(self, body, picture_opts=''):
        for part in split_top(picture_opts):
            key, _, value = part.partition('=')
            if key.strip() == 'scale':
                try:
                    self.scale = eval_number(value)
                except ValueError:
                    pass
            elif part.strip():
                self.warn(f'tikzpicture option {part!r} was ignored')
        # Drop macro definitions before expanding, or \pgfmathsetmacro{\w} would become {6}.
        body = expand_macros(remove_macro_definitions(strip_comments(body)), self.macros)
        body = self.take_preamble_commands(body)
        self.reserved = set(re.findall(r"\(\s*([A-Za-z_][\w']*)\s*(?:\.[\w ]+)?\)", body))
        for statement in split_statements(body):
            self.convert_statement(statement)
        self.finish_regions()
        self.pair_circle_foci()
        return self.to_json()

    def referenced_names(self):
        names = set()
        for obj in self.objects:
            for key in ('from', 'to', 'center', 'center2', 'control1', 'control2', 'at'):
                if isinstance(obj.get(key), str):
                    names.add(obj[key])
            names.update(obj.get('points', []))
            for loop in obj.get('loops', []):
                for vertex in loop:
                    names.update([vertex] if isinstance(vertex, str) else vertex['cross'])
        return names

    def pair_circle_foci(self):
        """The editor gives each circle a second, coincident focus so it can become an
        ellipse. A circle is exported with its centre only, so reuse an otherwise unused
        coordinate at the same place as that second focus."""
        used = self.referenced_names()
        for obj in self.objects:
            if obj['type'] != 'TikZCircle' or obj['center'] != obj['center2']:
                continue
            center = self.coords[obj['center']]
            for name, coord in self.coords.items():
                if (name not in used and not coord['showPoint'] and not coord['label']
                        and abs(coord['x'] - center['x']) <= TOL and abs(coord['y'] - center['y']) <= TOL):
                    obj['center2'] = name
                    used.add(name)
                    break

    def take_preamble_commands(self, body):
        """Handle and remove commands that do not end with a semicolon."""
        def color_sub(match):
            self.define_color(match.group(1), match.group(2), match.group(3))
            return ' '
        body = re.sub(r'\\definecolor\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{([^}]*)\}', color_sub, body)

        def colorlet_sub(match):
            hex_color = self.color_hex(match.group(2))
            if hex_color:
                self.custom_colors[match.group(1).strip()] = hex_color
            else:
                self.warn(f'Could not read colour {match.group(2)!r}')
            return ' '
        body = re.sub(r'\\colorlet\s*\{([^}]*)\}\s*\{([^}]*)\}', colorlet_sub, body)

        def scope_sub(match):
            if match.group(1) and re.search(r'shift|rotate|scale|xslant|yslant', match.group(1)):
                self.warn(f'Scope transformation [{match.group(1)}] is not supported')
            return ' '
        body = re.sub(r'\\begin\{scope\}\s*(?:\[([^\]]*)\])?', scope_sub, body)
        body = re.sub(r'\\end\{scope\}', ' ', body)
        body = re.sub(r'\\(?:usetikzlibrary|usepackage|tikzset)\s*\{[^}]*\}', ' ', body)
        if re.search(r'\\foreach\b', body):
            self.warn('\\foreach loops are not supported')
        return body

    def convert_statement(self, statement):
        match = re.match(r'\\([A-Za-z]+)', statement)
        if not match:
            self.warn(f'Skipped: {statement[:40]}')
            return
        cmd = match.group(1)
        rest = statement[match.end():]
        if cmd == 'node':
            rest = 'node' + rest
            cmd = 'path'
        elif cmd == 'coordinate':
            rest = 'coordinate' + rest
            cmd = 'path'
        elif cmd not in ('draw', 'filldraw', 'fill', 'path', 'clip', 'shade', 'shadedraw'):
            if cmd != 'foreach':
                self.warn(f'\\{cmd} is not supported')
            return
        if cmd in ('clip', 'shade', 'shadedraw'):
            self.warn(f'\\{cmd} is not supported; drawn as a plain path' if cmd != 'clip'
                      else '\\clip is not supported')
            if cmd == 'clip':
                return
            cmd = 'filldraw' if cmd == 'shadedraw' else 'fill'
        option_texts = []
        rest = rest.lstrip()
        while rest.startswith('['):
            inner, end = read_group(rest, 0)
            option_texts.append(inner)
            rest = rest[end:].lstrip()
        style = self.parse_options(option_texts)
        stroke = cmd in ('draw', 'filldraw') or 'draw' in style['flags']
        filled = cmd in ('fill', 'filldraw') or 'fill' in style or 'fill' in style['flags']
        events, state = [], {'current': None, 'start': None}
        self.transform = (style['rotate'], style['rotateAbout']) if style.get('rotate') else None
        try:
            self.walk_path(rest, style, events, state)
            self.build(events, style, stroke, filled, cmd)
        finally:
            self.transform = None

    # -- building objects ----------------------------------------------------

    def stroke_fields(self, style):
        return {
            'color': style.get('color', 'black'),
            'thickness': style.get('thickness', 'thin'),
            'lineStyle': style.get('lineStyle', 'solid'),
        }

    def fill_fields(self, style, filled):
        fill = style.get('patternColor') or style.get('fill')
        if fill is None and filled:
            fill = style.get('color', 'black')
        pattern = style.get('pattern', 'none')
        if pattern != 'none' and fill is None:
            fill = 'black'
        return {
            'fill': fill if fill and (filled or pattern != 'none') else 'none',
            'fillOpacity': fmt_num(style.get('fillOpacity', 1.0)),
            'pattern': pattern,
        }

    def build(self, events, style, stroke, filled, cmd):
        subpaths, current = [], None
        nodes_at = []
        for event in events:
            if event[0] == 'move':
                current = {'start': event[1], 'pieces': [], 'closed': False}
                subpaths.append(current)
            elif event[0] == 'piece':
                if current is None:
                    continue
                piece = event[1]
                if piece.get('cycle'):
                    current['closed'] = True
                    last = current['pieces'][-1]['to'] if current['pieces'] else current['start']
                    if dist(last.xy, current['start'].xy) <= TOL and not piece['nodes']:
                        continue
                current['pieces'].append(piece)
            elif event[0] == 'shape':
                self.build_shape(event[1], style, stroke, filled, cmd)
            elif event[0] == 'node':
                node, at = event[1], event[2]
                attach = self.node_on_previous_piece(node, current)
                if not attach:
                    nodes_at.append((node, at))

        drawn = [sp for sp in subpaths if sp['pieces']]
        if drawn and (stroke or filled):
            region = (cmd == 'fill' and not stroke) or len(drawn) > 1 or 'even odd rule' in style['flags'] \
                or any(sp['closed'] and any(p['kind'] == 'arc' for p in sp['pieces']) for sp in drawn)
            single_bezier = (len(drawn) == 1 and drawn[0]['pieces'][0]['kind'] == 'cubic'
                             and all(p['kind'] == 'line' for p in drawn[0]['pieces'][1:])
                             and len(drawn[0]['pieces']) <= 2
                             and (len(drawn[0]['pieces']) == 1 or drawn[0]['closed']))
            if region and not (single_bezier and cmd != 'fill'):
                self.build_region(drawn, style, stroke, filled)
            else:
                for sp in drawn:
                    self.build_subpath(sp, style, filled)

        for node, at in nodes_at:
            self.build_node(node, at, style)

    def node_on_previous_piece(self, node, subpath):
        """A node after a point with pos/midway refers to the previous line piece."""
        style = self.parse_options(node['opts'])
        if subpath is None or not subpath['pieces'] or node['at'] is not None:
            return False
        if 'pos' not in style and 'midway' not in style['flags']:
            return False
        piece = subpath['pieces'][-1]
        if piece['kind'] != 'line':
            return False
        piece['nodes'].append(node)
        return True

    def embedded_node(self, node, segment_index=None):
        style = self.parse_options(node['opts'])
        result = {
            'text': (node['text'] or '').strip(),
            'position': fmt_num(style.get('pos', 0.5)),
            'anchor': style.get('position', 'above'),
            'fontSize': style.get('fontSize', 'normal'),
            'color': style.get('text', style.get('color', '')),
            'sloped': 'sloped' in style['flags'],
            'rotation': fmt_num(-style.get('rotate', 0)),
        }
        if segment_index is not None:
            result['segmentIndex'] = segment_index
        return result

    def build_subpath(self, sp, style, filled):
        pieces = sp['pieces']
        stroke = self.stroke_fields(style)
        if all(p['kind'] == 'line' for p in pieces):
            names = [self.coord_for(sp['start'])] + [self.coord_for(p['to']) for p in pieces]
            if len(pieces) == 1 and not sp['closed']:
                arrow, size = self.arrow_fields(style)
                self.add({'type': 'TikZSegment', 'id': self.new_id('line'), 'from': names[0], 'to': names[1],
                          **stroke, 'arrowEnd': arrow, 'arrowSize': size,
                          'nodes': [self.embedded_node(n) for n in pieces[0]['nodes']]})
                return
            if sp['closed']:
                names = names[:-1]
            if 'arrow' in style:
                self.warn('Arrows on multi-point paths are not supported')
            nodes = [self.embedded_node(n, index) for index, p in enumerate(pieces) for n in p['nodes']]
            self.add({'type': 'TikZPath', 'id': self.new_id('path'), 'points': names, 'closed': sp['closed'],
                      **stroke, **self.fill_fields(style, filled), 'nodes': nodes})
            return
        if pieces[0]['kind'] == 'cubic' and (len(pieces) == 1 or (len(pieces) == 2 and sp['closed'])):
            piece = pieces[0]
            arrow, size = self.arrow_fields(style)
            closed = sp['closed']
            self.add({'type': 'TikZBezier', 'id': self.new_id('bezier'),
                      'from': self.coord_for(sp['start']), 'control1': self.coord_for(piece['c1']),
                      'control2': self.coord_for(piece['c2']), 'to': self.coord_for(piece['to']),
                      'closed': closed, **stroke, 'arrowEnd': 'none' if closed else arrow, 'arrowSize': size,
                      **(self.fill_fields(style, filled) if closed else
                         {'fill': 'none', 'fillOpacity': 1.0, 'pattern': 'none'})})
            return
        if len(pieces) == 1 and pieces[0]['kind'] == 'arc':
            self.build_arc(pieces[0], style)
            return
        # Mixed path: one object per piece; arrows go on the outer ends.
        start = sp['start']
        for index, piece in enumerate(pieces):
            piece_style = dict(style)
            if 'arrow' in style and len(pieces) > 1:
                tips = self.parse_arrow(style['arrow'])
                head = tips[0] if index == 0 else ''
                tail = tips[1] if index == len(pieces) - 1 else ''
                scale = f'[scale={tips[2]}]' if tips[2] else ''
                spec = (('{' + head + scale + '}') if head and scale else head) + '-' + \
                       (('{' + tail + scale + '}') if tail and scale else tail)
                if head or tail:
                    piece_style['arrow'] = spec
                else:
                    piece_style.pop('arrow')
            self.build_subpath({'start': start, 'pieces': [piece], 'closed': False}, piece_style, False)
            start = piece['to']

    def build_arc(self, piece, style):
        if abs(piece['rx'] - piece['ry']) > TOL:
            self.warn('Elliptical arcs outside a fill are not supported')
            return
        # A rotated circular arc is the same arc with its angles turned.
        start, delta = piece['start'] + math.degrees(piece['rotation']), piece['delta']
        reverse = delta < 0
        if reverse:
            start, delta = start + delta, -delta
        center = self.coord_for(Point(piece['cx'], piece['cy']))
        arrow, size = self.arrow_fields(style, reverse=reverse)
        self.add({'type': 'TikZArc', 'id': self.new_id('arc'), 'center': center,
                  'radius': fmt_num(piece['rx']), 'startAngle': fmt_num(start),
                  'endAngle': fmt_num(start + delta), **self.stroke_fields(style),
                  'arrowEnd': arrow, 'arrowSize': size})

    def build_shape(self, shape, style, stroke, filled, cmd):
        if shape['kind'] == 'round':
            center = shape['center']
            # \fill (A) circle (2pt) marks a point.
            if shape['unit'] == 'pt' and filled and abs(shape['rx'] - shape['ry']) < 1e-12:
                name = self.coord_for(center)
                coord = self.coords[name]
                coord['showPoint'] = True
                coord['pointSize'] = fmt_num(shape['raw'] / UNIT_CM['pt'])
                coord['color'] = style.get('fill') or style.get('color', 'black')
                return
            a, b = shape['rx'], shape['ry']
            rotation = math.radians(style.get('rotate', 0))
            if b > a:
                a, b, rotation = b, a, rotation + math.pi / 2
            fields = {**self.stroke_fields(style), **self.fill_fields(style, filled)}
            if not stroke:
                fields['color'] = fields['fill'] if fields['fill'] != 'none' else 'black'
            if a - b <= TOL:
                name = self.coord_for(center)
                self.add({'type': 'TikZCircle', 'id': self.new_id('circle'), 'center': name, 'center2': name,
                          'radius': fmt_num(a), **fields})
                return
            c = math.sqrt(a * a - b * b)
            ux, uy = math.cos(rotation), math.sin(rotation)
            f1 = self.coord_for(Point(center.x - c * ux, center.y - c * uy))
            f2 = self.coord_for(Point(center.x + c * ux, center.y + c * uy))
            self.add({'type': 'TikZCircle', 'id': self.new_id('circle'), 'center': f1, 'center2': f2,
                      'radius': fmt_num(a), **fields})
            return
        p, q = shape['from'], shape['to']
        # Corners already carry the rotation; undo it about their midpoint to get the bounds.
        angle = math.radians(style.get('rotate', 0))
        cx, cy = (p.x + q.x) / 2, (p.y + q.y) / 2
        dx, dy = q.x - p.x, q.y - p.y
        w = abs(dx * math.cos(angle) + dy * math.sin(angle))
        h = abs(-dx * math.sin(angle) + dy * math.cos(angle))
        bounds = {'xMin': fmt_num(cx - w / 2), 'yMin': fmt_num(cy - h / 2),
                  'xMax': fmt_num(cx + w / 2), 'yMax': fmt_num(cy + h / 2)}
        if shape['kind'] == 'grid':
            self.add({'type': 'TikZGrid', 'id': self.new_id('grid'), **bounds,
                      'step': fmt_num(style.get('step', 1.0)), 'color': style.get('color', 'lightgray'),
                      'thickness': style.get('thickness', 'very thin'),
                      'rotation': fmt_num(style.get('rotate', 0))})
            return
        fields = {**self.stroke_fields(style), **self.fill_fields(style, filled)}
        if not stroke:
            fields['color'] = fields['fill'] if fields['fill'] != 'none' else 'black'
        self.add({'type': 'TikZRectangle', 'id': self.new_id('rect'), **bounds, **fields,
                  'rotation': fmt_num(style.get('rotate', 0))})

    def build_node(self, node, at, path_style):
        style = self.parse_options(node['opts'])
        point = node['at'] or at
        text = (node['text'] or '').strip()
        if point is None:
            return
        name = node['name']
        if name and point.name is None:
            # A named node also defines a coordinate.
            self.define_coord(name, point.x, point.y)
            point = Point(point.x, point.y, name)
        if 'draw' in style['flags'] and text:
            self.warn('Node borders (\\node[draw]) are not supported; the text is kept')
        if 'circle' in style['flags'] and ('fill' in style['flags'] or 'fill' in style) and not text:
            coord = self.coords[self.coord_for(point)]
            coord['showPoint'] = True
            coord['color'] = style.get('fill') or style.get('color', 'black')
            return
        image = re.search(r'\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}', text)
        if image:
            self.build_image(image, style, point, node)
            return
        if not text:
            return
        anchor = self.coord_for(point)
        coord = self.coords[anchor]
        parts = split_top(' , '.join(node['opts']))
        # The editor writes a point's own label as \node[<position>, <colour>] at (A) {...}.
        if (len(parts) == 2 and parts[0] in POSITIONS and '=' not in parts[1]
                and self.color(parts[1]) is not None and not coord['label']):
            coord['label'] = text
            coord['anchor'] = parts[0]
            coord['color'] = self.color(parts[1])
            return
        self.add({'type': 'TikZLabel', 'id': self.new_id('label'), 'at': anchor, 'text': text,
                  'position': style.get('position', 'above'), 'distance': fmt_num(style.get('distance', 0)),
                  'fontSize': style.get('fontSize', 'normal'),
                  'color': style.get('text', style.get('color', 'black')),
                  'rotation': fmt_num(-style.get('rotate', 0))})

    def build_image(self, match, style, point, node):
        width, height, rotation = 4.0, None, 0.0
        for part in split_top(match.group(1) or ''):
            key, _, value = part.partition('=')
            try:
                if key.strip() == 'width':
                    width = eval_length(value)[0]
                elif key.strip() == 'height':
                    height = eval_length(value)[0]
                elif key.strip() == 'angle':
                    rotation = -eval_number(value.replace('--', ''))
                    if value.strip().startswith('--'):
                        rotation = -rotation
            except ValueError:
                self.warn(f'Could not read image option {part!r}')
        filename = match.group(2).strip()
        path = self.base_dir / filename
        candidates = [path] + [path.with_suffix(s) for s in IMAGE_TYPES if not path.suffix]
        image_data, mime, aspect = None, IMAGE_TYPES.get(path.suffix.lower(), 'image/png'), 1.0
        for candidate in candidates:
            if candidate.is_file():
                raw = candidate.read_bytes()
                mime = IMAGE_TYPES.get(candidate.suffix.lower(), 'image/png')
                image_data = f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
                size = image_size(raw)
                if size:
                    aspect = size[0] / size[1]
                break
        if image_data is None:
            self.warn(f'Image file {filename!r} was not found; the image will be empty')
        self.add({'type': 'TikZImage', 'id': self.new_id('image'), 'at': self.coord_for(point),
                  'imageData': image_data, 'filename': filename, 'mimeType': mime,
                  'width': fmt_num(width), 'height': fmt_num(height) if height else None,
                  'opacity': fmt_num(style.get('opacity', 1.0)), 'anchor': 'center',
                  'rotation': fmt_num(rotation), 'naturalAspect': aspect})

    # -- fills ---------------------------------------------------------------

    def build_region(self, subpaths, style, stroke, filled):
        # The editor writes a fill before the shapes that bound it (so it sits underneath
        # them). Match it once the whole picture is read, then put it back in this place.
        marker = {'type': '_pending_region'}
        self.objects.append(marker)
        self.pending_regions.append((marker, subpaths, style, stroke, filled))

    def finish_regions(self):
        for marker, subpaths, style, stroke, filled in self.pending_regions:
            index = self.objects.index(marker)
            self.objects.remove(marker)
            count = len(self.objects)
            self.make_region(subpaths, style, stroke, filled)
            # Move the new region into place; any new corner points stay at the end.
            if len(self.objects) > count and self.objects[-1]['type'] == 'TikZRegion':
                self.objects.insert(index, self.objects.pop())
        self.pending_regions = []

    def make_region(self, subpaths, style, stroke, filled):
        rings = []
        for sp in subpaths:
            pieces = list(sp['pieces'])
            last = pieces[-1]['to']
            if dist(last.xy, sp['start'].xy) > TOL:
                pieces.append({'kind': 'line', 'to': sp['start'], 'nodes': []})
            rings.append({'start': sp['start'], 'pieces': pieces})

        fill = self.fill_fields(style, filled)
        fields = {
            'fill': fill['fill'], 'fillOpacity': fill['fillOpacity'], 'pattern': fill['pattern'],
            'color': style.get('color', 'black') if stroke else 'none',
            'thickness': style.get('thickness', 'thin'), 'lineStyle': style.get('lineStyle', 'solid'),
        }
        if fields['fill'] == 'none' and not stroke:
            return

        straight = all(p['kind'] == 'line' for r in rings for p in r['pieces'])
        if straight:
            loops = self.legacy_loops(rings, allow_new=False)
            if loops:
                self.add({'type': 'TikZRegion', 'id': self.new_id('region'), 'loops': loops, **fields})
                return
        curve_loops = self.curve_loops(rings)
        if curve_loops:
            self.add({'type': 'TikZRegion', 'id': self.new_id('region'), 'loops': [],
                      'curveLoops': curve_loops, **fields})
            return
        if straight:
            loops = self.legacy_loops(rings, allow_new=True)
            if loops:
                self.add({'type': 'TikZRegion', 'id': self.new_id('region'), 'loops': loops, **fields})
                return
        self.warn('A curved fill does not follow the imported shapes and was skipped')

    def segment_cross(self, point):
        """{'cross': [...]} when the point is where two imported segments cross."""
        segments = [o for o in self.objects if o['type'] in ('TikZSegment', 'TikZVector')]
        for i, s in enumerate(segments):
            for t in segments[i + 1:]:
                a, b = self.coords[s['from']], self.coords[s['to']]
                c, d = self.coords[t['from']], self.coords[t['to']]
                hit = segment_intersection((a['x'], a['y']), (b['x'], b['y']), (c['x'], c['y']), (d['x'], d['y']))
                if hit and dist(hit, point.xy) <= TOL:
                    first, second = sorted([s['from'], s['to']]), sorted([t['from'], t['to']])
                    if json.dumps(first, separators=(',', ':')) > json.dumps(second, separators=(',', ':')):
                        first, second = second, first
                    return {'cross': first + second}
        return None

    def legacy_loops(self, rings, allow_new):
        loops = []
        for ring in rings:
            vertices = [ring['start']] + [p['to'] for p in ring['pieces'][:-1]]
            loop = []
            for vertex in vertices:
                if vertex.name and vertex.name in self.coords:
                    loop.append(vertex.name)
                    continue
                cross = self.segment_cross(vertex)
                if cross:
                    loop.append(cross)
                elif allow_new:
                    loop.append(self.coord_for(vertex))
                else:
                    return None
            if len(loop) < 3:
                return None
            loops.append(loop)
        return loops

    def fill_sources(self):
        for obj in self.objects:
            prims = self.primitives_for(obj)
            for part, prim in enumerate(prims):
                yield obj, part, prim

    def coord_xy(self, name):
        c = self.coords.get(name)
        return (c['x'], c['y']) if c else None

    def primitives_for(self, obj):
        """The editor's fillPrimitivesFor(), on imported objects."""
        kind = obj['type']
        xy = self.coord_xy

        def polyline(points, closed):
            if len(points) < 2 or None in points:
                return []
            edges = [{'kind': 'line', 'p0': points[i], 'p1': points[i + 1]} for i in range(len(points) - 1)]
            if closed:
                edges.append({'kind': 'line', 'p0': points[-1], 'p1': points[0]})
            return edges

        def arc(cx, cy, rx, ry, rotation, start, sweep):
            if rx <= 0 or ry <= 0 or not sweep:
                return []
            return [{'kind': 'arc', 'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'rotation': rotation,
                     'start': start, 'sweep': sweep}]

        if kind in ('TikZSegment', 'TikZVector'):
            return polyline([xy(obj['from']), xy(obj['to'])], False)
        if kind == 'TikZPath':
            return polyline([xy(n) for n in obj['points']], obj['closed'])
        if kind == 'TikZBezier':
            pts = [xy(obj[k]) for k in ('from', 'control1', 'control2', 'to')]
            if None in pts:
                return []
            prims = [{'kind': 'cubic', 'p0': pts[0], 'p1': pts[1], 'p2': pts[2], 'p3': pts[3]}]
            if obj['closed'] and pts[0] != pts[3]:
                prims.append({'kind': 'line', 'p0': pts[3], 'p1': pts[0]})
            return prims
        if kind == 'TikZCircle':
            c1, c2 = xy(obj['center']), xy(obj['center2'])
            if c1 is None or c2 is None:
                return []
            if obj['center'] != obj['center2'] and dist(c1, c2) > 0.001:
                half = dist(c1, c2) / 2
                a = obj['radius']
                b = 0.1 if half >= a else math.sqrt(a * a - half * half)
                return arc((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2, a, b,
                           math.atan2(c2[1] - c1[1], c2[0] - c1[0]), 0, 2 * math.pi)
            return arc(c1[0], c1[1], obj['radius'], obj['radius'], 0, 0, 2 * math.pi)
        if kind == 'TikZArc':
            c = xy(obj['center'])
            if c is None:
                return []
            return arc(c[0], c[1], obj['radius'], obj['radius'], 0, math.radians(obj['startAngle']),
                       fill_arc_sweep(obj['startAngle'], obj['endAngle']))
        if kind == 'TikZRectangle':
            cx, cy = (obj['xMin'] + obj['xMax']) / 2, (obj['yMin'] + obj['yMax']) / 2
            angle = math.radians(obj.get('rotation', 0) or 0)
            cos, sin = math.cos(angle), math.sin(angle)
            corners = [(obj['xMin'], obj['yMin']), (obj['xMax'], obj['yMin']),
                       (obj['xMax'], obj['yMax']), (obj['xMin'], obj['yMax'])]
            return polyline([(cx + (x - cx) * cos - (y - cy) * sin, cy + (x - cx) * sin + (y - cy) * cos)
                             for x, y in corners], True)
        return []

    def piece_samples(self, start, piece):
        """Start, middle and end points of a fill piece."""
        if piece['kind'] == 'line':
            end = piece['to'].xy
            return start.xy, ((start.x + end[0]) / 2, (start.y + end[1]) / 2), end
        if piece['kind'] == 'cubic':
            p = {'kind': 'cubic', 'p0': start.xy, 'p1': piece['c1'].xy, 'p2': piece['c2'].xy, 'p3': piece['to'].xy}
            return start.xy, prim_point(p, 0.5), piece['to'].xy
        return start.xy, piece['mid'].xy, piece['to'].xy

    def curve_loops(self, rings):
        """Match each piece of each ring to a span of an imported object's primitive."""
        loops = []
        for ring in rings:
            runs, start = [], ring['start']
            for piece in ring['pieces']:
                if dist(start.xy, piece['to'].xy) <= TOL and piece['kind'] == 'line':
                    start = piece['to']
                    continue
                run = self.match_piece(start, piece)
                if run is None:
                    return None
                runs.extend(run)
                start = piece['to']
            if not runs:
                return None
            loops.append(runs)
        return loops

    def match_piece(self, start, piece):
        a, mid, b = self.piece_samples(start, piece)
        wanted = {'line': ('line',), 'cubic': ('cubic',), 'arc': ('arc',)}[piece['kind']]
        for obj, part, prim in self.fill_sources():
            if prim['kind'] not in wanted:
                continue
            t0, d0 = prim_param(prim, a)
            t1, d1 = prim_param(prim, b)
            tm, dm = prim_param(prim, mid)
            if max(d0, d1, dm) > 5 * TOL:
                continue
            periodic = prim['kind'] == 'arc' and abs(prim['sweep'] - 2 * math.pi) < 1e-9
            if periodic:
                spans = self.periodic_spans(t0, tm, t1, piece)
                if spans is None:
                    continue
                return [{'objectId': obj['id'], 'part': part, 't0': fmt_num(s), 't1': fmt_num(e)}
                        for s, e in spans]
            if not (min(t0, t1) - 1e-6 <= tm <= max(t0, t1) + 1e-6):
                continue
            return [{'objectId': obj['id'], 'part': part, 't0': fmt_num(t0), 't1': fmt_num(t1)}]
        return None

    @staticmethod
    def periodic_spans(t0, tm, t1, piece):
        """Parameter spans on a closed ellipse; split at its seam (t = 0 = 1) if crossed."""
        forward = piece['delta'] > 0 if piece['kind'] == 'arc' else None
        if forward is None:
            forward = (tm - t0) % 1 < (t1 - t0) % 1
        if forward:
            if t1 <= t0 + 1e-9:
                t1 += 1
            if t1 - 1 > 1e-9 and t0 < 1:
                if t1 > 2:
                    return None
                return [(t0, 1.0), (0.0, t1 - 1)] if t1 - 1 > 1e-9 else [(t0, 1.0)]
            return [(t0, min(t1, 1.0))]
        if t0 <= t1 + 1e-9:
            t0 += 1
        if t0 - 1 > 1e-9:
            return [(t0 - 1, 0.0), (1.0, t1)] if t1 < 1 - 1e-9 else [(t0 - 1, 0.0)]
        return [(t0, t1)]

    # -- output --------------------------------------------------------------

    def to_json(self):
        xs, ys = [], []
        for obj in self.objects:
            if obj['type'] == 'TikZCoordinate':
                xs.append(obj['x'])
                ys.append(obj['y'])
            elif 'xMin' in obj:
                xs += [obj['xMin'], obj['xMax']]
                ys += [obj['yMin'], obj['yMax']]
        if xs:
            width, height = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
            # Fit the drawing to a typical canvas (about 640 x 560 px beside the panels).
            zoom = max(10, min(100, 560 / width, 480 / height))
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            view_x, view_y = 330 - cx * zoom, 300 + cy * zoom
        else:
            zoom, view_x, view_y = 50, 400, 400
        return {
            'version': '1.0', 'viewX': round(view_x, 2), 'viewY': round(view_y, 2), 'zoom': round(zoom, 2),
            'customColors': self.custom_colors, 'objects': self.objects,
        }


def segment_intersection(a, b, c, d):
    dx, dy, ex, ey = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    det = dx * ey - dy * ex
    if abs(det) < 1e-12:
        return None
    t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / det
    u = ((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) / det
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + t * dx, a[1] + t * dy)
    return None


def image_size(raw):
    """(width, height) of PNG or JPEG data, else None."""
    if raw[:8] == b'\x89PNG\r\n\x1a\n' and len(raw) >= 24:
        return struct.unpack('>II', raw[16:24])
    if raw[:2] == b'\xff\xd8':
        i = 2
        while i + 9 < len(raw):
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            length = struct.unpack('>H', raw[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack('>HH', raw[i + 5:i + 9])
                return width, height
            i += 2 + length
    return None


def extract_tikzpictures(tex_content):
    """(options, body) for every tikzpicture environment."""
    pictures = []
    for match in re.finditer(r'\\begin\{tikzpicture\}\s*(\[)?', tex_content):
        start = match.end()
        options = ''
        if match.group(1):
            options, start = read_group(tex_content, match.end() - 1)
        end = tex_content.find('\\end{tikzpicture}', start)
        if end < 0:
            break
        pictures.append((options, tex_content[start:end]))
    return pictures


def preamble_colors(tex_content):
    """Colours defined before the first tikzpicture."""
    first = tex_content.find('\\begin{tikzpicture}')
    converter = TikZConverter()
    converter.take_preamble_commands(strip_comments(tex_content[:first if first >= 0 else len(tex_content)]))
    return converter.custom_colors


def convert_tex(tex_content, base_dir=Path('.')):
    """Return a list of (project dict, warnings) for each tikzpicture."""
    clean = strip_comments(tex_content)
    macros = collect_macros(clean)
    colors = preamble_colors(tex_content)
    results = []
    for options, body in extract_tikzpictures(clean):
        converter = TikZConverter(base_dir, macros, colors)
        try:
            project = converter.convert(body, options)
        except Exception as err:  # Report, but keep converting other pictures.
            converter.warn(f'Conversion stopped early: {err}')
            project = converter.to_json()
        results.append((project, converter.warnings))
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Convert TikZ pictures to tikz-draw JSON format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tikz2view.py input.tex
  python tikz2view.py input.tex -o diagram.json
  cat input.tex | python tikz2view.py -o output.json
        """
    )
    parser.add_argument('input', nargs='?', help='Input .tex file (or use stdin)')
    parser.add_argument('-o', '--output', help='Output .json file (default: auto-generate)')
    parser.add_argument('-q', '--quiet', action='store_true', help='Do not print warnings')
    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: File '{args.input}' not found", file=sys.stderr)
            sys.exit(1)
        tex_content = input_path.read_text(encoding='utf-8')
        base_name, base_dir = input_path.stem, input_path.parent
    else:
        tex_content = sys.stdin.read()
        base_name, base_dir = 'tikz', Path('.')

    results = convert_tex(tex_content, base_dir)
    if not results:
        print('No tikzpicture environments found', file=sys.stderr)
        sys.exit(1)

    print(f'Found {len(results)} tikzpicture(s)')
    for i, (project, warnings) in enumerate(results):
        if args.output:
            output_path = Path(args.output)
            output_file = output_path if len(results) == 1 else \
                output_path.with_name(f'{output_path.stem}_{i + 1}{output_path.suffix}')
        else:
            output_file = Path(f'{base_name}_{i + 1}.json' if len(results) > 1 else f'{base_name}.json')
        output_file.write_text(json.dumps(project, indent=2), encoding='utf-8')
        print(f'  Created: {output_file} ({len(project["objects"])} objects)')
        if warnings and not args.quiet:
            for warning in warnings:
                print(f'    warning: {warning}', file=sys.stderr)


if __name__ == '__main__':
    main()
