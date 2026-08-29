# Magpie landing page

A single self-contained page: `index.html` plus `assets/`. No build step, no
framework, no npm. Open it in a browser and it works.

```
website/
  index.html            everything, markup, CSS and JS
  assets/
    flock.webp          hero flock, animated, real alpha, flies left to right
    magpie-mark.png     the logo, trimmed and downscaled
    magpie-mark-dark.png  the light-on-dark variant, used by the dark theme
    og.jpg              1200x630 share card, regenerate from a hero screenshot
  build_artifact.py     bundles the whole thing into one portable .html
```

The page is roughly 320 KB all in, so it loads in one paint on a slow
connection.

## Where the design came from

Colour and layout follow usefenn.com: accent `#0099FF`, ink `#121212`, paper
`#FAFAFA`, and their card, pill and border geometry. Pricing, testimonials and
"featured in" are intentionally absent. Four deliberate departures:

- **Radley** carries every label, eyebrow, table header and file-meta line.
  Radley only ships oldstyle figures, which turn `v0.1.0` into `vo.1.o`, so a
  `@font-face` block called `LiningFigures` borrows digits from whichever
  Times-metric serif the machine already has. Do not remove it.
- **Permanent Marker** for the handwritten asides.
- **SUSE Mono** survives in exactly two places: the app mock-ups and anything
  that is literally code, a shell command or a keycap. It is the typeface Magpie
  itself ships with, so the mock and the product speak the same voice.
- **Headings run at weight 400**, not 700, and true black is reserved for the
  uppercase label role via `--ink-strong`.

Satoshi is loaded from Fontshare for the display face; Plus Jakarta Sans from
Google Fonts is the fallback, so the page still looks right wherever Fontshare
is blocked.

House rules for the copy: **no em dashes, no middot separators.** Commas and
full stops only.

## The demo section

There is no video. The demo is a live recreation of the app, built from the same
markup as the hero mock, that cycles through three questions: a college essay, a
flight receipt and a bank statement. It types the question, shows a reading
state, then reveals the answer, the cited source and the highlighted line in the
preview page.

Everything it says lives in the `DEMOS` array near the bottom of `index.html`.
To change a question, edit that array; nothing else needs to move. Each entry
needs `tag`, `scan`, `q`, `a`, `file`, `path`, `snip`, `page` and `hit`. Adding a
fourth entry also means adding a fourth `.demo-tab` button.

The loop only runs while the section is on screen, and under
`prefers-reduced-motion` it renders the first question finished and stays put.
The real screen capture still lives at `docs/assets/demo.mp4` and the caption
links to it.

## Editing

Every download URL, file size and version string is written literally in
`index.html`. When a new release ships, search for `v0.1.0-beta.4` and update
the four asset links, the three sizes in the `.dl-meta` blocks, and the eyebrow
above **Get Magpie**.

## Running it locally

```bash
cd website
python3 -m http.server 8000
# then open http://localhost:8000
```

Opening `index.html` straight off disk works too, but a server is closer to
production.

## Deploying

It is static, so anything that serves files will do.

**GitHub Pages.** Settings, then Pages, then *Deploy from a branch*, picking
`main` and `/website`. To publish at the domain root instead, move the contents
of `website/` into a `gh-pages` branch.

**Netlify, Vercel, Cloudflare Pages.** Point the project at this repo, set the
publish directory to `website`, and leave the build command empty.
