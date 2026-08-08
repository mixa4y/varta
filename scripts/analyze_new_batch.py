from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def safe_target(base: Path, name: str) -> Path:
    normalized = name.replace("/", "\\")
    parts = [part for part in normalized.split("\\") if part not in ("", ".", "..")]
    target = base.joinpath(*parts)
    resolved_base = base.resolve()
    resolved_target = target.resolve()
    if resolved_base != resolved_target and resolved_base not in resolved_target.parents:
        raise ValueError(f"Unsafe ZIP entry: {name}")
    return target


def decode_html(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "windows-1251", "cp866"):
        try:
            raw = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raw = data.decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def pdf_summary(data: bytes) -> dict:
    reader = PdfReader(BytesIO(data), strict=False)
    chunks: list[str] = []
    for page in reader.pages[:8]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            chunks.append(f"[TEXT_EXTRACTION_ERROR: {exc}]")
    text = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    return {
        "pages": len(reader.pages),
        "text_chars": len(text),
        "text": text[:12000],
        "metadata": {str(k): str(v) for k, v in (reader.metadata or {}).items()},
    }


def inspect_zip(zip_path: Path, review_dir: Path) -> dict:
    archive_dir = review_dir / zip_path.stem
    archive_dir.mkdir(parents=True, exist_ok=True)
    record = {"zip": zip_path.name, "path": str(zip_path), "entries": []}
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info)
            target = safe_target(archive_dir, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            suffix = target.suffix.lower()
            item = {
                "name": info.filename,
                "size": len(data),
                "sha256": digest(data),
                "extracted_path": str(target),
            }
            if suffix in (".html", ".htm"):
                text = decode_html(data)
                item["html_text_chars"] = len(text)
                item["html_text"] = text[:12000]
            elif suffix == ".pdf":
                try:
                    item["pdf"] = pdf_summary(data)
                except Exception as exc:  # noqa: BLE001
                    item["pdf_error"] = str(exc)
            elif suffix == ".zip":
                nested_dir = target.with_suffix("")
                nested_dir.mkdir(parents=True, exist_ok=True)
                nested = []
                try:
                    with zipfile.ZipFile(BytesIO(data)) as nested_zip:
                        for nested_info in nested_zip.infolist():
                            if nested_info.is_dir():
                                continue
                            nested_data = nested_zip.read(nested_info)
                            nested_target = safe_target(nested_dir, nested_info.filename)
                            nested_target.parent.mkdir(parents=True, exist_ok=True)
                            nested_target.write_bytes(nested_data)
                            nested_item = {
                                "name": nested_info.filename,
                                "size": len(nested_data),
                                "sha256": digest(nested_data),
                                "extracted_path": str(nested_target),
                            }
                            if nested_target.suffix.lower() == ".pdf":
                                try:
                                    nested_item["pdf"] = pdf_summary(nested_data)
                                except Exception as exc:  # noqa: BLE001
                                    nested_item["pdf_error"] = str(exc)
                            nested.append(nested_item)
                except Exception as exc:  # noqa: BLE001
                    item["nested_zip_error"] = str(exc)
                item["nested_entries"] = nested
            record["entries"].append(item)
    return record


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Безпечно розпакувати й проаналізувати ZIP-пакет із заданого inbox."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Корінь локального workspace.")
    parser.add_argument(
        "--inbox",
        type=Path,
        default=Path("00_INBOX"),
        help="Абсолютний шлях або шлях відносно --root.",
    )
    parser.add_argument(
        "--review-dir",
        type=Path,
        help="Каталог звіту; типово tmp/reviews/<timestamp> відносно --root.",
    )
    parser.add_argument(
        "--expected-zip-count",
        type=int,
        help="Необов'язкова точна кількість ZIP для контрольної перевірки.",
    )
    return parser.parse_args(argv)


def resolve_under_root(root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (root / value).resolve()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    inbox = resolve_under_root(root, args.inbox)
    review_dir = (
        resolve_under_root(root, args.review_dir)
        if args.review_dir
        else root / "tmp" / "reviews" / f"zip_review_{datetime.now():%Y%m%d_%H%M%S}"
    )
    if args.expected_zip_count is not None and args.expected_zip_count < 0:
        raise ValueError("--expected-zip-count не може бути від'ємним")
    if not inbox.is_dir():
        raise NotADirectoryError(inbox)

    review_dir.mkdir(parents=True, exist_ok=False)
    zips = sorted(inbox.glob("*.zip"))
    if args.expected_zip_count is not None and len(zips) != args.expected_zip_count:
        raise RuntimeError(
            f"Очікувалося ZIP-файлів: {args.expected_zip_count}; знайдено: {len(zips)}"
        )
    report = {
        "root": str(root),
        "inbox": str(inbox),
        "review_dir": str(review_dir),
        "archives": [inspect_zip(path, review_dir) for path in zips],
    }
    report_path = review_dir / "analysis.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "review_dir": str(review_dir),
        "report": str(report_path),
        "archives": [
            {
                "zip": archive["zip"],
                "entries": len(archive["entries"]),
                "key_entries": [
                    {
                        "name": item["name"],
                        "size": item["size"],
                        "pages": item.get("pdf", {}).get("pages"),
                        "text_chars": item.get("pdf", {}).get("text_chars", item.get("html_text_chars")),
                        "preview": item.get("pdf", {}).get("text", item.get("html_text", ""))[:1200],
                        "nested_count": len(item.get("nested_entries", [])),
                    }
                    for item in archive["entries"]
                    if item["name"].lower().endswith((".pdf", ".html", ".zip"))
                ],
            }
            for archive in report["archives"]
        ],
    }
    print(json.dumps(compact, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
