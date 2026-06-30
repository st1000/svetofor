#!/usr/bin/env python3
"""Batch OCR for court case materials: PNG screenshots, PDFs, EML emails."""

from __future__ import annotations

import email
import re
import sys
from datetime import datetime
from email import policy
from pathlib import Path

from ocrmac import ocrmac

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "текст"
SCREENSHOTS_DIR = ROOT / "скриншоты"
LETTERS_DIR = ROOT / "письма"
CONTRACT_DIR = ROOT / "Договор"


def ocr_image(path: Path) -> str:
    try:
        results = ocrmac.OCR(str(path), language_preference=["ru-RU", "en-US"]).recognize()
        lines = [text for text, _conf, _bbox in results if text.strip()]
        return "\n".join(lines)
    except Exception as exc:
        return f"[OCR ERROR: {exc}]"


def extract_pdf(path: Path) -> str:
    if fitz is None:
        return "[pymupdf not installed]"
    try:
        doc = fitz.open(path)
        parts: list[str] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if len(text) > 50:
                parts.append(f"--- Страница {i} ---\n{text}")
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            tmp = Path(f"/tmp/ocr_pdf_{path.stem}_{i}.png")
            pix.save(tmp)
            results = ocrmac.OCR(str(tmp), language_preference=["ru-RU", "en-US"]).recognize()
            tmp.unlink(missing_ok=True)
            ocr_text = "\n".join(t for t, _, _ in results if t.strip())
            parts.append(f"--- Страница {i} (OCR) ---\n{ocr_text}")
        doc.close()
        return "\n\n".join(parts) if parts else "[PDF: пустой документ]"
    except Exception as exc:
        return f"[PDF ERROR: {exc}]"


def extract_eml(path: Path) -> str:
    try:
        raw = path.read_bytes()
        msg = email.message_from_bytes(raw, policy=policy.default)
        parts: list[str] = [
            f"From: {msg.get('From', '')}",
            f"To: {msg.get('To', '')}",
            f"Date: {msg.get('Date', '')}",
            f"Subject: {msg.get('Subject', '')}",
            "",
        ]
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    payload = part.get_content()
                    if isinstance(payload, str) and payload.strip():
                        parts.append(payload.strip())
        else:
            payload = msg.get_content()
            if isinstance(payload, str):
                parts.append(payload.strip())
        return "\n".join(parts)
    except Exception as exc:
        return f"[EML ERROR: {exc}]"


def safe_name(path: Path) -> str:
    name = path.stem
    name = re.sub(r"[^\w\s\-\.]", "_", name, flags=re.UNICODE)
    return name[:120]


def process_file(path: Path, out_subdir: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".png":
        text = ocr_image(path)
        kind = "screenshot"
    elif suffix == ".pdf":
        text = extract_pdf(path)
        kind = "pdf"
    elif suffix == ".eml":
        text = extract_eml(path)
        kind = "email"
    elif suffix in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        kind = "text"
    else:
        return {}

    out_file = out_subdir / f"{safe_name(path)}.txt"
    header = (
        f"Источник: {path.relative_to(ROOT)}\n"
        f"Тип: {kind}\n"
        f"Обработано: {datetime.now().isoformat(timespec='seconds')}\n"
        f"{'=' * 60}\n\n"
    )
    out_file.write_text(header + text, encoding="utf-8")
    return {"path": str(path), "out": str(out_file), "chars": len(text), "kind": kind}


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "скриншоты").mkdir(exist_ok=True)
    (OUT_DIR / "pdf").mkdir(exist_ok=True)
    (OUT_DIR / "письма").mkdir(exist_ok=True)
    (OUT_DIR / "договор").mkdir(exist_ok=True)

    stats: list[dict] = []
    errors: list[str] = []

    targets: list[tuple[Path, Path]] = []

    if SCREENSHOTS_DIR.exists():
        for p in sorted(SCREENSHOTS_DIR.rglob("*.png")):
            targets.append((p, OUT_DIR / "скриншоты"))

    for pdf_dir in [SCREENSHOTS_DIR, CONTRACT_DIR, ROOT]:
        if pdf_dir.exists():
            for p in sorted(pdf_dir.rglob("*.pdf")):
                rel = "pdf" if p.parent.name != "претензия" else "pdf"
                targets.append((p, OUT_DIR / rel))

    if LETTERS_DIR.exists():
        for p in sorted(LETTERS_DIR.glob("*.eml")):
            targets.append((p, OUT_DIR / "письма"))

    if CONTRACT_DIR.exists():
        for p in sorted(CONTRACT_DIR.glob("*.md")):
            targets.append((p, OUT_DIR / "договор"))

    total = len(targets)
    print(f"Файлов к обработке: {total}", flush=True)

    for i, (path, out_subdir) in enumerate(targets, start=1):
        print(f"[{i}/{total}] {path.name}", flush=True)
        try:
            result = process_file(path, out_subdir)
            if result:
                stats.append(result)
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    # combined index
    index_lines = [
        "# Индекс распознанных материалов",
        f"Дата: {datetime.now().isoformat(timespec='seconds')}",
        f"Всего файлов: {len(stats)}",
        f"Ошибок: {len(errors)}",
        "",
    ]
    for s in stats:
        index_lines.append(
            f"- [{s['kind']}] {s['path']} -> {s['out']} ({s['chars']} симв.)"
        )
    if errors:
        index_lines.extend(["", "## Ошибки", ""] + [f"- {e}" for e in errors])

    (OUT_DIR / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    # combined full text for search
    combined: list[str] = ["# Полный текст всех материалов\n"]
    for s in stats:
        text = Path(s["out"]).read_text(encoding="utf-8")
        combined.append(f"\n\n{'#' * 2} {s['path']}\n\n{text}")
    (OUT_DIR / "ALL_TEXT.md").write_text("\n".join(combined), encoding="utf-8")

    print(f"\nГотово: {len(stats)} файлов, {len(errors)} ошибок")
    print(f"Индекс: {OUT_DIR / 'INDEX.md'}")
    print(f"Полный текст: {OUT_DIR / 'ALL_TEXT.md'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
