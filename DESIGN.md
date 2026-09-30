# DocPixly — design plan

Subject: a tool that turns paper (scans, photos, PDFs) into structured, editable data,
for students/offices/colleges in Nepal. The job is precision and trust, not persuasion —
lead with the working tool, not a marketing hero.

## Color
- `--paper: #ECEEE7`   cool ledger-paper grey-green (not the cliché warm cream)
- `--ink:   #1F2A44`   deep ink navy — primary text, headings, active states
- `--rule:  #C9CFC5`   hairline rule / grid-line grey
- `--stamp: #A23B34`   muted brick-red — the one accent color, used like a rubber stamp:
                       sparingly, for the primary action and "official" confirmations
- `--flag:  #B8862E`   muted amber — low-confidence cell flags only
- `--ok:    #3F6B4F`   muted green — success / found states
- `--surface: #FFFFFF` cards / panels on top of the paper background

## Type
Two families, clearly distinct roles (not decoration):
- **IBM Plex Sans** — all UI chrome: headings, buttons, labels, body copy.
- **IBM Plex Mono** — anything that IS extracted data: table cells, field values,
  file names, confidence numbers. The monospace face is the visual signal that
  "this text came off the page," not typed by a person.

## Layout
Single-purpose tool, not a marketing site. No nav bar, no hero image.
```
┌───────────────────────────────────────────────┐
│  DocPixly            turn scans into files      slim header, wordmark + one-liner
├───────────────────────────────────────────────┤
│  ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐    │
│  ╎  drop files here — corner registration ╎    │  upload tray: dashed + corner
│  ╎  marks like a scanner bed              ╎    │  marks, grounded in "scan" idea
│  └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘    │
│  language / page-range options (inline, plain) │
├───────────────────────────────────────────────┤
│ 01 Upload — 02 Read — 03 Review — 04 Download   real 4-step sequence (numbering
├───────────┬─────────────────────┬─────────────┤ is justified: it IS a process)
│ page      │ extracted blocks /  │  downloads   │
│ thumbs    │ editable tables     │  DOCX·XLSX·  │
│ (rail)    │ (center, wide)      │  CSV·TXT     │
└───────────┴─────────────────────┴─────────────┘
```
Left-aligned throughout; center column is the widest (it's the content people edit).

## Principles
- The upload tray and step rail are the only place structure is "decorated" (registration
  marks, numbering) — both grounded in the literal subject (a scanner bed, a workflow).
  Everything else is quiet: flat surfaces, hairline borders, no drop shadows, no
  rounded-card kit.
- Table cells the pipeline wasn't sure about are flagged with the amber underline, not a
  wall of caveats — the person can just look at the page thumbnail to check.
- Copy is plain and active: "Download Word", not "Export Document", errors say what
  happened and what to try next.
