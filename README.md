# TikZ Draw

A browser-based visual editor for creating TikZ diagrams. Draw geometric shapes, add LaTeX labels, and export clean TikZ code for use in LaTeX documents.

![TikZ Draw Screenshot](screenshot.png)

## Features

- **Visual Drawing Tools**: Point, Line, Vector, Circle, Arc, Rectangle, Path, Bézier Curve, Label, and Grid
- **LaTeX Support**: Full MathJax rendering for labels and annotations
- **Clean TikZ Export**: Generates well-formatted, readable TikZ code
- **Project Save/Load**: Save your work as JSON and continue later
- **Customizable Styling**: Colors, line styles, thicknesses, arrow types, and more
- **Snap to Grid**: Configurable grid snapping for precise positioning
- **Pan & Zoom**: Navigate large diagrams easily

## Getting Started

Simply open `tikz-draw.html` in a modern web browser. No installation or server required.

```bash
# Clone the repository
git clone https://github.com/yourusername/tikz-draw.git

# Open in browser
open tikz-draw.html
# or
xdg-open tikz-draw.html  # Linux
start tikz-draw.html      # Windows
```

## Tools

| Tool | Shortcut | Description |
|------|----------|-------------|
| Select | V | Select and move objects |
| Point | P | Create coordinate points |
| Line | L | Draw line segments between points |
| Vector | A | Draw arrows/vectors between points |
| Circle | C | Draw circles (click center, drag radius) |
| Arc | R | Draw circular arcs |
| Rectangle | T | Draw rectangles |
| Label | B | Add text/LaTeX labels at points |
| Path | / | Draw multi-point paths |
| Curve | ~ | Draw Bézier curves |
| Grid | # | Add a coordinate grid |

## Basic Workflow

1. **Create Points**: Select the Point tool and click on the canvas to place coordinate points. Each point gets a unique name (A, B, C, etc.)

2. **Draw Shapes**: Use Line, Vector, Circle, or other tools. Most shapes reference existing points by name.

3. **Add Labels**: Use the Label tool to add text or LaTeX math at any point. Labels support full LaTeX syntax: `$\frac{a}{b}$`, `$\alpha + \beta$`, etc.

4. **Style Objects**: Select any object to edit its properties in the right panel - colors, line styles, thickness, etc.

5. **Export TikZ**: Click "Export TikZ" to generate LaTeX code you can copy into your document.

## Navigation

- **Pan**: Click and drag on empty canvas, or use arrow keys
- **Zoom**: Mouse wheel, or use +/- buttons in the status bar
- **Snap**: Adjust grid snap size in the status bar (click the snap value)

## Properties Panel

Select any object to view and edit its properties:

- **Points**: Position (x, y), name, visibility, color, label for export
- **Lines/Vectors**: Start/end points, color, thickness, line style, embedded labels
- **Circles**: Center, radius, stroke color, fill color, opacity
- **Labels**: Position, text content, anchor position, color

## Embedded Labels

Lines and vectors can have labels attached directly to them:

1. Select a line or vector
2. Click "+ Add Label" in the properties panel
3. Click on the label entry to edit: text, position along the line (0-1), anchor, font size, color

## Line Styles

Available line styles for all stroke objects:
- solid, dashed, dotted
- dashdotted, dashdotdotted
- loosely dashed, densely dashed
- loosely dotted, densely dotted
- loosely dashdotted, densely dashdotted

## Arrow Types (Vectors)

- Stealth, latex (arrow head styles)
- Start, end, or both ends
- Adjustable arrow size

## LaTeX Labels

Labels support full LaTeX math notation via MathJax:

```latex
$\alpha$                           % Greek letters
$\frac{a}{b}$                      % Fractions
$\sqrt{x^2 + y^2}$                 % Square roots
$\int_0^\infty e^{-x} dx$          % Integrals
$\left[\frac{a}{b}\right]$         % Auto-sized brackets
```

## Export Format

The exported TikZ code is clean and well-organized:

```latex
\begin{tikzpicture}

% Coordinates
\coordinate (A) at (0, 0);
\coordinate (B) at (3, 4);
\coordinate (C) at (6, 0);

% Visible Points
\fill (A) circle (2pt);
\fill (B) circle (2pt);

% Segments
\draw (A) -- (B);
\draw[thick, dashed, red] (B) -- (C);

% Vectors
\draw[-Stealth] (A) -- (C);

% Labels
\node[above] at (B) {$P$};

\end{tikzpicture}
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| V | Select tool |
| P | Point tool |
| L | Line tool |
| A | Vector (Arrow) tool |
| C | Circle tool |
| R | Arc tool |
| T | Rectangle tool |
| B | Label tool |
| / | Path tool |
| ~ | Bézier Curve tool |
| # | Grid tool |
| Delete/Backspace | Delete selected object |
| Arrow keys | Pan the canvas |
| +/- | Zoom in/out |
| Escape | Cancel current operation |

## Project Files

Save your work as JSON files to continue editing later:

- **Save**: Click "Save" to download a `.json` file
- **Open**: Click "Open" to load a previously saved project

Project files preserve all objects, positions, styles, and view settings.

## Tips

- **Naming Points**: Points are automatically named A, B, C... You can rename them in the properties panel.
- **Precise Positioning**: Use the coordinate inputs in the properties panel for exact values.
- **Reordering**: Drag objects in the Objects list to change their draw order.
- **Colors**: Use the color picker or enter custom hex colors. TikZ color names (red, blue, etc.) are supported.
- **Point Labels**: Points can have both an editor name (shown in gray) and an export label (rendered in LaTeX).

## Browser Compatibility

Works in modern browsers with ES6+ support:
- Chrome/Chromium
- Firefox
- Safari
- Edge

Requires JavaScript enabled and internet connection (for MathJax CDN).

## License

MIT License - feel free to use, modify, and distribute.

## Contributing

Contributions welcome! Please open an issue or pull request on GitHub.
