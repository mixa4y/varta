from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MAX_DEPTH = 5
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def unsafe_name(name: str) -> bool:
    pure = PurePosixPath(name.replace("\\", "/"))
    return pure.is_absolute() or ".." in pure.parts


def safe_segment(value: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip(" ._")
    return value[:120] or "unnamed"


def extract_zip_bytes(
    data: bytes,
    destination: Path,
    source_label: str,
    records: list[dict],
    total: list[int],
    depth: int = 0,
) -> None:
    if depth > MAX_DEPTH:
        records.append({"container": source_label, "depth": depth, "error": "maximum ZIP depth exceeded"})
        return
    with zipfile.ZipFile(BytesIO(data)) as archive:
        for index, info in enumerate(archive.infolist(), start=1):
            if info.is_dir():
                continue
            record = {
                "container": source_label,
                "entry": info.filename,
                "depth": depth,
                "size": info.file_size,
                "unsafe_path": unsafe_name(info.filename),
            }
            if record["unsafe_path"]:
                record["error"] = "unsafe archive path"
                records.append(record)
                continue
            if info.file_size > MAX_ENTRY_BYTES:
                record["error"] = "entry size limit exceeded"
                records.append(record)
                continue
            total[0] += info.file_size
            if total[0] > MAX_TOTAL_BYTES:
                record["error"] = "total uncompressed size limit exceeded"
                records.append(record)
                return
            payload = archive.read(info)
            original = PurePosixPath(info.filename.replace("\\", "/"))
            safe_parts = [safe_segment(part) for part in original.parts]
            output = destination.joinpath(*safe_parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                output = output.with_name(f"{output.stem}__dup_{index:02d}{output.suffix}")
            output.write_bytes(payload)
            record["sha256"] = sha256(payload)
            record["staged_relative"] = str(output.relative_to(ROOT)).replace("/", "\\")
            records.append(record)
            if output.suffix.casefold() == ".zip":
                nested_destination = output.with_suffix("")
                nested_destination = nested_destination.with_name(nested_destination.name + "__nested")
                nested_destination.mkdir(parents=True, exist_ok=True)
                try:
                    extract_zip_bytes(
                        payload,
                        nested_destination,
                        f"{source_label}!{info.filename}",
                        records,
                        total,
                        depth + 1,
                    )
                except Exception as exc:  # noqa: BLE001
                    records.append(
                        {
                            "container": f"{source_label}!{info.filename}",
                            "depth": depth + 1,
                            "error": str(exc),
                        }
                    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely extract all ZIP packages of one proceeding to staging.")
    parser.add_argument("case_folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    case_folder = (ROOT / args.case_folder).resolve()
    output = (ROOT / args.output).resolve()
    if ROOT.resolve() not in case_folder.parents or ROOT.resolve() not in output.parents:
        raise ValueError("paths must remain inside project")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)

    packages: list[dict] = []
    streams = [("01_ВІД_СУДУ", "COURT"), ("02_МОЇ_ДОКУМЕНТИ", "MINE")]
    for stream_name, prefix in streams:
        stream = case_folder / stream_name
        if not stream.exists():
            continue
        for number, archive_path in enumerate(
            sorted(stream.rglob("*.zip"), key=lambda item: str(item).casefold()), start=1
        ):
            package_id = f"{prefix}_{number:04d}"
            package_dir = output / package_id
            package_dir.mkdir()
            archive_copy = package_dir / safe_segment(archive_path.name)
            data = archive_path.read_bytes()
            archive_copy.write_bytes(data)
            content_dir = package_dir / "content"
            content_dir.mkdir()
            records: list[dict] = []
            total = [0]
            extract_zip_bytes(data, content_dir, archive_path.name, records, total)
            packages.append(
                {
                    "package_id": package_id,
                    "stream": stream_name,
                    "source_relative": str(archive_path.relative_to(ROOT)).replace("/", "\\"),
                    "source_name": archive_path.name,
                    "source_sha256": sha256(data),
                    "staged_archive_relative": str(archive_copy.relative_to(ROOT)).replace("/", "\\"),
                    "records": records,
                    "uncompressed_bytes": total[0],
                }
            )

    manifest = {
        "schema_version": 1,
        "case_folder": str(args.case_folder).replace("/", "\\"),
        "output": str(output.relative_to(ROOT)).replace("/", "\\"),
        "packages": packages,
    }
    (output / "staging_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "packages": len(packages),
                "files": sum(len(item["records"]) for item in packages),
                "errors": sum(
                    "error" in record for item in packages for record in item["records"]
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
