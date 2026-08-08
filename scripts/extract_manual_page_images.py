from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp" / "pydeps"))

from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402


OUTPUT = ROOT / "tmp" / "pdfs" / "esud_manuals" / "rendered"
FILES = [
    ("electronic_cabinet", ROOT / "Інструкція_користувача_підсистеми_Електронний_кабінет.pdf"),
    ("electronic_court", ROOT / "Інструкція_користувача_підсистеми_Електронний_суд.pdf"),
]


def main() -> None:
    report = []
    for slug, source in FILES:
        reader = PdfReader(str(source))
        folder = OUTPUT / slug
        folder.mkdir(parents=True, exist_ok=True)
        page_paths = []
        page_info = []
        for page_no, page in enumerate(reader.pages, 1):
            images = list(page.images)
            candidates = []
            for image_file in images:
                image = image_file.image.convert("RGB")
                candidates.append((image.width * image.height, image_file.name, image))
            if not candidates:
                page_info.append({"page": page_no, "images": 0, "saved": None})
                continue
            candidates.sort(key=lambda item: item[0], reverse=True)
            _, image_name, selected = candidates[0]
            target = folder / f"page_{page_no:03d}.png"
            selected.save(target, format="PNG", optimize=True)
            page_paths.append(target)
            page_info.append(
                {
                    "page": page_no,
                    "images": len(images),
                    "selected_source": image_name,
                    "width": selected.width,
                    "height": selected.height,
                    "saved": target.name,
                }
            )

        contact_paths = []
        for batch_no in range(0, len(page_paths), 6):
            batch = page_paths[batch_no : batch_no + 6]
            thumb_width = 520
            label_height = 42
            thumbs = []
            for page_path in batch:
                image = Image.open(page_path).convert("RGB")
                height = round(image.height * thumb_width / image.width)
                image.thumbnail((thumb_width, height), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (thumb_width, image.height + label_height), "white")
                canvas.paste(image, ((thumb_width - image.width) // 2, label_height))
                draw = ImageDraw.Draw(canvas)
                draw.text((14, 10), page_path.stem.replace("page_", "Сторінка "), fill="black")
                thumbs.append(canvas)
            columns = 2
            rows = (len(thumbs) + columns - 1) // columns
            cell_height = max(image.height for image in thumbs)
            sheet = Image.new("RGB", (thumb_width * columns, cell_height * rows), "#d9d9d9")
            for index, image in enumerate(thumbs):
                x = (index % columns) * thumb_width
                y = (index // columns) * cell_height
                sheet.paste(image, (x, y))
            contact = OUTPUT / f"{slug}__contact_{batch_no // 6 + 1:02d}.jpg"
            sheet.save(contact, format="JPEG", quality=90, optimize=True)
            contact_paths.append(contact.name)

        report.append(
            {
                "slug": slug,
                "source": source.name,
                "pages": len(reader.pages),
                "page_info": page_info,
                "contact_sheets": contact_paths,
            }
        )
    report_path = OUTPUT / "render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
