from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PdfExportError(RuntimeError):
    pass


def _default_css_path() -> Path:
    return Path(__file__).parent / "assets" / "markdown.css"


def _run_pandoc(
    *,
    input_md: Path,
    output_pdf: Path,
    pdf_engine: str = "xelatex",
) -> None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise PdfExportError("pandoc not found in PATH")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        pandoc,
        str(input_md),
        "-o",
        str(output_pdf),
        "--pdf-engine",
        pdf_engine,
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise PdfExportError(
            "Pandoc PDF export failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}\n"
            "Tip: ensure a TeX engine is installed (MiKTeX/TeX Live) and the "
            f"pdf engine '{pdf_engine}' is available."
        )


def _md_to_html(md_text: str) -> str:
    try:
        import markdown2  # type: ignore

        return markdown2.markdown(
            md_text,
            extras=[
                "fenced-code-blocks",
                "tables",
                "strike",
                "task_list",
                "footnotes",
            ],
        )
    except Exception:
        pass

    try:
        import markdown  # type: ignore

        return markdown.markdown(
            md_text,
            extensions=[
                "fenced_code",
                "tables",
            ],
        )
    except Exception as exc:
        raise PdfExportError(
            "No Markdown-to-HTML backend available. Install one of:\n"
            "  - markdown2\n"
            "  - markdown\n"
            f"Import error: {exc}"
        ) from exc


def _run_weasyprint(
    *,
    input_md: Path,
    output_pdf: Path,
    css_path: Optional[Path] = None,
) -> None:
    try:
        from weasyprint import CSS, HTML  # type: ignore
    except Exception as exc:
        raise PdfExportError(
            "WeasyPrint is not installed (or missing system deps). "
            "Install weasyprint, or install pandoc + a TeX engine.\n"
            f"Import error: {exc}"
        ) from exc

    md_text = input_md.read_text(encoding="utf-8")
    body_html = _md_to_html(md_text)

    css_path = css_path or _default_css_path()
    css_text = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>{css_text}</style>
  </head>
  <body>
    <article class="markdown-body">
      {body_html}
    </article>
  </body>
</html>
"""

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(input_md.parent)).write_pdf(
        str(output_pdf),
        stylesheets=[CSS(string=css_text)] if css_text else None,
    )


def export_markdown_to_pdf(
    *,
    input_md: Path,
    output_pdf: Path,
    css_path: Optional[Path] = None,
    pandoc_pdf_engine: str = "xelatex",
) -> None:
    """
    Convert Markdown to PDF, preferring pandoc if available.
    """
    if not input_md.exists():
        raise FileNotFoundError(f"Markdown file not found: {input_md}")

    try:
        _run_pandoc(input_md=input_md, output_pdf=output_pdf, pdf_engine=pandoc_pdf_engine)
        logger.info("Exported PDF via pandoc: %s", output_pdf)
        return
    except PdfExportError as exc:
        logger.warning("Pandoc backend unavailable/failed: %s", exc)

    _run_weasyprint(input_md=input_md, output_pdf=output_pdf, css_path=css_path)
    logger.info("Exported PDF via WeasyPrint: %s", output_pdf)

