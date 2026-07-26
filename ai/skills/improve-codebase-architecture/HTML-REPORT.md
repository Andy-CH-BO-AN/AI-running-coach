# HTML Report Format

The architectural review is rendered as a single 100% self-contained HTML file in the OS temp directory. All layout, typography, and visual diagrams are generated using embedded CSS and inline SVG/HTML elements. **No external CDN dependencies or third-party script tags are allowed**, ensuring full offline usability and compliance with local data privacy requirements.

## Scaffold

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Architecture review — {{repo name}}</title>
    <style>
      :root {
        --bg-main: #f8fafc;
        --text-main: #0f172a;
        --border-color: #e2e8f0;
        --seam-color: #64748b;
        --leak-color: #dc2626;
        --deep-bg: linear-gradient(135deg, #0f172a, #1e293b);
      }
      body { background-color: var(--bg-main); color: var(--text-main); font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 2rem; }
      .container { max-width: 64rem; margin: 0 auto; }
      .card { background: white; border: 1px solid var(--border-color); border-radius: 0.5rem; padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
      .seam { stroke-dasharray: 4 4; stroke: var(--seam-color); }
      .leak { stroke: var(--leak-color); stroke-width: 2px; }
      .deep-module { background: var(--deep-bg); color: white; border-radius: 0.5rem; padding: 1rem; }
      .badge-strong { background: #d1fae5; color: #065f46; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600; }
      .badge-exploring { background: #fef3c7; color: #92400e; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600; }
      .badge-speculative { background: #f1f5f9; color: #475569; padding: 0.25rem 0.5rem; border-radius: 0.25rem; font-size: 0.75rem; font-weight: 600; }
      .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
      .diagram-box { border: 1px solid var(--border-color); background: #f1f5f9; border-radius: 0.375rem; padding: 1rem; }
    </style>
  </head>
  <body>
    <main class="container">
      <header>...</header>
      <section id="candidates">...</section>
      <section id="top-recommendation">...</section>
    </main>
  </body>
</html>
```

## Header

Repo name, date, and a compact legend: solid box = module, dashed line = seam, red arrow = leakage, thick dark box = deep module. No introduction paragraph — straight into the candidates.

## Candidate card

The diagrams carry the weight. Prose is sparse, plain, and uses the glossary terms (from the `/codebase-design` skill) without ceremony.

Each candidate is one `<article>`:

- **Title** — short, names the deepening (e.g. "Collapse the Order intake pipeline").
- **Badge row** — recommendation strength (`Strong` = emerald, `Worth exploring` = amber, `Speculative` = slate), plus a tag for the dependency category (`in-process`, `local-substitutable`, `ports & adapters`, `mock`).
- **Files** — monospaced list (`font-family: monospace; font-size: 0.875rem`).
- **Before / After diagram** — the centrepiece. Two columns, side by side (`.grid-2`). See patterns below.
- **Problem** — one sentence. What hurts.
- **Solution** — one sentence. What changes.
- **Wins** — bullets, ≤6 words each. e.g. "Tests hit one interface", "Pricing logic stops leaking", "Delete 4 shallow wrappers".
- **ADR callout** (if applicable) — one line in an amber-tinted box.

No paragraphs of explanation. If the diagram needs a paragraph to be understood, redraw the diagram.

## Diagram patterns

Pick the pattern that fits the candidate. Mix them. Don't make every diagram look the same — variety is part of the point. All diagrams are built inline using SVG elements and HTML flex/grid containers.

### Inline SVG / HTML Box-and-Arrow Graph (Dependencies / Call Flow)

Use inline SVG `<svg>` with `<rect>`, `<path>`, and `<text>` elements, or nested HTML `<div>` blocks styled with borders and background colors.

```html
<div class="diagram-box">
  <svg width="100%" height="160" viewBox="0 0 400 160">
    <!-- Modules -->
    <rect x="20" y="20" width="100" height="40" rx="4" fill="#ffffff" stroke="#64748b" />
    <text x="70" y="45" text-anchor="middle" font-size="12">OrderHandler</text>

    <!-- Leak arrow -->
    <path d="M 120 40 L 220 40" stroke="#dc2626" stroke-width="2" stroke-dasharray="4 4" marker-end="url(#arrow-red)" />
    <text x="170" y="32" text-anchor="middle" font-size="10" fill="#dc2626">leak</text>
  </svg>
</div>
```

### Hand-built boxes-and-arrows

Modules as `<div>`s with borders and labels. Arrows as inline SVG `<line>` or `<path>` elements positioned over a relative container. Reach for this when you want the "after" diagram to feel like one thick-bordered deep module with greyed-out internals.

### Cross-section (good for layered shallowness)

Stack horizontal bands (`height: 3rem; border-left: 4px solid ...`) to show layers a call passes through. Before: 6 thin layers each doing nothing. After: 1 thick band labelled with the consolidated responsibility.

### Mass diagram (good for "interface as wide as implementation")

Two rectangles per module — one for interface surface area, one for implementation. Before: interface rectangle is nearly as tall as the implementation rectangle (shallow). After: interface rectangle is short, implementation rectangle is tall (deep).

### Call-graph collapse

Before: a tree of function calls rendered as nested boxes. After: the same tree collapsed into one box, with the now-internal calls shown faded inside it.

## Style guidance

- Lean editorial, not corporate-dashboard. Generous whitespace.
- Colour sparingly: one accent (emerald or indigo) plus red for leakage and amber for warnings.
- Keep diagrams ~320px tall so before/after sits comfortably side by side without scrolling.
- Use uppercase tracking for module labels inside diagrams — they should read as schematic, not as UI.
- **Zero external script or CSS tags**. The report is completely offline and self-contained.

## Top recommendation section

One larger card. Candidate name, one sentence on why, anchor link to its card. That's it.

## Tone

Plain English, concise — but the architectural nouns and verbs come straight from the `/codebase-design` skill. Concision is not an excuse to drift.

**Use exactly:** module, interface, implementation, depth, deep, shallow, seam, adapter, leverage, locality.

**Never substitute:** component, service, unit (for module) · API, signature (for interface) · boundary (for seam) · layer, wrapper (for module, when you mean module).

**Phrasings that fit the style:**

- "Order intake module is shallow — interface nearly matches the implementation."
- "Pricing leaks across the seam."
- "Deepen: one interface, one place to test."
- "Two adapters justify the seam: HTTP in prod, in-memory in tests."

**Wins bullets** name the gain in glossary terms: *"locality: bugs concentrate in one module"*, *"leverage: one interface, N call sites"*, *"interface shrinks; implementation absorbs the wrappers"*. Don't write *"easier to maintain"* or *"cleaner code"* — those terms aren't in the glossary and don't earn their place.

No hedging, no throat-clearing, no "it's worth noting that…". If a sentence could be a bullet, make it a bullet. If a bullet could be cut, cut it. If a term isn't in the `/codebase-design` glossary, reach for one that is before inventing a new one.
