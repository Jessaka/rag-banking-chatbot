#!/usr/bin/env python3
"""Validátor stažených dokumentů a HTML/Markdown snapshotů."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.utils.logger import get_logger

app = typer.Typer(pretty_exceptions_enable=False)
console = Console()
logger = get_logger(__name__)

TEXT_EXT = {".txt", ".md", ".html", ".json", ".csv", ".xml"}
DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".csv", ".xml"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def meaningful_len(text: str) -> int:
    text = re.sub(r"\s+", " ", text)
    return len(re.sub(r"[^0-9A-Za-zÀ-ɏ]+", "", text))


def ocr_garbage_ratio(text: str) -> float:
    if not text:
        return 1.0
    alnum = len(re.findall(r"[0-9A-Za-zÀ-ɏ]", text))
    return round(1 - (alnum / max(len(text), 1)), 4)


def read_text_file(path: Path) -> tuple[str, list[str]]:
    issues = []
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), issues
    except UnicodeDecodeError:
        issues.append("encoding_problem_non_utf8")
        return raw.decode("utf-8", errors="replace"), issues


def validate_pdf(path: Path) -> dict[str, Any]:
    rec: dict[str, Any] = {"path": str(path), "type": "pdf", "size_bytes": path.stat().st_size, "issues": []}
    if path.stat().st_size == 0:
        rec["issues"].append("empty_pdf_zero_bytes")
        return rec
    if path.read_bytes()[:5] != b"%PDF-":
        rec["issues"].append("corrupted_pdf_invalid_header")
        return rec
    try:
        import fitz
        doc = fitz.open(path)
        rec["pages"] = doc.page_count
        if doc.page_count == 0:
            rec["issues"].append("empty_pdf_zero_pages")
        text = "\n".join(page.get_text("text") for page in doc)
        rec["text_chars"] = len(text)
        rec["ocr_garbage_ratio"] = ocr_garbage_ratio(text)
        if not text.strip() and doc.page_count > 0:
            rec["issues"].append("scanned_only_pdf_no_text")
        if text and rec["ocr_garbage_ratio"] > 0.65:
            rec["issues"].append("ocr_garbage_suspected")
        if meaningful_len(text) < 200:
            rec["issues"].append("boilerplate_or_too_short")
        doc.close()
    except Exception as exc:
        rec["issues"].append("corrupted_pdf_parse_error")
        rec["error"] = str(exc)
    return rec


def validate_text(path: Path) -> dict[str, Any]:
    text, issues = read_text_file(path)
    rec: dict[str, Any] = {"path": str(path), "type": path.suffix.lstrip(".").lower(), "size_bytes": path.stat().st_size, "text_chars": len(text), "ocr_garbage_ratio": ocr_garbage_ratio(text), "issues": issues}
    if path.stat().st_size == 0 or not text.strip():
        rec["issues"].append("empty_file")
    if rec["ocr_garbage_ratio"] > 0.75 and len(text) > 100:
        rec["issues"].append("ocr_garbage_suspected")
    mlen = meaningful_len(text)
    if mlen < 200:
        rec["issues"].append("boilerplate_or_too_short")
    nav_words = sum(text.lower().count(w) for w in ["menu", "navigace", "přihlášení", "kontakt", "vyhledávání", "cookies"])
    content_words = sum(text.lower().count(w) for w in ["sazebník", "podmínky", "úrok", "poplatek", "karta", "hypotéka", "úvěr"])
    if nav_words >= 5 and content_words == 0 and mlen < 800:
        rec["issues"].append("nav_only_page")
    return rec


def validate_binary(path: Path) -> dict[str, Any]:
    rec = {"path": str(path), "type": path.suffix.lstrip(".").lower() or "unknown", "size_bytes": path.stat().st_size, "issues": []}
    if path.stat().st_size == 0:
        rec["issues"].append("empty_file")
    return rec


def scan(root: Path, fix: bool) -> dict[str, Any]:
    records = []
    by_hash: dict[str, list[str]] = defaultdict(list)
    for path in root.rglob("*") if root.exists() else []:
        if not path.is_file() or path.name.endswith(".jsonl"):
            continue
        try:
            digest = sha256_file(path) if path.stat().st_size else "EMPTY"
            by_hash[digest].append(str(path))
            if path.suffix.lower() == ".pdf":
                rec = validate_pdf(path)
            elif path.suffix.lower() in TEXT_EXT:
                rec = validate_text(path)
            else:
                rec = validate_binary(path)
            rec["sha256"] = digest
            records.append(rec)
        except Exception as exc:
            records.append({"path": str(path), "issues": ["validation_exception"], "error": str(exc)})
    duplicates = [{"sha256": h, "files": files} for h, files in by_hash.items() if h != "EMPTY" and len(files) > 1]
    for rec in records:
        if rec.get("sha256") in {d["sha256"] for d in duplicates}:
            rec.setdefault("issues", []).append("duplicated_chunk_or_file_sha256")
    fixed = []
    if fix:
        for rec in records:
            if any(i in rec.get("issues", []) for i in ["empty_file", "empty_pdf_zero_bytes", "corrupted_pdf_invalid_header", "corrupted_pdf_parse_error"]):
                p = Path(rec["path"])
                try:
                    p.unlink(missing_ok=True)
                    fixed.append(str(p))
                except Exception as exc:
                    rec.setdefault("fix_errors", []).append(str(exc))
    summary = {"total_files": len(records), "files_with_issues": sum(1 for r in records if r.get("issues")), "duplicate_groups": len(duplicates), "fixed_deleted": fixed}
    return {"summary": summary, "duplicates": duplicates, "files": records}


@app.callback(invoke_without_command=True)
def main(dir: Path = typer.Option(config.DOCUMENTS_DIR, "--dir", help="Adresář dokumentů ke kontrole."), fix: bool = typer.Option(False, "--fix", help="Smaže corrupted/empty soubory.")) -> None:
    report = scan(dir, fix)
    config.DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    (config.DISCOVERY_DIR / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    table = Table(title="Document validation")
    table.add_column("Metric"); table.add_column("Value", justify="right")
    for k, v in report["summary"].items():
        table.add_row(k, str(v if not isinstance(v, list) else len(v)))
    console.print(table)


if __name__ == "__main__":
    app()
