from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Print selected OCR manual pages as UTF-8.")
    parser.add_argument("manual", choices=("electronic_cabinet", "electronic_court"))
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1] / "tmp" / "pdfs" / "esud_manuals" / "ocr" / args.manual
    for page_no in range(args.start, args.end + 1):
        path = root / f"page_{page_no:03d}.txt"
        print(f"\n===== PAGE {page_no} =====\n")
        print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
