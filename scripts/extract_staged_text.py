from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: str) -> str:
    value = value.replace("\x00", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n{3,}", "\n\n", value)).strip()


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "windows-1251", "cp866"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def html_text(path: Path) -> str:
    raw = decode(path.read_bytes())
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</li>|</div>|</h[1-6]>", "\n", raw)
    return normalize(html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw)))


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read("word/document.xml").decode("utf-8", errors="replace")
    raw = re.sub(r"</w:p>|</w:tr>", "\n", raw)
    return normalize(html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw)))


def pdf_text(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path), strict=False)
    chunks: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            chunks.append(f"\n===== PAGE {number} =====\n{page.extract_text() or ''}")
        except Exception as exc:  # noqa: BLE001
            chunks.append(f"\n===== PAGE {number} =====\n[PAGE_TEXT_ERROR: {exc}]")
    return normalize("".join(chunks)), len(reader.pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract searchable text from staging documents.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = (ROOT / args.manifest).resolve()
    output = (ROOT / args.output).resolve()
    if ROOT.resolve() not in manifest_path.parents or ROOT.resolve() not in output.parents:
        raise ValueError("paths must remain inside project")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for package in payload["packages"]:
        for item in package["records"]:
            relative = item.get("staged_relative")
            if not relative or item.get("error"):
                continue
            source = ROOT / relative
            suffix = source.suffix.casefold()
            if source.name.casefold().endswith(".p7s.2") or suffix == ".p7s":
                continue
            text = ""
            pages = None
            error = None
            try:
                if suffix == ".pdf":
                    text, pages = pdf_text(source)
                elif suffix in {".html", ".htm"}:
                    text = html_text(source)
                elif suffix == ".docx":
                    text = docx_text(source)
                elif suffix in {".txt", ".rtf"}:
                    text = normalize(decode(source.read_bytes()))
                else:
                    continue
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            text_name = f"{package['package_id']}__{len(records) + 1:04d}.txt"
            text_path = output / text_name
            text_path.write_text(text, encoding="utf-8")
            records.append(
                {
                    "package_id": package["package_id"],
                    "stream": package["stream"],
                    "source_package": package["source_name"],
                    "entry": item["entry"],
                    "staged_relative": relative,
                    "sha256": item.get("sha256"),
                    "pages": pages,
                    "text_chars": len(text),
                    "weak_text": suffix == ".pdf" and len(text) < max(200, (pages or 1) * 80),
                    "error": error,
                    "text_relative": str(text_path.relative_to(ROOT)).replace("/", "\\"),
                    "preview": text[:2000],
                }
            )

    index = {
        "schema_version": 1,
        "manifest": str(manifest_path.relative_to(ROOT)).replace("/", "\\"),
        "records": records,
        "statistics": {
            "documents": len(records),
            "weak_text": sum(bool(item["weak_text"]) for item in records),
            "errors": sum(bool(item["error"]) for item in records),
        },
    }
    (output / "text_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(index["statistics"], ensure_ascii=False))


if __name__ == "__main__":
    main()
