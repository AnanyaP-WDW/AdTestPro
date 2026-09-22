"""PDF export via WeasyPrint.

Optional dependency: if WeasyPrint (or its system libraries) is unavailable the
app keeps working and the PDF route degrades to 503, with the download button
hidden. Rendering is fully offline — all CSS is inlined and images are data URIs.
"""

from __future__ import annotations

from typing import Optional


def engine_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


def render_pdf(html: str, base_url: Optional[str] = None) -> bytes:
    """Render a self-contained HTML string to PDF bytes."""
    from weasyprint import HTML

    return HTML(string=html, base_url=base_url or "").write_pdf()
