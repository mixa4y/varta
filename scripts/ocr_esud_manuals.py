from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp" / "pydeps"))

from PIL import Image, ImageFilter, ImageOps  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from winocr import recognize_pil_sync  # noqa: E402


BASE = ROOT / "tmp" / "pdfs" / "esud_manuals"
RENDERED = BASE / "rendered"
FILES = [
    ("electronic_cabinet", ROOT / "Інструкція_користувача_підсистеми_Електронний_кабінет.pdf"),
    ("electronic_court", ROOT / "Інструкція_користувача_підсистеми_Електронний_суд.pdf"),
]


def prepare(image: Image.Image) -> Image.Image:
    result = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    result = result.resize(
        (round(result.width * 1.35), round(result.height * 1.35)),
        Image.Resampling.LANCZOS,
    )
    return result.filter(ImageFilter.SHARPEN).convert("RGBA")


def main() -> None:
    summary = []
    for slug, pdf_path in FILES:
        reader = PdfReader(str(pdf_path))
        image_folder = RENDERED / slug
        output_folder = BASE / "ocr" / slug
        output_folder.mkdir(parents=True, exist_ok=True)
        pages = []
        combined = []
        for page_no in range(1, len(reader.pages) + 1):
            image_path = image_folder / f"page_{page_no:03d}.png"
            if image_path.exists():
                result = recognize_pil_sync(prepare(Image.open(image_path)), "ru")
                text = "\n".join(line.get("text", "") for line in result.get("lines", []))
                source = "windows_ocr_ru"
            else:
                text = reader.pages[page_no - 1].extract_text() or ""
                source = "pdf_text_layer"
            page_path = output_folder / f"page_{page_no:03d}.txt"
            page_path.write_text(text, encoding="utf-8")
            pages.append(
                {
                    "page": page_no,
                    "source": source,
                    "characters": len(text),
                    "lines": len(text.splitlines()),
                    "file": page_path.name,
                }
            )
            combined.append(f"\n\n===== СТОРІНКА {page_no} =====\n{text}")
            print(f"{slug}: {page_no}/{len(reader.pages)} chars={len(text)}", flush=True)
        combined_path = BASE / "ocr" / f"{slug}__ocr_full.txt"
        combined_path.write_text("".join(combined), encoding="utf-8")
        summary.append(
            {
                "slug": slug,
                "pages": len(pages),
                "characters": sum(page["characters"] for page in pages),
                "weak_pages": [page["page"] for page in pages if page["characters"] < 250],
                "page_records": pages,
                "combined": combined_path.name,
            }
        )
    index = BASE / "ocr" / "ocr_index.json"
    index.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
