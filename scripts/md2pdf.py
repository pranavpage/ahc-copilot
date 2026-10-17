"""Render a markdown file (with mermaid diagrams) to PDF with headless Chrome.

    uv run --with markdown --with playwright python scripts/md2pdf.py SUBMISSION.md SUBMISSION.pdf

Needs Google Chrome and internet (mermaid.js comes from a CDN).
"""

import html
import re
import sys
import tempfile
from pathlib import Path
import markdown
from playwright.sync_api import sync_playwright

src, out = Path(sys.argv[1]), Path(sys.argv[2])
text = src.read_text()
# mermaid blocks -> <pre class="mermaid"> (kept out of the markdown parser)
blocks = []
def keep(m):
    blocks.append(m.group(1)); return f"\n\nMERMAID{len(blocks)-1}\n\n"
text = re.sub(r"```mermaid\n(.*?)```", keep, text, flags=re.S)
# a list right after a paragraph line needs a blank line for Python-Markdown (GitHub does not)
lines, prev = [], ""
for line in text.split("\n"):
    is_item = re.match(r"\s*(?:[-*]|\d+\.) ", line)
    prev_item = re.match(r"\s*(?:[-*]|\d+\.) ", prev) or prev.startswith("  ")
    if is_item and prev.strip() and not prev_item and not prev.startswith("|"):
        lines.append("")
    lines.append(line); prev = line
text = "\n".join(lines)
body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
for i, b in enumerate(blocks):
    body = body.replace(f"<p>MERMAID{i}</p>", f'<pre class="mermaid">{html.escape(b)}</pre>')
page = f"""<!doctype html><html><head><meta charset="utf-8">
<style>
 @page {{ size: A4; margin: 14mm 12mm; }}
 body {{ font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif; font-size: 9.5pt; line-height: 1.4; color: #1a1a1a; }}
 h1 {{ font-size: 17pt; margin: 0 0 6px; }} h2 {{ font-size: 13pt; border-bottom: 1px solid #ddd; padding-bottom: 3px; margin-top: 14px; }}
 h3 {{ font-size: 11.5pt; margin: 12px 0 4px; }} h4 {{ font-size: 10pt; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 7.6pt; margin: 6px 0 8px; page-break-inside: auto; }}
 tr {{ page-break-inside: avoid; }}
 th, td {{ border: 1px solid #d0d0d0; padding: 2px 4px; text-align: left; vertical-align: top; }}
 th {{ background: #f3f3f3; }}
 code {{ font-family: Menlo, monospace; font-size: 8pt; background: #f4f4f4; padding: 0 2px; border-radius: 2px; }}
 blockquote {{ margin: 4px 0; padding: 2px 10px; border-left: 3px solid #c8d3e6; color: #333; background: #f8fafd; }}
 blockquote p {{ margin: 3px 0; }}
 pre.mermaid {{ text-align: center; margin: 6px 0; }} pre.mermaid svg {{ width: 100% !important; max-width: 100% !important; height: auto; max-height: 560px; }}
 p, li {{ margin: 3px 0; }} ul, ol {{ margin: 3px 0; padding-left: 18px; }}
 a {{ color: #1a56b0; text-decoration: none; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
</head><body>{body}
<script>mermaid.initialize({{startOnLoad:false, theme:'neutral', flowchart:{{htmlLabels:true}}}});
mermaid.run().then(()=>{{document.body.dataset.done='1'}}).catch(e=>{{document.body.dataset.done='err:'+e}});</script>
</body></html>"""
html_path = Path(tempfile.mkdtemp()) / "page.html"
html_path.write_text(page)
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page()
    pg.goto(html_path.resolve().as_uri())
    pg.wait_for_function("document.body.dataset.done", timeout=60000)
    print("mermaid:", pg.evaluate("document.body.dataset.done"))
    pg.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
    b.close()
print(out)
