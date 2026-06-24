"""Resume export — convert markdown to PDF and DOCX.

Uses markdown -> HTML -> PDF (via weasyprint) and markdown -> DOCX (via python-docx).
These are optional dependencies — if not installed, export gracefully degrades.
"""

from __future__ import annotations

from pathlib import Path


def export_pdf(markdown_path: Path, output_path: Path | None = None) -> Path | None:
    """Export a markdown resume to PDF.

    Returns the path to the PDF, or None if export failed (missing deps).
    """
    try:
        import markdown
        import weasyprint
    except ImportError:
        return None

    if not markdown_path.exists():
        return None

    output_path = output_path or markdown_path.with_suffix(".pdf")
    md_text = markdown_path.read_text()

    # Convert markdown to HTML
    html_body = markdown.markdown(md_text, extensions=["extra", "tables"])

    # Wrap in a simple HTML document with print-friendly styling
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #222; max-width: 800px; margin: 0 auto; padding: 20px; }}
  h1 {{ font-size: 18pt; margin-bottom: 4pt; }}
  h2 {{ font-size: 13pt; margin-top: 14pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }}
  h3 {{ font-size: 11pt; margin-top: 10pt; }}
  a {{ color: #222; text-decoration: none; }}
  ul {{ margin-top: 4pt; }}
  li {{ margin-bottom: 2pt; }}
  @page {{ margin: 0.5in; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    weasyprint.HTML(string=html).write_pdf(str(output_path))
    return output_path


def export_docx(markdown_path: Path, output_path: Path | None = None) -> Path | None:
    """Export a markdown resume to DOCX.

    Returns the path to the DOCX, or None if export failed (missing deps).
    """
    try:
        from docx import Document
        from docx.shared import Pt, Inches
    except ImportError:
        return None

    if not markdown_path.exists():
        return None

    output_path = output_path or markdown_path.with_suffix(".docx")
    md_text = markdown_path.read_text()

    doc = Document()

    # Simple markdown parsing — headings, bullet points, paragraphs
    for line in md_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.startswith("* ") and not line.endswith("*"):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            # Remove markdown bold/italic markers
            clean = line.replace("**", "").replace("*", "").replace("__", "")
            doc.add_paragraph(clean)

    doc.save(str(output_path))
    return output_path
