"""Bundle index.html and everything in assets/ into one portable .html file.

Claude Artifacts (and anywhere else that won't serve a sibling assets/ folder)
need a single file, so every local src= becomes a data: URI. Two more things
happen for the Artifact host specifically: the <html>/<head>/<body> shell comes
off, because the host supplies its own, and the Fontshare <link> goes with it,
because the host CSP only admits Google Fonts. Satoshi then falls back to Plus
Jakarta Sans, which is what the fallback stack is there for.

    python3 build_artifact.py     ->  dist/magpie-landing.html
"""

import base64
import mimetypes
import re
from pathlib import Path

level0 = Path(__file__).resolve().parent          # website/
assets = level0 / "assets"
out = level0 / "dist" / "magpie-landing.html"

DROP = set()   # everything in assets/ is referenced by the page


def data_uri(name):
    path = assets / name
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blob = base64.b64encode(path.read_bytes()).decode()
    print(f"  inlined {name:24s} {path.stat().st_size/1024:7.0f} KB -> {len(blob)/1024:7.0f} KB")
    return f"data:{mime};base64,{blob}"


html = (level0 / "index.html").read_text()

print("bundling:")
for name in sorted(p.name for p in assets.iterdir()):
    if name in DROP:
        print(f"  skipped {name}")
        continue
    html = html.replace(f"assets/{name}", data_uri(name))

# nothing local should be left pointing at a path
leftovers = re.findall(r'(?:src|href)="(?!https?:|#|data:)([^"]+)"', html)
if leftovers:
    raise SystemExit(f"still referencing local files: {leftovers}")

# Fontshare is blocked by the Artifact CSP, so drop the link rather than let it
# fail noisily; the fallback stack already names Plus Jakarta Sans
html = re.sub(r'<link rel="stylesheet" href="https://api\.fontshare\.com[^>]*>\n?', "", html)

# the host wraps whatever we hand it in its own doctype/head/body
head = html[html.index("<title>"):html.index("</head>")]
body = html[html.index("<body>") + len("<body>"):html.index("</body>")]
html = head.rstrip() + "\n" + body

out.parent.mkdir(exist_ok=True)
out.write_text(html)
print(f"\nwrote {out}, {out.stat().st_size/1024/1024:.2f} MB")
print("next: publish dist/magpie-landing.html as an Artifact")
