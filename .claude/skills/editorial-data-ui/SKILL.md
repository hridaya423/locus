---
name: editorial-data-ui
description: The visual and interaction language of locus (UoSDDNB/omics-agent web app), written down so new projects can reuse it - a warm-paper editorial look for scientific data tools, with exact colour tokens, type scale, component recipes, navigation rules and copy rules. USE WHEN starting or extending a web UI for a data, search or science tool that should look like locus, when asked to "keep the locus design", "same design as locus", "editorial data UI", or when adding a page or component to a project that already uses this system and you need its conventions. Not for slide decks or charts in other media (use the dataviz skill for charts).
---

# Editorial data UI (reverse-engineered from locus)

A quiet, paper-like interface where the data is the loudest thing on the page. Reference implementation: `web/` in
UoSDDNB/omics-agent (Next.js App Router, Tailwind v4, shadcn primitives, framer-motion, lucide icons). Before
inventing anything, open `web/app/globals.css`, `web/components/page-kit.tsx`, `web/components/logo.tsx` and one
finished page (`web/components/dataset.tsx`) and copy from them.

## Principles

1. **Paper, ink, one signal.** Warm off-white ground, near-black ink, a single orange signal colour used sparingly for
   the thing that matters (cases, the active state, the logo's dot). Everything else is a shade of the paper.
2. **Rules, not boxes.** Sections are separated by thin hairlines (`border-rule`), not cards with shadows. Cards
   (`bg-card`) appear only for inputs and floating panels.
3. **Three typefaces, three jobs.** Serif for titles and the wordmark, a tight grotesque for reading, mono for labels,
   identifiers and numbers.
4. **Numbers line up.** Every count, date and identifier uses tabular figures.
5. **Say where a fact came from.** A number on screen carries its provenance in small muted text; anything a model
   wrote is labelled as model-written; missing information says "not stated" or "unknown", never a guess.
6. **Motion is a courtesy.** Short, eased, and disabled under `prefers-reduced-motion`.

## Tokens (light; a matching `.dark` set exists in globals.css)

| Token | Value | Use |
|---|---|---|
| `--background` | `#EFEBE3` | page ground (warm paper) |
| `--foreground` / `--primary` | `#111110` | ink, primary buttons |
| `--card` / `--popover` | `#F7F5F0` | inputs, panels |
| `--secondary` / `--muted` / `--accent` | `#E6E1D7` | quiet fills |
| `--muted-foreground` | `#6E6860` | secondary text, muted links |
| `--border` / `--rule` | `#D9D3C7` | hairlines, link underlines |
| `--signal` | `#E8461A` | the one accent: cases, active, logo dot |
| `--control` | `#2E5B4F` | the counterpart to signal: controls |
| `--mark` | `#F2E3A0` | highlighter for matched words in source text |
| `--destructive` | `#B23A2A` | errors only |
| `--warn` / `--warn-soft` | `#3D3935` / `#E3DED4` | cautions (design warnings), never red |
| `--radius` | `0.5rem` | small; corners are barely rounded |

Charts take `--chart-1..5` (signal, control, ink, two greys). Case/control colour is semantic and identical on every
chart, table and badge of a page.

## Type

- Fonts (via `next/font/google`): **Instrument Serif** 400 → `font-display`; **Inter Tight** 400/500/600 → body;
  **JetBrains Mono** 400/500 → `font-mono`.
- Headings: `h1–h4 { text-wrap: balance; letter-spacing: -0.02em }`. Page titles are serif at 34–48 px; section
  headings use `Heading` from page-kit (serif 28 px, with an optional mono count beside it).
- Body copy 13–16 px; most UI text is `text-[13px]`, metadata `text-[12px]`.
- **`.label`**: mono, 11.5 px, letter-spacing .05em, uppercase. Used for field names (DATA TYPE, START WITH), table
  headers and small stats captions. Never use it for sentences.
- **`.tabular`** on every number; identifiers (`GSE…`, `PXD…`) in `font-mono`.

## Component recipes

- **Links:** `LINK` = underline in the rule colour, offset 4, darkening on hover. `MUTED_LINK` = the same in
  muted-foreground, darkening to ink on hover. No blue links anywhere.
- **Header (every page except home):** a `<nav>` row: the wordmark at `text-[30px]` linking home on the left, then
  muted back links (`ArrowLeft` / `ChevronLeft` at `size-3.5` + `text-[13px]` + `MUTED_LINK`), and outbound links on the
  right with `ArrowUpRight`. Gap 5 between items; long labels `truncate`.
- **Home:** the wordmark large (`text-[88px] sm:text-[120px]`) centred above a one-line promise in two tones
  ("Ask in plain English." in ink, the second clause muted), then the input. Nothing else competes.
- **Input:** a single large field on `bg-card` with a hairline border, the submit button a dark square inside it;
  example text is a real question, not "Search…".
- **Fact strips:** a row of cells split by vertical hairlines, each a `.label` over a value (DATA TYPE / ORGANISM /
  SAMPLES / FILES). Unknown values read "not stated".
- **Chips:** plain bordered pills for what was searched; filled muted pills for filters.
- **Tables:** hairline rows, mono uppercase headers, numbers right-aligned and tabular, case counts in signal and
  control counts in control.
- **Callout quote:** a left border in ink with muted text, for domain notes and quoted evidence.
- **Badges:** small dark pill (`bg-foreground text-background`) for structural facts ("2 records of one study").
- **Logo:** a wordmark whose "o" is a reticle (ring + signal dot) that spins while a search runs; keep the hover
  animation subtle and skipped under reduced motion.

## Navigation rules

- **The logo always goes home**, from every page, including the results view. Home is a plain `/`.
- **Results have their own address** (`/?q=<question>`), so a link, a reload and browser Back all reopen them. Save
  the last results for the tab (sessionStorage) and restore them only when the address asks for that question;
  never restore on plain `/`, or the logo stops meaning home.
- **"Results for …" is a separate link**, beside the logo, on every page reached from a search; it links to
  `/?q=<question>` (not `history.back()`, which goes to the previous page, not the results) and restores the row the
  reader left from.
- Clearing state when going home: the page component may stay mounted when only the query changes, so reset the
  search state in the home link's click handler.

## Copy rules

- Plain words, sentence case, no exclamation marks, no marketing adjectives.
- Every number says where it came from in small muted text ("88 cases and 109 controls, counted from 210 SDRF
  samples").
- Model output is labelled ("Written by the model from the numbers above"); a check that a model did not invent a
  number is better than a disclaimer.
- Missing is "not stated" / "unknown"; a failed fetch says what failed in one sentence; a disabled control says why.
- Progress names real stages ("Understanding the question", "Searching 18 repositories", "Reading sample records").

## Motion

- Entrances: `animate-in fade-in slide-in-from-bottom-2 duration-700` for the home hero; 150–200 ms colour transitions
  on links and buttons.
- Wrap the app in `<MotionConfig reducedMotion="user">` and keep the global reduced-motion CSS override.
- View transitions for the search bar moving from home to results (`view-transition-name: search-bar`, .55 s,
  `cubic-bezier(.16,1,.3,1)`).

## Accessibility

- Visible focus: `outline: 2px solid var(--ring); outline-offset: 3px` on links and buttons.
- Icon-only controls get `aria-label`; decorative icons `aria-hidden`.
- Contrast: muted text is `#6E6860` on `#EFEBE3`; do not go lighter for anything a reader needs.

## Checklist for a new page or project

1. Copy `globals.css` tokens, the three fonts, `page-kit.tsx` and the wordmark.
2. Header row with the home wordmark and, if reached from a search, the "Results for …" link.
3. One serif title, a fact strip, then sections under `Heading`, separated by hairlines.
4. Every number tabular and sourced; every unknown says so.
5. Check light and dark, a 390 px phone width, keyboard focus, and reduced motion.
