"""Resume text extraction — DOCX and PDF to plain text."""

from __future__ import annotations

from pathlib import Path


def extract_docx_text(path: Path) -> str:
    """Extract text from a .docx file."""
    try:
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except ImportError:
        raise RuntimeError("python-docx not installed. Run: pip install python-docx")


def extract_pdf_text(path: Path) -> str:
    """Extract text from a .pdf file."""
    try:
        import pymupdf as fitz
        doc = fitz.open(str(path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts)
    except ImportError:
        pass

    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except ImportError:
        raise RuntimeError("No PDF library installed. Run: pip install pymupdf or pypdf")
