"""OCR detection and fallback processing for PDF ingestion.

This module is intentionally self-contained and uses optional OCR dependencies.
It detects scanned/image-only PDFs before normal chunking and writes OCR output as
plain text files that downstream ingestion can consume instead of the source PDF.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber

SCANNED_TEXT_THRESHOLD = 50
SCANNED_DENSITY_THRESHOLD = 0.001
OCR_QUALITY_MIN = 0.3
OCR_ENGINE_PREFERENCE = ["tesseract", "paddleocr"]

logger = logging.getLogger(__name__)

# Public-ish diagnostics for callers that need reasons while keeping the required
# is_scanned_pdf(path: str) -> bool API.
SCAN_DETECTION_REASONS: dict[str, dict[str, Any]] = {}
OCR_RESULTS: dict[str, dict[str, Any]] = {}


class OCRNotAvailable(Exception):
    """Raised when no supported OCR engine is installed or executable."""


class OCRProcessingError(Exception):
    """Raised when OCR fails for a specific file."""


def _ocr_output_path(path: str, output_dir: str) -> str:
    source = Path(path)
    return str(Path(output_dir) / f"{source.stem}_ocr.txt")


def _clean_ocr_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_len(text: str | None) -> int:
    return len(text or "")


def _resolve_pdf_obj(value: Any) -> Any:
    try:
        from pdfminer.pdftypes import resolve1

        return resolve1(value)
    except Exception:
        return value


def _stream_size(value: Any) -> int:
    """Best-effort byte size for a PDF page /Contents object."""
    value = _resolve_pdf_obj(value)
    if value is None:
        return 0
    if isinstance(value, list):
        return sum(_stream_size(item) for item in value)

    try:
        raw = value.get_rawdata()
        if raw:
            return len(raw)
    except Exception:
        pass

    try:
        data = value.get_data()
        if data:
            return len(data)
    except Exception:
        pass

    try:
        return len(bytes(value))
    except Exception:
        return 0


def _page_content_size(page: Any) -> int:
    try:
        contents = page.page_obj.attrs.get("Contents")
    except Exception:
        return 0
    return _stream_size(contents)


def _page_has_fonts(page: Any) -> bool:
    try:
        resources = _resolve_pdf_obj(page.page_obj.attrs.get("Resources", {})) or {}
        fonts = _resolve_pdf_obj(resources.get("Font", {})) or {}
        return bool(fonts)
    except Exception:
        return False


def _pdf_text_stats(path: str) -> dict[str, Any]:
    total_text_len = 0
    total_content_bytes = 0
    page_count = 0
    pages_without_fonts = 0
    extraction_errors: list[str] = []

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            page_count += 1
            try:
                text = page.extract_text() or ""
                total_text_len += len(text.strip())
            except Exception as exc:
                extraction_errors.append(f"page_{page_index}: {exc.__class__.__name__}")

            content_size = _page_content_size(page)
            if content_size <= 0:
                # Fallback to file-size/page-count approximation when content
                # streams are unavailable through pdfminer internals.
                try:
                    content_size = max(os.path.getsize(path) // max(len(pdf.pages), 1), 1)
                except OSError:
                    content_size = 1
            total_content_bytes += content_size

            if not _page_has_fonts(page):
                pages_without_fonts += 1

    density = total_text_len / max(total_content_bytes, 1)
    no_fonts_ratio = pages_without_fonts / max(page_count, 1)
    return {
        "total_text_len": total_text_len,
        "total_content_bytes": total_content_bytes,
        "text_density": density,
        "page_count": page_count,
        "pages_without_fonts": pages_without_fonts,
        "no_fonts_ratio": no_fonts_ratio,
        "extraction_errors": extraction_errors,
    }


def is_scanned_pdf(path: str) -> bool:
    """Return True when a PDF is likely scanned/image-only.

    Detection reasons are stored in ``SCAN_DETECTION_REASONS[path]``. The signal
    combines total extractable text, text density per page content byte and PDF
    font resources.
    """
    reasons: list[str] = []
    try:
        stats = _pdf_text_stats(path)
    except Exception as exc:
        SCAN_DETECTION_REASONS[path] = {
            "is_scanned": False,
            "confidence": 0.0,
            "reasons": [f"detection_failed: {exc.__class__.__name__}"],
            "error": str(exc),
            "total_text_len": 0,
            "text_density": 0.0,
        }
        logger.warning(
            "ocr_scan_detection_failed path=%s error_type=%s error=%s",
            path,
            exc.__class__.__name__,
            exc,
        )
        return False

    if stats["total_text_len"] < SCANNED_TEXT_THRESHOLD:
        reasons.append("total_text_below_threshold")
    if stats["text_density"] < SCANNED_DENSITY_THRESHOLD:
        reasons.append("text_density_below_threshold")
    if stats["page_count"] > 0 and stats["pages_without_fonts"] == stats["page_count"]:
        reasons.append("no_font_resources")

    is_scanned = len(reasons) >= 2 or (
        "total_text_below_threshold" in reasons and "no_font_resources" in reasons
    )
    confidence = min(1.0, len(reasons) / 3.0)
    if not is_scanned:
        confidence = max(0.0, 1.0 - confidence)

    SCAN_DETECTION_REASONS[path] = {
        "is_scanned": is_scanned,
        "confidence": confidence,
        "reasons": reasons or ["extractable_text_detected"],
        **stats,
    }
    logger.info(
        "ocr_scan_detection path=%s is_scanned=%s confidence=%.2f text_len=%s density=%.6f reasons=%s",
        path,
        is_scanned,
        confidence,
        stats["total_text_len"],
        stats["text_density"],
        reasons,
    )
    return is_scanned


def _tesseract_available() -> Any | None:
    try:
        import pytesseract

        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            logger.warning("ocr_engine_unavailable engine=tesseract reason=%s", exc)
            return None
        return pytesseract
    except ImportError:
        logger.warning("ocr_engine_missing engine=tesseract package=pytesseract")
        return None


def _pdf2image_available() -> Any | None:
    try:
        from pdf2image import convert_from_path

        return convert_from_path
    except ImportError:
        logger.warning("ocr_dependency_missing package=pdf2image")
        return None


def _paddleocr_available() -> Any | None:
    try:
        from paddleocr import PaddleOCR

        return PaddleOCR
    except ImportError:
        logger.warning("ocr_engine_missing engine=paddleocr package=paddleocr")
        return None


def _ocr_with_tesseract(path: str) -> tuple[str, dict[str, Any]]:
    pytesseract = _tesseract_available()
    if pytesseract is None:
        raise OCRNotAvailable("pytesseract/Tesseract is not available")

    convert_from_path = _pdf2image_available()
    if convert_from_path is None:
        raise OCRNotAvailable("pdf2image is required for Tesseract PDF OCR")

    texts: list[str] = []
    confidences: list[float] = []
    try:
        pages = convert_from_path(path, dpi=300)
        for page_number, image in enumerate(pages, start=1):
            text = pytesseract.image_to_string(image)
            texts.append(f"\n\n--- Page {page_number} ---\n{text}")
            try:
                data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
                for raw_conf in data.get("conf", []):
                    try:
                        conf = float(raw_conf)
                    except (TypeError, ValueError):
                        continue
                    if conf >= 0:
                        confidences.append(conf / 100.0)
            except Exception as exc:
                logger.warning(
                    "ocr_confidence_unavailable engine=tesseract path=%s page=%s error_type=%s",
                    path,
                    page_number,
                    exc.__class__.__name__,
                )
    except OCRNotAvailable:
        raise
    except Exception as exc:
        raise OCRProcessingError(f"Tesseract OCR failed for {path}: {exc}") from exc

    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    return _clean_ocr_text("\n".join(texts)), {
        "engine": "tesseract",
        "page_count": len(texts),
        "char_confidence": avg_confidence,
    }


def _ocr_with_paddleocr(path: str) -> tuple[str, dict[str, Any]]:
    PaddleOCR = _paddleocr_available()
    if PaddleOCR is None:
        raise OCRNotAvailable("paddleocr is not available")

    convert_from_path = _pdf2image_available()
    if convert_from_path is None:
        raise OCRNotAvailable("pdf2image is required for PaddleOCR PDF OCR")

    texts: list[str] = []
    confidences: list[float] = []
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        with tempfile.TemporaryDirectory(prefix="ocr_paddle_") as tmp_dir:
            pages = convert_from_path(path, dpi=300)
            for page_number, image in enumerate(pages, start=1):
                image_path = Path(tmp_dir) / f"page_{page_number}.png"
                image.save(image_path)
                result = ocr.ocr(str(image_path), cls=True)
                page_lines: list[str] = []
                for block in result or []:
                    for line in block or []:
                        if len(line) < 2:
                            continue
                        payload = line[1]
                        if isinstance(payload, (list, tuple)) and payload:
                            page_lines.append(str(payload[0]))
                            if len(payload) > 1:
                                try:
                                    confidences.append(float(payload[1]))
                                except (TypeError, ValueError):
                                    pass
                texts.append(f"\n\n--- Page {page_number} ---\n" + "\n".join(page_lines))
    except OCRNotAvailable:
        raise
    except Exception as exc:
        raise OCRProcessingError(f"PaddleOCR failed for {path}: {exc}") from exc

    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    return _clean_ocr_text("\n".join(texts)), {
        "engine": "paddleocr",
        "page_count": len(texts),
        "char_confidence": avg_confidence,
    }


def ocr_pdf(path: str, output_dir: str) -> str:
    """Run OCR for a PDF and write ``{output_dir}/{basename}_ocr.txt``.

    Engine order follows ``OCR_ENGINE_PREFERENCE``. Missing optional imports are
    logged as warnings and only raise ``OCRNotAvailable`` when no engine can run.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = _ocr_output_path(path, output_dir)
    errors: list[str] = []

    for engine in OCR_ENGINE_PREFERENCE:
        try:
            if engine == "tesseract":
                text, metadata = _ocr_with_tesseract(path)
            elif engine == "paddleocr":
                text, metadata = _ocr_with_paddleocr(path)
            else:
                logger.warning("ocr_engine_unknown engine=%s", engine)
                continue

            Path(output_path).write_text(text, encoding="utf-8")
            metadata.update(
                {
                    "source_path": path,
                    "output_path": output_path,
                    "text_len": len(text),
                    "quality": validate_ocr_quality(output_path),
                }
            )
            OCR_RESULTS[path] = metadata
            logger.info(
                "ocr_processing_success path=%s output_path=%s engine=%s text_len=%s",
                path,
                output_path,
                metadata.get("engine"),
                len(text),
            )
            return output_path
        except OCRNotAvailable as exc:
            errors.append(f"{engine}: {exc}")
            continue
        except OCRProcessingError:
            raise
        except Exception as exc:
            raise OCRProcessingError(f"OCR failed for {path} using {engine}: {exc}") from exc

    logger.warning("ocr_no_engine_available path=%s errors=%s", path, errors)
    raise OCRNotAvailable("No OCR engine available. Install pytesseract+pdf2image or paddleocr+pdf2image.")


def process_document(path: str, output_dir: str) -> dict[str, Any]:
    """Detect scan status and OCR scanned PDFs, returning ingestion metadata."""
    scanned = is_scanned_pdf(path)
    detection = SCAN_DETECTION_REASONS.get(path, {})
    original_text_len = int(detection.get("total_text_len", 0) or 0)

    result: dict[str, Any] = {
        "path": path,
        "ocr_applied": False,
        "ocr_engine": None,
        "original_text_len": original_text_len,
        "ocr_text_len": 0,
        "is_scanned": scanned,
        "confidence": float(detection.get("confidence", 0.0) or 0.0),
        "detection": detection,
    }

    if not scanned:
        return result

    output_path = ocr_pdf(path, output_dir)
    ocr_text_len = _safe_len(Path(output_path).read_text(encoding="utf-8", errors="ignore"))
    ocr_metadata = OCR_RESULTS.get(path, {})
    result.update(
        {
            "path": output_path,
            "ocr_applied": True,
            "ocr_engine": ocr_metadata.get("engine"),
            "ocr_text_len": ocr_text_len,
            "ocr_quality": ocr_metadata.get("quality"),
        }
    )
    return result


def batch_ocr(input_dir: str, output_dir: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Process all PDFs in a directory with resume support.

    ``config`` supports optional keys:
    - ``recursive`` (bool): scan subdirectories, default False
    - ``force`` (bool): re-run OCR even when output exists, default False
    """
    recursive = bool(config.get("recursive", False))
    force = bool(config.get("force", False))
    input_path = Path(input_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    pdfs = sorted(input_path.rglob("*.pdf") if recursive else input_path.glob("*.pdf"))
    results: list[dict[str, Any]] = []

    for pdf_path in pdfs:
        path = str(pdf_path)
        output_path = _ocr_output_path(path, output_dir)
        try:
            if not force and Path(output_path).exists():
                quality = validate_ocr_quality(output_path)
                result = {
                    "path": output_path,
                    "source_path": path,
                    "ocr_applied": True,
                    "ocr_engine": None,
                    "original_text_len": 0,
                    "ocr_text_len": _safe_len(Path(output_path).read_text(encoding="utf-8", errors="ignore")),
                    "is_scanned": True,
                    "confidence": 1.0,
                    "status": "skipped_existing",
                    "ocr_quality": quality,
                }
                logger.info("ocr_batch_skip_existing path=%s output_path=%s", path, output_path)
            else:
                result = process_document(path, output_dir)
                result["source_path"] = path
                result["status"] = "ocr_applied" if result.get("ocr_applied") else "not_scanned"
            results.append(result)
        except Exception as exc:
            logger.warning(
                "ocr_batch_file_failed path=%s error_type=%s error=%s",
                path,
                exc.__class__.__name__,
                exc,
            )
            results.append(
                {
                    "path": path,
                    "source_path": path,
                    "ocr_applied": False,
                    "ocr_engine": None,
                    "original_text_len": 0,
                    "ocr_text_len": 0,
                    "is_scanned": False,
                    "confidence": 0.0,
                    "status": "failed",
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            )
    return results


def validate_ocr_quality(text_path: str) -> dict[str, Any]:
    """Validate OCR text and return a 0.0-1.0 quality score with issues."""
    issues: list[str] = []
    try:
        text = Path(text_path).read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {"quality_score": 0.0, "issues": [f"read_failed: {exc}"], "char_confidence": None}

    stripped = text.strip()
    if not stripped:
        return {"quality_score": 0.0, "issues": ["empty_output"], "char_confidence": None}

    chars = len(stripped)
    alnum = sum(1 for char in stripped if char.isalnum())
    spaces = sum(1 for char in stripped if char.isspace())
    non_alnum_ratio = 1.0 - (alnum / max(chars, 1))
    space_ratio = spaces / max(chars, 1)
    repeated_single_chars = re.findall(r"(?i)(.)\1{9,}", stripped)
    tokens = re.findall(r"\S+", stripped)
    single_char_token_ratio = sum(1 for token in tokens if len(token.strip(".,;:()[]{}|")) == 1) / max(len(tokens), 1)

    score = 1.0
    if chars < SCANNED_TEXT_THRESHOLD:
        issues.append("too_short")
        score -= 0.35
    if repeated_single_chars:
        issues.append("repeated_single_chars")
        score -= 0.25
    if space_ratio < 0.03 and chars > 100:
        issues.append("few_or_no_spaces")
        score -= 0.2
    if non_alnum_ratio > 0.55:
        issues.append("mostly_non_alphanumeric")
        score -= 0.3
    if single_char_token_ratio > 0.35 and len(tokens) > 20:
        issues.append("many_single_character_tokens")
        score -= 0.2

    # Best-effort confidence propagated from the latest OCR run for this output.
    char_confidence = None
    for metadata in OCR_RESULTS.values():
        if metadata.get("output_path") == text_path:
            char_confidence = metadata.get("char_confidence")
            break
    if char_confidence is not None and char_confidence < OCR_QUALITY_MIN:
        issues.append("low_engine_confidence")
        score -= 0.25

    score = max(0.0, min(1.0, score))
    if score < OCR_QUALITY_MIN and "below_min_quality" not in issues:
        issues.append("below_min_quality")

    return {
        "quality_score": score,
        "issues": issues,
        "char_confidence": char_confidence,
        "char_count": chars,
        "alphanumeric_ratio": alnum / max(chars, 1),
        "space_ratio": space_ratio,
    }
