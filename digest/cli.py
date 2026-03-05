from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .build import build_digest
from .pdf_export import PdfExportError, export_markdown_to_pdf
from .render import render_markdown


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m digest", description="Daily AI research digest tools.")
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR).")

    sub = p.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Build digest JSON from raw input.")
    p_build.add_argument("--date", required=True, help="Digest date (YYYY-MM-DD).")
    p_build.add_argument("--input", required=True, type=Path, help="Path to raw.json (or memory.json).")
    p_build.add_argument("--out", default=Path("./reports_json"), type=Path, help="Output dir for JSON.")
    p_build.add_argument("--top-n", default=10, type=int, help="Max items in Top papers.")
    p_build.add_argument("--sources-csv", default=None, type=Path, help="Optional sources.csv for nicer labels.")
    p_build.add_argument("--force", action="store_true", help="Overwrite existing YYYY-MM-DD.json if present.")

    p_render = sub.add_parser("render", help="Render digest JSON to Markdown.")
    p_render.add_argument("--date", required=True, help="Digest date (YYYY-MM-DD).")
    p_render.add_argument("--in", dest="in_dir", default=Path("./reports_json"), type=Path, help="Input JSON dir.")
    p_render.add_argument("--out", default=Path("./reports_md"), type=Path, help="Output dir for Markdown.")

    p_pdf = sub.add_parser("pdf", help="Convert Markdown digest to PDF.")
    p_pdf.add_argument("--date", required=True, help="Digest date (YYYY-MM-DD).")
    p_pdf.add_argument("--md-dir", default=Path("./reports_md"), type=Path, help="Input Markdown dir.")
    p_pdf.add_argument("--out", default=Path("./reports_pdf"), type=Path, help="Output PDF dir.")
    p_pdf.add_argument("--css", default=None, type=Path, help="Optional CSS file for WeasyPrint backend.")
    p_pdf.add_argument("--pdf-engine", default="xelatex", help="Pandoc PDF engine (default: xelatex).")

    p_all = sub.add_parser("all", help="Build + render + pdf.")
    p_all.add_argument("--date", required=True, help="Digest date (YYYY-MM-DD).")
    p_all.add_argument("--input", required=True, type=Path, help="Path to raw.json (or memory.json).")
    p_all.add_argument("--json-out", default=Path("./reports_json"), type=Path, help="Output dir for JSON.")
    p_all.add_argument("--md-out", default=Path("./reports_md"), type=Path, help="Output dir for Markdown.")
    p_all.add_argument("--pdf-out", default=Path("./reports_pdf"), type=Path, help="Output dir for PDFs.")
    p_all.add_argument("--top-n", default=10, type=int, help="Max items in Top papers.")
    p_all.add_argument("--sources-csv", default=None, type=Path, help="Optional sources.csv for nicer labels.")
    p_all.add_argument("--force", action="store_true", help="Overwrite existing outputs if present.")
    p_all.add_argument("--css", default=None, type=Path, help="Optional CSS file for WeasyPrint backend.")
    p_all.add_argument("--pdf-engine", default="xelatex", help="Pandoc PDF engine (default: xelatex).")

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    _configure_logging(args.log_level)

    try:
        if args.cmd == "build":
            build_digest(
                date=args.date,
                input_path=args.input,
                out_dir=args.out,
                top_n=args.top_n,
                sources_csv=args.sources_csv,
                force=args.force,
            )
            return 0

        if args.cmd == "render":
            render_markdown(date=args.date, in_dir=args.in_dir, out_dir=args.out)
            return 0

        if args.cmd == "pdf":
            md_path = args.md_dir / f"{args.date}.md"
            pdf_path = args.out / f"{args.date}.pdf"
            export_markdown_to_pdf(
                input_md=md_path,
                output_pdf=pdf_path,
                css_path=args.css,
                pandoc_pdf_engine=args.pdf_engine,
            )
            return 0

        if args.cmd == "all":
            build_digest(
                date=args.date,
                input_path=args.input,
                out_dir=args.json_out,
                top_n=args.top_n,
                sources_csv=args.sources_csv,
                force=args.force,
            )
            md_path = render_markdown(date=args.date, in_dir=args.json_out, out_dir=args.md_out)
            export_markdown_to_pdf(
                input_md=md_path,
                output_pdf=args.pdf_out / f"{args.date}.pdf",
                css_path=args.css,
                pandoc_pdf_engine=args.pdf_engine,
            )
            return 0

        raise ValueError(f"Unknown command: {args.cmd}")
    except (FileNotFoundError, FileExistsError, ValueError, PdfExportError) as exc:
        logging.getLogger(__name__).error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

