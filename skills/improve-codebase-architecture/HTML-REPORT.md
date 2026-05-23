# HTML Report Format

Adapted from Matt Pocock's skills repo:
[HTML-REPORT.md](https://github.com/mattpocock/skills/blob/main/skills/engineering/improve-codebase-architecture/HTML-REPORT.md)

The architectural review is rendered as a single self-contained HTML file in the OS temp directory. Tailwind and Mermaid both come from CDNs. Mermaid handles graph-shaped diagrams reliably, while hand-built divs and inline SVG handle more editorial visuals such as mass diagrams and cross-sections. Mix the two. Do not lean on Mermaid for everything.

## Scaffold

Use a simple standalone HTML document with:

- Tailwind loaded from the CDN
- Mermaid loaded from the CDN ESM build
- A small custom CSS layer for seam lines, leakage arrows, and deep module treatments
- A main layout containing a header, candidate section, and top recommendation section

Example structure:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Architecture review - {{repo name}}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script type="module">
      import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
      mermaid.initialize({ startOnLoad: true, theme: "neutral", securityLevel: "loose" });
    </script>
    <style>
      .seam { stroke-dasharray: 4 4; }
      .leak { stroke: #dc2626; }
      .deep { background: linear-gradient(135deg, #0f172a, #1e293b); }
    </style>
  </head>
  <body class="bg-stone-50 text-slate-900 font-sans">
    <main class="max-w-5xl mx-auto px-6 py-12 space-y-12">
      <header>...</header>
      <section id="candidates" class="space-y-10">...</section>
      <section id="top-recommendation">...</section>
    </main>
  </body>
</html>
```

## Header

Include the repo name, date, and a compact legend:

- Solid box = module
- Dashed line = seam
- Red arrow = leakage
- Thick dark box = deep module

Do not add an introduction paragraph. Go straight into the candidates.

## Candidate card

The diagrams should carry most of the weight. Prose should stay sparse, plain, and use the glossary terms from [LANGUAGE.md](LANGUAGE.md).

Each candidate should render as one article with:

- Title: short, names the deepening
- Badge row: recommendation strength plus dependency category
- Files: monospaced list
- Before / After diagram: the centerpiece
- Problem: one sentence
- Solution: one sentence
- Wins: very short bullets
- ADR callout, if needed: one line in an amber-tinted box

If the diagram needs a paragraph to be understood, redraw the diagram instead.

## Diagram patterns

Pick the pattern that fits the candidate. Mix them so the report does not feel repetitive.

### Mermaid graph

Use Mermaid flowcharts or graphs when the point is dependency shape or call flow.

Good for:

- Dependency tangles
- Call graphs
- Sequence reductions

### Hand-built boxes and arrows

Use divs plus inline SVG when Mermaid fights the desired layout or when you want the after state to feel like a single thick deep module.

### Cross-section

Use stacked horizontal bands to show layered shallowness.

- Before: many thin layers doing very little
- After: one thicker band carrying the consolidated responsibility

### Mass diagram

Use paired rectangles to show interface size versus implementation size.

- Before: interface nearly as tall as implementation, meaning shallow
- After: interface short and implementation tall, meaning deep

### Call-graph collapse

- Before: tree of function calls
- After: same tree collapsed into one deeper module, with internal calls faded inside it

## Style guidance

- Lean editorial, not dashboard-like
- Use generous whitespace
- Optional serif headings can work well
- Use color sparingly: one accent, red for leakage, amber for warnings
- Keep diagrams around 320px tall for side-by-side readability
- Use small uppercase schematic labels inside diagrams
- Keep the report static aside from Mermaid rendering

## Top recommendation section

End with one larger card containing:

- Candidate name
- One sentence on why it should go first
- Anchor link to its card

## Tone

Use plain, concise English, but keep the architectural nouns and verbs aligned with [LANGUAGE.md](LANGUAGE.md).

Use exactly:

- module
- interface
- implementation
- depth
- deep
- shallow
- seam
- adapter
- leverage
- locality

Avoid substitutions such as:

- component, service, unit when you mean module
- API or signature when you mean interface
- boundary when you mean seam
- vague terms like "cleaner code" or "easier to maintain"
