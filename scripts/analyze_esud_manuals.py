from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tmp" / "pdfs" / "esud_manuals"
FILES = [
    ROOT / "Інструкція_користувача_підсистеми_Електронний_кабінет.pdf",
    ROOT / "Інструкція_користувача_підсистеми_Електронний_суд.pdf",
]


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def flatten_outline(items, depth: int = 0) -> list[dict]:
    result: list[dict] = []
    for item in items or []:
        if isinstance(item, list):
            result.extend(flatten_outline(item, depth + 1))
            continue
        title = getattr(item, "title", None) or str(item)
        result.append({"depth": depth, "title": title})
    return result


def heading_candidates(text: str, page: int) -> list[dict]:
    candidates: list[dict] = []
    for raw in text.splitlines():
        line = " ".join(raw.split()).strip()
        if not line or len(line) < 4 or len(line) > 180:
            continue
        numbered = re.match(r"^(?:\d+(?:\.\d+){0,5}\.?|РОЗДІЛ\s+\d+|ДОДАТОК\s+[А-ЯA-Z0-9]+)\s+", line, re.I)
        uppercase = sum(char.isupper() for char in line if char.isalpha())
        letters = sum(char.isalpha() for char in line)
        mostly_upper = letters >= 5 and uppercase / letters >= 0.82
        keyword = re.match(
            r"^(?:ЗМІСТ|ВСТУП|ТЕРМІНИ|СКОРОЧЕННЯ|АВТОРИЗАЦІЯ|РЕЄСТРАЦІЯ|ГОЛОВНА|ПОВІДОМЛЕННЯ|"
            r"ЗАЯВИ|ДОКУМЕНТИ|СПРАВИ|ПРОВАДЖЕННЯ|ДОВІРЕНОСТІ|ОПЛАТА|ВІДЕОКОНФЕРЕНЦІЯ|ТЕХНІЧНІ ВИМОГИ)",
            line,
            re.I,
        )
        if numbered or mostly_upper or keyword:
            candidates.append({"page": page, "text": line})
    return candidates


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for source in FILES:
        if not source.exists():
            raise FileNotFoundError(source)
        reader = PdfReader(str(source))
        page_records = []
        headings = []
        combined_parts = []
        for index, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                text = ""
                error = type(exc).__name__
            else:
                error = None
            normalized = "\n".join(line.rstrip() for line in text.replace("\r", "\n").splitlines())
            combined_parts.append(f"\n\n===== СТОРІНКА {index} =====\n{normalized}")
            page_records.append(
                {
                    "page": index,
                    "characters": len(normalized),
                    "words": len(normalized.split()),
                    "extraction_error": error,
                }
            )
            headings.extend(heading_candidates(normalized, index))

        slug = "electronic_cabinet" if "кабінет" in source.name.lower() else "electronic_court"
        text_path = OUTPUT / f"{slug}__full_text.txt"
        text_path.write_text("".join(combined_parts), encoding="utf-8")
        metadata = {str(key): str(value) for key, value in (reader.metadata or {}).items()}
        try:
            outline = flatten_outline(reader.outline)
        except Exception:
            outline = []
        report = {
            "source_name": source.name,
            "slug": slug,
            "sha256": sha256(source),
            "size": source.stat().st_size,
            "pages": len(reader.pages),
            "text_characters": sum(item["characters"] for item in page_records),
            "pages_with_less_than_80_characters": [item["page"] for item in page_records if item["characters"] < 80],
            "metadata": metadata,
            "outline": outline,
            "heading_candidates": headings,
            "page_records": page_records,
            "full_text_file": text_path.name,
        }
        reports.append(report)

    index_path = OUTPUT / "manuals_index.json"
    index_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    "name": item["source_name"],
                    "pages": item["pages"],
                    "characters": item["text_characters"],
                    "weak_text_pages": item["pages_with_less_than_80_characters"],
                    "outline_items": len(item["outline"]),
                    "heading_candidates": len(item["heading_candidates"]),
                }
                for item in reports
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
