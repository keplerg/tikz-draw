# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains tools for working with TikZ graphics:

1. **tikz-draw.html** - A browser-based visual editor for creating TikZ diagrams with LaTeX support
2. **tikz2ggb.py** - Python script to convert TikZ pictures from .tex files to GeoGebra .ggb files
3. **tikz2view.py** - Python script to convert TikZ pictures to tikz-draw JSON format

## Running the Applications

### TikZ Draw Editor (tikz-draw.html)

Simply open `tikz-draw.html` in a modern web browser - no build process or server required:

```bash
# Linux
xdg-open tikz-draw.html

# macOS
open tikz-draw.html

# Windows
start tikz-draw.html
```

The application is a single self-contained HTML file (~4,280 lines) with all CSS and JavaScript inline.

### TikZ to GeoGebra Converter (tikz2ggb.py)

```bash
# Convert a .tex file to .ggb files
python tikz2ggb.py input.tex

# Specify output directory
python tikz2ggb.py input.tex --output-dir ./output

# Enable verbose output for debugging
python tikz2ggb.py input.tex --verbose
```

Requirements: Python 3.6+ (uses standard library only)

### TikZ to JSON Converter (tikz2view.py)

```bash
# Convert a .tex file to JSON
python tikz2view.py input.tex

# Specify output file
python tikz2view.py input.tex -o output.json

# Read from stdin
cat input.tex | python tikz2view.py -o output.json
```

Requirements: Python 3.6+ (uses standard library only)

## Architecture Overview

### tikz-draw.html Architecture

This is a single-page application with the following key components:

**Object Model (Lines ~130-650)**
- Class hierarchy: `TikZCoordinate`, `TikZSegment`, `TikZVector`, `TikZCircle`, `TikZArc`, `TikZRectangle`, `TikZPath`, `TikZBezier`, `TikZGrid`, `TikZLabel`
- Each class has `toTikZ()` method for export and `draw(ctx, transform)` for canvas rendering
- Compound objects (segments/vectors) can have embedded labels stored in `this.nodes` array

**Application State Management (Lines ~650-1100)**
- Global `app` object manages:
  - `objects[]`: ordered list of all drawing objects
  - `selectedObject`: currently selected object for editing
  - `currentTool`: active drawing tool
  - `viewX`, `viewY`, `zoom`: canvas viewport state
  - `customColors`: user-defined color palette

**MathJax Integration (Lines ~1200-1400)**
- **CRITICAL**: MathJax SVG glyphs are stored in a global cache `#MJX-SVG-global-cache`
- When rendering LaTeX to canvas, the global cache must be inlined into each SVG or `<use>` references will break
- Rendering pipeline: LaTeX → MathJax SVG → inline defs → base64 PNG → canvas Image
- LaTeX is rendered on both canvas and in preview panels

**Canvas Rendering (Lines ~2500-2800)**
- White background (#ffffff) to match LaTeX default
- Coordinate transformation: screen ↔ TikZ coordinates via pan/zoom
- Renders objects in order from `app.objects[]` array
- Selection highlighting with dashed cyan border

**Properties Panel (Lines ~2900-3400)**
- Dynamically generated based on `selectedObject.type`
- Updates object properties in real-time
- For embedded labels on lines/vectors, shows modal popup editor

**TikZ Export (Lines ~3500-3700)**
- Groups output by type: coordinates, visible points, segments, vectors, circles, arcs, labels, etc.
- Preserves all styling: colors, line styles, arrow types, font sizes
- Clean, well-formatted output with comments

**File Operations (Lines ~4100-4300)**
- Save: JSON serialization with explicit property enumeration (class spread operators don't work reliably)
- Load: JSON deserialization with object reconstruction via class constructors
- **Important**: All object properties must be explicitly listed in `serializeObject()` function

### tikz2ggb.py Architecture

**Parser Architecture (Lines ~390-1400)**
- `TikZParser` class:
  - Macro expansion system with `_expand_macros()` - supports `\def` and `\newcommand`
  - Coordinate system: handles Cartesian `(x,y)`, polar `(angle:radius)`, and named coordinate references
  - Expression evaluator with safe `eval()` using restricted namespace - supports TikZ calc library
  - Color system: basic TikZ colors + custom `\colorlet` and `\definecolor` support

**GeoGebra XML Generation (Lines ~125-383)**
- Each TikZ element maps to GeoGebra classes: `GGBPoint`, `GGBSegment`, `GGBVector`, `GGBArc`, `GGBCircle`, `GGBText`
- **Critical Issue**: GeoGebra XML has strict requirements:
  - Arcs require: hidden center point + hidden circle + start/end points + Arc command
  - Circles require: hidden center point + point on circumference + Circle command
  - Points must be defined before they're referenced in commands
  - Text uses LaTeX mode with `<isLaTeX val="true"/>`
- Name sanitization: point names ending in digits (like `P2`) are prefixed with `p` (→ `pP2`) to prevent GeoGebra from interpreting as algebra `P*2`

**Coordinate Calculation (Lines ~500-650)**
- Handles `let...in` syntax from TikZ calc library
- Polar to Cartesian conversion with degree-based angles
- Expression evaluation supports: trig functions (sin/cos/tan), sqrt, hypot, basic arithmetic
- Macro substitution happens before coordinate parsing

**Text Handling (Lines ~950-1035, ~1155-1319)**
- Font size mapping: TikZ `\tiny` → GeoGebra `size=-6`, etc.
- Node positioning: parses `above`, `below`, `left`, `right`, `midway`, `pos=0.5`, etc.
- Matrix/legend parsing: extracts text from TikZ matrix environments, creates bordered box if `draw` option present
- LaTeX cleanup: removes `\contour`, `\textcolor`, preserves math mode

## Key Implementation Details

### MathJax Rendering Fix (tikz-draw.html)

The most complex part of the codebase is the MathJax-to-canvas pipeline. The critical issue was that MathJax SVGs use `<use>` elements referencing glyphs in a global cache. When cloning an SVG for rendering, those references break.

**Solution** (Lines ~1300-1350):
```javascript
// Find the global MathJax cache
const globalCache = document.querySelector('#MJX-SVG-global-cache defs');
// Clone the SVG
const clonedSvg = svgElement.cloneNode(true);
// Inline the global cache into the cloned SVG
if (globalCache) {
  let defs = clonedSvg.querySelector('defs');
  if (!defs) {
    defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    clonedSvg.insertBefore(defs, clonedSvg.firstChild);
  }
  // Copy all cache definitions
  for (const child of globalCache.children) {
    defs.appendChild(child.cloneNode(true));
  }
}
```

### GeoGebra Arc Generation (tikz2ggb.py)

GeoGebra doesn't support simple arc(start:end:radius) syntax. Must create auxiliary elements:

**Solution** (Lines ~220-303):
```python
# 1. Create hidden center point
# 2. Create hidden point on circle for Circle() command
# 3. Create Circle using center + point on circle
# 4. Create hidden start point at start_angle
# 5. Create hidden end point at end_angle
# 6. Create Arc using: Arc(<Circle>, <StartPoint>, <EndPoint>)
```

### Object Ordering and Reordering (tikz-draw.html)

Objects are stored in creation order in `app.objects[]` array. The object list UI allows drag-and-drop reordering which directly modifies this array order (Lines ~3800-3900).

**Compound Object Hierarchy**:
- Lines/vectors can have embedded labels (`this.nodes[]`)
- Object list shows expandable/collapsible tree: `▸ line_1` expands to show `(A)`, `segment`, `"label"`, `(B)`
- Clicking subobjects selects them and shows appropriate properties panel

### Save/Load Implementation (tikz-draw.html)

**Critical**: JavaScript class instances don't serialize well with `JSON.stringify()`. The `...obj` spread operator doesn't capture all properties reliably.

**Solution** (Lines ~4150-4250):
```javascript
function serializeObject(obj) {
  // Explicitly enumerate ALL properties for each object type
  if (obj.type === 'TikZCoordinate') {
    return {
      type: obj.type,
      id: obj.id,
      x: obj.x,
      y: obj.y,
      name: obj.name,
      showPoint: obj.showPoint,
      // ... list every property explicitly
    };
  }
  // Repeat for each object type
}
```

## Common Patterns

### Adding a New Tool to tikz-draw.html

1. Add tool button in toolbar HTML (~line 100)
2. Add keyboard shortcut in `setupKeyboardShortcuts()` (~line 3600)
3. Implement `handle{Tool}Click()` function (~line 2100)
4. Add case in main `handleCanvasClick()` switch statement (~line 2000)
5. Update properties panel in `updatePropertiesPanel()` (~line 2900)

### Adding a New TikZ Element Type to tikz2ggb.py

1. Create `GGB{ElementName}` dataclass with `to_xml()` method (~line 125)
2. Add parsing logic in `_parse_draw_command()` or create new `_parse_{element}_command()` (~line 723)
3. Update element counter in `_get_unique_name()` (~line 400)
4. Ensure points are created before elements that reference them (~line 1372)

### Handling TikZ Macros and Calculations

Both `tikz2ggb.py` and `tikz2view.py` need to handle TikZ's `\def` macros:
- Parse macro definitions in first pass
- Expand macros recursively before evaluating expressions
- Use safe `eval()` with restricted namespace for security
- Handle TikZ-specific functions: `veclen`, trig with degrees, etc.

## Testing

### Testing tikz-draw.html

1. Open in browser
2. Test each tool: Point (P), Line (L), Vector (A), Circle (C), Arc (R), Rectangle (T), Label (B), Path (/), Bezier (~), Grid (#)
3. Test LaTeX labels: `$\alpha + \beta = \gamma$`
4. Test embedded labels on lines
5. Test save/load with a complex diagram
6. Test TikZ export - copy to LaTeX document and compile

### Testing tikz2ggb.py

```bash
# Test with sample file
python tikz2ggb.py cmb.tex --verbose

# Open output in GeoGebra to verify:
# - All points are positioned correctly
# - Arcs render properly
# - Text labels appear
# - Legend box is drawn
```

## Known Limitations

### tikz-draw.html
- TikZ import (Import button, `importTikZ`/`TikZImporter`) is a port of tikz2view.py; change both
  together and regenerate the goldens with `python3 tests/tikz2view/test_tikz2view.py --update`
  (tests/tikz-import.html checks the JS port against them)
- Undo/redo keeps the last 50 snapshots (`maxHistory`) in memory only; history is lost on reload
- No layer support beyond object ordering
- MathJax requires internet connection (loaded from CDN)

### tikz2ggb.py
- Text labels and matrix environments don't translate perfectly (GeoGebra handles text differently)
- Only supports subset of TikZ: coordinates, lines, arcs, circles, points, basic colors, basic styling
- Complex calc library expressions may not evaluate correctly
- Does not support: curves with `..`, `to[out=,in=]`, decorations, patterns, advanced transformations

### tikz2view.py
- Converts everything tikz-draw exports: round trip (export → convert → load → export) is
  exact, checked by `python -m unittest discover -s tests/tikz2view` against
  `tests/tikz2view/editor-export.tex`. Keep it in step when the exporter changes.
- Fills are rebuilt as `curveLoops` by matching each outline piece to an imported object's
  primitive (mirrors `fillPrimitivesFor`), and are built after the whole picture is read
  because the editor writes fills before their boundary shapes.
- Arithmetic uses a whitelist `ast` evaluator (never `eval`); simple `\def`/`\newcommand`/
  `\pgfmathsetmacro` macros are expanded.
- Not supported (reported as warnings): `\foreach`, scope transforms, `to[out,in]`
  (imported straight), `plot`/`edge`/decorations, node borders, elliptical arcs outside fills.
