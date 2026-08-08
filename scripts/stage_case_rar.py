from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    return not (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in pure.parts
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely stage one RAR file with system bsdtar.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id", default="MINE_0006")
    args = parser.parse_args()
    archive = (ROOT / args.archive).resolve() if not args.archive.is_absolute() else args.archive.resolve()
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    allowed = (ROOT / "tmp" / "staging").resolve()
    if allowed not in output.parents:
        raise ValueError("RAR staging output must stay under tmp/staging")
    if output.exists():
        if allowed not in output.parents:
            raise ValueError("Unsafe existing output")
        shutil.rmtree(output)
    raw = output / "raw"
    content = output / "content"
    raw.mkdir(parents=True)
    content.mkdir()

    listing = subprocess.run(
        ["tar", "-tf", str(archive)], capture_output=True, check=True
    ).stdout
    decoded = None
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            decoded = listing.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        decoded = listing.decode("utf-8", errors="replace")
    members = [line.strip() for line in decoded.splitlines() if line.strip()]
    unsafe = [name for name in members if not safe_member(name)]
    if unsafe:
        raise ValueError(f"Unsafe RAR paths: {unsafe}")
    subprocess.run(["tar", "-xf", str(archive), "-C", str(raw)], check=True)
    for path in raw.rglob("*"):
        if path.resolve() != raw and raw not in path.resolve().parents:
            raise ValueError(f"Extracted path escapes staging: {path}")
    files = [path for path in raw.rglob("*") if path.is_file()]
    if not files:
        raise ValueError("RAR produced no files")
    common_root = raw
    first_parts = {path.relative_to(raw).parts[0] for path in files}
    if len(first_parts) == 1 and (raw / next(iter(first_parts))).is_dir():
        common_root = raw / next(iter(first_parts))
    records = []
    for source in sorted(files, key=lambda path: str(path).casefold()):
        inside = source.relative_to(common_root)
        target = content / inside
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records.append(
            {
                "entry": str(inside).replace("\\", "/"),
                "size": target.stat().st_size,
                "sha256": sha256(target),
                "staged_relative": str(target.relative_to(ROOT)).replace("/", "\\"),
                "depth": 0,
                "unsafe_path": False,
            }
        )
    shutil.rmtree(raw)
    result = {
        "package_id": args.package_id,
        "stream": "02_МОЇ_ДОКУМЕНТИ",
        "source_relative": str(archive.relative_to(ROOT)).replace("/", "\\"),
        "source_name": archive.name,
        "source_sha256": sha256(archive),
        "records": records,
    }
    manifest = output / "rar_staging_manifest.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest), "files": len(records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
