"""Tests for tikz2view.py (TikZ -> tikz-draw project).

Run from the repository root:
    python -m unittest discover -s tests/tikz2view -v

editor-export.tex is tikz-draw's own export of a drawing that uses every object type,
so converting it must rebuild that drawing. (Loading the result in the editor and
exporting again reproduces editor-export.tex exactly.)
"""

import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

import tikz2view  # noqa: E402


def convert(tex, base_dir=HERE):
    results = tikz2view.convert_tex(tex, base_dir)
    assert len(results) == 1
    return results[0]


def picture(body, options=''):
    return f'\\begin{{tikzpicture}}{options}\n{body}\n\\end{{tikzpicture}}'


def by_type(project, kind):
    return [o for o in project['objects'] if o['type'] == kind]


def coords(project):
    return {o['name']: o for o in by_type(project, 'TikZCoordinate')}


class EditorExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project, cls.warnings = convert((HERE / 'editor-export.tex').read_text(encoding='utf-8'))
        cls.objects = cls.project['objects']

    def test_no_warnings(self):
        self.assertEqual(self.warnings, [])

    def test_every_object_type(self):
        counts = Counter(o['type'] for o in self.objects)
        self.assertEqual(counts['TikZSegment'], 6)
        self.assertEqual(counts['TikZCircle'], 4)
        self.assertEqual(counts['TikZArc'], 2)
        self.assertEqual(counts['TikZRectangle'], 2)
        self.assertEqual(counts['TikZPath'], 2)
        self.assertEqual(counts['TikZBezier'], 2)
        self.assertEqual(counts['TikZLabel'], 2)
        self.assertEqual(counts['TikZGrid'], 1)
        self.assertEqual(counts['TikZImage'], 1)
        self.assertEqual(counts['TikZRegion'], 4)

    def test_points_and_labels(self):
        a = coords(self.project)['A']
        self.assertTrue(a['showPoint'])
        self.assertEqual((a['color'], a['pointSize'], a['label'], a['anchor']), ('red', 3, '$A$', 'below left'))
        labels = {l['text']: l for l in by_type(self.project, 'TikZLabel')}
        alpha = labels['$\\alpha+\\beta$']
        self.assertEqual((alpha['position'], alpha['distance'], alpha['fontSize'], alpha['color'], alpha['rotation']),
                         ('above right', 4, 'Large', 'magenta', 30))
        self.assertEqual(labels['plain']['rotation'], -15)

    def test_arrows_styles_and_nodes(self):
        segments = {(s['from'], s['to']): s for s in by_type(self.project, 'TikZSegment')}
        diamond = segments[('A', 'E')]
        self.assertEqual((diamond['arrowEnd'], diamond['arrowSize']), ('Diamond-Diamond', 1.5))
        self.assertEqual((diamond['color'], diamond['thickness'], diamond['lineStyle']),
                         ('myblue', 'thick', 'loosely dashed'))
        node = diamond['nodes'][0]
        self.assertEqual((node['text'], node['position'], node['anchor'], node['sloped'], node['fontSize'], node['color']),
                         ('$d$', 0.3, 'above left', True, 'small', 'red'))
        self.assertEqual(segments[('B', 'E')]['arrowEnd'], '-Computer Modern Rightarrow')
        self.assertEqual(segments[('E', 'D')]['arrowEnd'], 'Hooks-Rays')
        self.assertEqual(segments[('A', 'B')]['arrowEnd'], 'Stealth-')
        self.assertEqual(self.project['customColors'], {'myblue': '#1e3cc8', 'teal1': '#008080'})

    def test_circles_ellipse_and_second_focus(self):
        circles = by_type(self.project, 'TikZCircle')
        filled = next(c for c in circles if c['fill'] == 'green')
        self.assertEqual((filled['center'], filled['center2'], filled['fillOpacity']), ('O', 'O2', 0.4))
        ellipse = next(c for c in circles if c['center'] != c['center2'] and c['center'] != 'O')
        self.assertEqual((ellipse['center'], ellipse['center2'], ellipse['radius']), ('F1', 'F2', 2))
        self.assertEqual((ellipse['fill'], ellipse['pattern']), ('orange', 'north east lines'))

    def test_arcs_rectangles_grid_and_image(self):
        arcs = by_type(self.project, 'TikZArc')
        self.assertEqual([(a['center'], a['radius'], a['startAngle'], a['endAngle']) for a in arcs],
                         [('O', 3, 20, 160), ('Q', 1, 300, 390)])
        rect = next(r for r in by_type(self.project, 'TikZRectangle') if r['rotation'])
        self.assertEqual((rect['xMin'], rect['yMin'], rect['xMax'], rect['yMax'], rect['rotation']), (10, 3, 13, 5, 25))
        self.assertEqual((rect['fill'], rect['pattern'], rect['fillOpacity']), ('cyan', 'grid', 0.5))
        grid = by_type(self.project, 'TikZGrid')[0]
        self.assertEqual((grid['step'], grid['color'], grid['thickness'], grid['rotation']), (0.5, 'gray', 'very thin', 15))
        image = by_type(self.project, 'TikZImage')[0]
        self.assertTrue(image['imageData'].startswith('data:image/png;base64,'))
        self.assertEqual((image['width'], image['opacity'], image['rotation'], image['naturalAspect']), (2, 0.7, -20, 2))

    def test_paths_and_beziers(self):
        closed = next(p for p in by_type(self.project, 'TikZPath') if p['closed'])
        self.assertEqual(closed['points'], ['P1', 'P2', 'P3'])
        self.assertEqual([(n['text'], n['segmentIndex'], n['position']) for n in closed['nodes']],
                         [('seg0', 0, 0.5), ('close', 2, 0.25)])
        beziers = by_type(self.project, 'TikZBezier')
        self.assertEqual([(b['from'], b['control1'], b['control2'], b['to']) for b in beziers],
                         [('K1', 'K2', 'K3', 'K4'), ('Z1', 'Z2', 'Z3', 'Z4')])
        self.assertEqual(beziers[0]['arrowEnd'], 'Kite-Triangle')
        self.assertEqual((beziers[1]['closed'], beziers[1]['fill'], beziers[1]['pattern']), (True, 'red', 'dots'))

    def test_fills_follow_their_shapes(self):
        regions = by_type(self.project, 'TikZRegion')
        ids = {o['id']: o['type'] for o in self.objects}
        # Straight cell between crossing segments: corner names plus a crossing point.
        self.assertEqual(regions[0]['loops'], [['A', 'B', {'cross': ['A', 'E', 'B', 'D']}]])
        # Curved fills reference real objects and keep their order (fills sit below shapes).
        for region in regions[1:]:
            for ring in region['curveLoops']:
                for run in ring:
                    self.assertIn(run['objectId'], ids)
                    self.assertTrue(0 <= run['t0'] <= 1 and 0 <= run['t1'] <= 1)
        lens = regions[1]
        self.assertEqual({ids[r['objectId']] for r in lens['curveLoops'][0]}, {'TikZCircle', 'TikZArc'})
        self.assertEqual((lens['color'], lens['lineStyle'], lens['pattern']), ('red', 'dashed', 'crosshatch'))
        self.assertEqual(len(regions[2]['curveLoops']), 2, 'rectangle with a circular hole')
        first_region = self.objects.index(regions[0])
        first_segment = self.objects.index(by_type(self.project, 'TikZSegment')[0])
        self.assertLess(first_region, first_segment)


class HandWrittenTests(unittest.TestCase):
    def test_sample_file(self):
        project, warnings = convert((HERE / 'handwritten.tex').read_text(encoding='utf-8'))
        self.assertEqual(sorted(warnings), sorted([
            '\\foreach loops are not supported',
            'Node borders (\\node[draw]) are not supported; the text is kept',
            "Option 'decorate' is not supported and was ignored",
        ]))
        c = coords(project)
        self.assertTrue(c['P']['showPoint'])
        self.assertAlmostEqual(c['P']['x'], 1.5 * 2 * 0.8660254, places=6)  # (30:2) at scale=1.5
        arcs = by_type(project, 'TikZArc')
        self.assertEqual((arcs[0]['center'], arcs[0]['endAngle']), ('O', 30))
        self.assertEqual((arcs[1]['startAngle'], arcs[1]['endAngle']), (-90, 90), 'clockwise arc')
        triangle = [(c[n]['x'], c[n]['y']) for n in by_type(project, 'TikZPath')[0]['points']]
        self.assertEqual(triangle, [(4.5, 3), (6, 4.5), (4.5, 1.5)], '+ does not move the reference point')
        self.assertEqual(project['customColors']['accent'], '#cc6600')

    def test_coordinate_forms(self):
        project, warnings = convert(picture(
            '\\coordinate (A) at (1,2); \\coordinate (B) at (3,0);'
            '\\draw ($(A)!0.5!(B)$) -- (A |- B) -- (A -| B) -- (90:1cm) -- (10mm, 5pt);'))
        self.assertEqual(warnings, [])
        path = by_type(project, 'TikZPath')[0]
        points = [(round(coords(project)[n]['x'], 4), round(coords(project)[n]['y'], 4)) for n in path['points']]
        self.assertEqual(points, [(2, 1), (1, 0), (3, 2), (0, 1), (1, round(5 / 28.45274, 4))])

    def test_rotation_about_origin(self):
        # rotate=90 turns the 2 x 1 rectangle about the origin: centre (2,1)+(4,2) -> (-1.5, 3).
        # The editor stores it unrotated about that centre, plus the rotation.
        project, _ = convert(picture('\\draw[rotate=90] (2,1) rectangle (4,2);'))
        rect = by_type(project, 'TikZRectangle')[0]
        self.assertEqual((rect['xMin'], rect['xMax'], rect['yMin'], rect['yMax'], rect['rotation']),
                         (-2.5, -0.5, 2.5, 3.5, 90))

    def test_points_and_default_arrow_tip(self):
        project, _ = convert(picture(
            '\\coordinate (A) at (0,0); \\fill[blue] (A) circle (1.5pt);'
            '\\draw[->, >=Latex] (A) -- (1,0) node[midway, below] {m};'))
        self.assertEqual((coords(project)['A']['showPoint'], coords(project)['A']['color']), (True, 'blue'))
        segment = by_type(project, 'TikZSegment')[0]
        self.assertEqual(segment['arrowEnd'], '-Latex')
        self.assertEqual([(n['text'], n['anchor']) for n in segment['nodes']], [('m', 'below')])

    def test_polygon_fill_without_shapes(self):
        project, warnings = convert(picture('\\fill[green!30] (0,0) -- (2,0) -- (1,1) -- cycle;'))
        self.assertEqual(warnings, [])
        region = by_type(project, 'TikZRegion')[0]
        self.assertEqual(len(region['loops'][0]), 3)
        self.assertEqual(region['fill'], 'green30')
        self.assertEqual(project['customColors']['green30'], '#b3ffb3')

    def test_macros(self):
        tex = '\\def\\r{2}\\newcommand{\\h}{0.5}\n' + picture(
            '\\pgfmathsetmacro{\\w}{\\r*3}\\draw (0,0) rectangle (\\w,\\h); \\draw (0,0) circle (\\r);')
        project, warnings = convert(tex)
        self.assertEqual(warnings, [])
        rect = by_type(project, 'TikZRectangle')[0]
        self.assertEqual((rect['xMax'], rect['yMax']), (6, 0.5))
        self.assertEqual(by_type(project, 'TikZCircle')[0]['radius'], 2)

    def test_unsupported_constructs_are_reported(self):
        _, warnings = convert(picture('\\draw (0,0) to[out=90,in=180] (1,1); \\draw plot coordinates {(0,0) (1,1)};'))
        self.assertTrue(any('"to" paths' in w for w in warnings))
        self.assertTrue(any('"plot"' in w for w in warnings))


class SafetyTests(unittest.TestCase):
    def test_expressions_cannot_run_code(self):
        with self.assertRaises(ValueError):
            tikz2view.eval_number("__import__('os').system('echo unsafe')")
        with self.assertRaises(ValueError):
            tikz2view.eval_number('().__class__')
        self.assertAlmostEqual(tikz2view.eval_number('2*cos(60)+sqrt(4)^2'), 5)

    def test_malicious_coordinate_is_only_a_warning(self):
        project, warnings = convert(picture("\\draw (__import__('os').system('echo x'), 1) -- (1,1);"))
        self.assertTrue(any('Could not read coordinate' in w for w in warnings))


if __name__ == '__main__':
    unittest.main()
