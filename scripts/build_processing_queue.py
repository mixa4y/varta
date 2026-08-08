from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import BinaryIO

try:
    from pypdf import PdfReader
except ImportError:  # The queue still works; PDF previews will contain an error.
    PdfReader = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCAN_ROOTS = ("00_INBOX",)
SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".pdf", ".html", ".htm", ".docx", ".doc", ".rtf", ".txt"}
ARCHIVE_SUFFIXES = {".zip", ".rar"}
SIGNATURE_SUFFIXES = {".p7s", ".p7s.2"}
DOC_ID_RE = re.compile(r"DOC_\d{4,}", re.IGNORECASE)
PROCEEDING_RE = re.compile(
    r"(?<![\w/])\d{1,3}(?:-[А-Яа-яІіЇїЄєҐґ]+)?/\d{3}/\d+/\d{2,4}(?![\w/])"
)
MAX_PREVIEW_CHARS = 12_000
MAX_PDF_PAGES = 8
MAX_ZIP_DEPTH = 5
MAX_ZIP_ENTRIES = 10_000


def compound_suffix(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".p7s.2"):
        return ".p7s.2"
    return Path(name).suffix.lower()


def classify_name(name: str) -> str:
    suffix = compound_suffix(name)
    if suffix in SCREENSHOT_SUFFIXES:
        return "screenshot"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in SIGNATURE_SUFFIXES:
        return "signature"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    return "other"


def sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def proceeding_candidates(text: str) -> list[str]:
    return sorted(set(PROCEEDING_RE.findall(text)), key=str.casefold)


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "windows-1251", "cp866"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def html_preview(data: bytes) -> str:
    raw = decode_bytes(data)
    raw = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return normalize_text(html.unescape(raw))[:MAX_PREVIEW_CHARS]


def docx_preview(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"[DOCX_PREVIEW_ERROR: {exc}]"
    xml = re.sub(r"</w:p>|</w:tr>", "\n", xml)
    return normalize_text(html.unescape(re.sub(r"(?s)<[^>]+>", " ", xml)))[:MAX_PREVIEW_CHARS]


def pdf_preview(source: Path | BytesIO) -> tuple[str, int | None, str | None]:
    if PdfReader is None:
        return "", None, "pypdf is not available"
    try:
        reader = PdfReader(source, strict=False)
        chunks: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"[PAGE_TEXT_ERROR: {exc}]")
        return normalize_text(" ".join(chunks))[:MAX_PREVIEW_CHARS], len(reader.pages), None
    except Exception as exc:  # noqa: BLE001
        return "", None, str(exc)


def text_preview(path: Path) -> dict:
    suffix = compound_suffix(path.name)
    try:
        if suffix == ".pdf":
            text, pages, error = pdf_preview(path)
            return {"text": text, "pages": pages, "error": error}
        if suffix in {".html", ".htm"}:
            return {"text": html_preview(path.read_bytes()), "pages": None, "error": None}
        if suffix == ".docx":
            return {"text": docx_preview(path.read_bytes()), "pages": None, "error": None}
        if suffix in {".txt", ".rtf"}:
            return {
                "text": normalize_text(decode_bytes(path.read_bytes()))[:MAX_PREVIEW_CHARS],
                "pages": None,
                "error": None,
            }
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "pages": None, "error": str(exc)}
    return {"text": "", "pages": None, "error": None}


def unsafe_zip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    return pure.is_absolute() or ".." in pure.parts


def inspect_zip_bytes(
    data: bytes,
    container: str,
    depth: int,
    counter: list[int],
) -> list[dict]:
    entries: list[dict] = []
    if depth > MAX_ZIP_DEPTH:
        return [{"container": container, "error": f"maximum ZIP depth {MAX_ZIP_DEPTH} exceeded"}]
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return [{"container": container, "error": str(exc)}]
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            counter[0] += 1
            if counter[0] > MAX_ZIP_ENTRIES:
                entries.append({"container": container, "error": f"ZIP entry limit {MAX_ZIP_ENTRIES} exceeded"})
                break
            item = {
                "container": container,
                "entry": info.filename,
                "depth": depth,
                "kind": classify_name(info.filename),
                "size": info.file_size,
                "compressed_size": info.compress_size,
                "unsafe_path": unsafe_zip_name(info.filename),
                "crc32": f"{info.CRC:08X}",
            }
            entries.append(item)
            if item["kind"] == "archive" and not item["unsafe_path"]:
                try:
                    nested = archive.read(info)
                    entries.extend(
                        inspect_zip_bytes(
                            nested,
                            f"{container}!{info.filename}",
                            depth + 1,
                            counter,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    entries.append({"container": f"{container}!{info.filename}", "error": str(exc)})
    return entries


def inspect_zip(path: Path) -> list[dict]:
    return inspect_zip_bytes(path.read_bytes(), str(path), 0, [0])


def find_7zip() -> Path | None:
    config = {}
    try:
        config = json.loads((ROOT / ".caseflow" / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        pass
    candidates = [
        str(config.get("seven_zip_path", "")),
        os.environ.get("VARTA_7Z", ""),
        os.environ.get("CASEFLOW_7Z", ""),  # legacy compatibility
    ]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            candidates.append(str(Path(base) / "7-Zip" / "7z.exe"))
    candidates.extend(
        [
            r"C:\Program Files\3uToolsV3\files\patchtools\7z-64\7z.exe",
            r"C:\Program Files\3uToolsV3\files\patchtools\7z-32\7z.exe",
            r"C:\Program Files\Lenovo\Lenovo Bootable Generator\7z.exe",
        ]
    )
    command = shutil.which("7z") or shutil.which("7z.exe")
    if command:
        candidates.append(command)
    return next((Path(value).resolve() for value in candidates if value and Path(value).is_file()), None)


def inspect_rar(path: Path) -> list[dict]:
    executable = find_7zip()
    if not executable:
        return [{"container": str(path), "error": "7-Zip is not available for RAR inventory"}]
    result = subprocess.run(
        [str(executable), "l", "-slt", "-ba", "-sccUTF-8", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode not in {0, 1}:
        return [{"container": str(path), "error": (result.stderr or result.stdout)[-1000:]}]
    entries: list[dict] = []
    record: dict[str, str] = {}
    for line in result.stdout.splitlines() + [""]:
        if not line.strip():
            name = record.get("Path", "")
            if record and name and record.get("Folder") != "+":
                try:
                    size = int(record.get("Size", "0") or 0)
                except ValueError:
                    size = 0
                entries.append(
                    {
                        "container": str(path),
                        "entry": name,
                        "depth": 0,
                        "kind": classify_name(name),
                        "size": size,
                        "compressed_size": None,
                        "unsafe_path": unsafe_zip_name(name),
                        "crc32": record.get("CRC", ""),
                    }
                )
            record = {}
            continue
        key, separator, value = line.partition(" = ")
        if separator:
            record[key.strip()] = value.strip()
    return entries[:MAX_ZIP_ENTRIES]


def inspect_archive(path: Path) -> list[dict]:
    return inspect_rar(path) if path.suffix.casefold() == ".rar" else inspect_zip(path)


def infer_doc_id(path: Path) -> str | None:
    for part in reversed(path.parts):
        match = DOC_ID_RE.search(part)
        if match:
            return match.group(0).upper()
    return None


def infer_stream(relative_path: Path) -> str:
    normalized = {part.casefold() for part in relative_path.parts}
    if "01_від_суду".casefold() in normalized:
        return "Від суду"
    if "02_мої_документи".casefold() in normalized:
        return "Мій документ"
    return "Невизначено"


def load_manifest_components() -> dict[str, dict]:
    by_hash: dict[str, dict] = {}
    manifest_dir = ROOT / "03_РЕЄСТР" / "manifests"
    if not manifest_dir.exists():
        return by_hash
    for manifest_path in sorted(manifest_dir.glob("*manifest.json")):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for item in payload.get("files", []):
            digest = str(item.get("sha256", "")).upper()
            if digest:
                by_hash[digest] = {
                    "component": item.get("component"),
                    "doc_id": item.get("doc_id"),
                    "manifest": manifest_path.name,
                }
    return by_hash


def primary_rank(item: dict) -> tuple:
    name = item["name"].casefold()
    manifest_component = str(item.get("manifest_component") or "").casefold()
    technology = any(token in name for token in ("картка", "протокол", "підпис"))
    if "pdf_есітс" in name:
        representation_rank = 0
    elif "конвертовано" in name:
        representation_rank = 1
    elif "оригінал" in name:
        representation_rank = 2
    else:
        representation_rank = 3
    return (
        manifest_component != "основний",
        technology,
        representation_rank,
        item["extension"] not in {".pdf", ".html", ".htm", ".docx"},
        item["name"].casefold(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Рекурсивно інвентаризує провадження, підпапки, вкладені ZIP і скріншоти."
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        dest="scan_roots",
        help="Папка відносно кореня проєкту; параметр можна повторювати.",
    )
    parser.add_argument("--output", type=Path, help="Каталог результату. За замовчуванням — timestamp у tmp.")
    parser.add_argument(
        "--register-rows-json",
        type=Path,
        help="Необов’язковий JSON-витяг аркуша «Документи», створений через artifact-tool.",
    )
    parser.add_argument(
        "--proceeding-folder",
        action="append",
        dest="proceeding_folders",
        help=(
            "Обмежити обхід конкретною папкою провадження першого рівня всередині scan-root. "
            "Параметр можна повторювати."
        ),
    )
    args = parser.parse_args()

    scan_root_names = args.scan_roots or list(DEFAULT_SCAN_ROOTS)
    scan_roots = [(ROOT / name).resolve() for name in scan_root_names]
    for path in scan_roots:
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(path)
        if ROOT.resolve() != path and ROOT.resolve() not in path.parents:
            raise ValueError(f"Scan root is outside the project: {path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_dir = (args.output or ROOT / "tmp" / "processing_queue" / stamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)

    register_by_doc_id: dict[str, dict] = {}
    if args.register_rows_json:
        register_path = args.register_rows_json.resolve()
        register_payload = json.loads(register_path.read_text(encoding="utf-8"))
        for row in register_payload.get("rows", []):
            doc_id = str(row.get("ID документа", "")).strip().upper()
            if doc_id:
                register_by_doc_id[doc_id] = row

    files: list[dict] = []
    zip_entries: list[dict] = []
    doc_groups: dict[str, list[dict]] = defaultdict(list)
    screenshots: list[dict] = []
    manifest_components = load_manifest_components()
    proceeding_filter = {value.casefold() for value in (args.proceeding_folders or [])}

    for scan_root in scan_roots:
        for path in sorted(scan_root.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            relative_to_scan = path.relative_to(scan_root)
            proceeding = relative_to_scan.parts[0] if len(relative_to_scan.parts) > 1 else "__ROOT__"
            if proceeding_filter and proceeding.casefold() not in proceeding_filter:
                continue
            relative_to_proceeding = (
                Path(*relative_to_scan.parts[1:]) if proceeding != "__ROOT__" else relative_to_scan
            )
            kind = classify_name(path.name)
            doc_id = infer_doc_id(path)
            record = {
                "scan_root": str(scan_root.relative_to(ROOT)).replace("/", "\\"),
                "proceeding_folder": proceeding,
                "stream": infer_stream(relative_to_proceeding),
                "relative_subfolder": str(relative_to_proceeding.parent).replace("/", "\\"),
                "relative_path": str(path.relative_to(ROOT)).replace("/", "\\"),
                "absolute_path": str(path),
                "name": path.name,
                "kind": kind,
                "extension": compound_suffix(path.name),
                "size": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                "sha256": sha256_file(path),
                "doc_id": doc_id,
                "needs_review": scan_root.name == "00_INBOX"
                and (proceeding == "__ROOT__" or infer_stream(relative_to_proceeding) == "Невизначено"),
            }
            manifest_meta = manifest_components.get(record["sha256"])
            if manifest_meta:
                record["manifest_component"] = manifest_meta["component"]
                record["manifest_source"] = manifest_meta["manifest"]
            register_row = register_by_doc_id.get(doc_id or "")
            if register_row:
                record["register_stream"] = register_row.get("Потік")
                record["register_proceeding"] = register_row.get("Провадження")
            files.append(record)
            if doc_id:
                doc_groups[doc_id].append(record)
            if kind == "screenshot":
                screenshots.append(record)
            elif kind == "archive":
                zip_entries.extend(inspect_archive(path))

    summary_tasks: list[dict] = []
    for doc_id, group in sorted(doc_groups.items()):
        candidates = [item for item in group if item["kind"] == "document"]
        candidates.sort(key=primary_rank)
        primary = candidates[0] if candidates else None
        preview = text_preview(Path(primary["absolute_path"])) if primary else {"text": "", "pages": None, "error": None}
        proceeding_values = sorted({item["proceeding_folder"] for item in group})
        stream_values = sorted(
            {
                str(item.get("register_stream") or item["stream"])
                for item in group
                if item.get("register_stream") or item.get("stream")
            }
        )
        register_proceedings = sorted(
            {str(item["register_proceeding"]) for item in group if item.get("register_proceeding")}
        )
        detected_proceedings = proceeding_candidates(preview["text"])
        summary_tasks.append(
            {
                "doc_id": doc_id,
                "proceeding_folder": proceeding_values[0] if len(proceeding_values) == 1 else proceeding_values,
                "streams": stream_values,
                "register_proceedings": register_proceedings,
                "document_proceeding_candidates": detected_proceedings,
                "proceeding_resolution_rule": (
                    "user_document_number_is_primary"
                    if "Мій документ" in stream_values
                    else "verify_document_cabinet_and_folder"
                ),
                "primary_source_path": primary["absolute_path"] if primary else None,
                "candidate_source_paths": [item["absolute_path"] for item in candidates],
                "evidence_paths": [item["absolute_path"] for item in group],
                "text_preview": preview["text"],
                "pages": preview["pages"],
                "preview_error": preview["error"],
            }
        )

    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(ROOT),
        "scan_roots": [str(path.relative_to(ROOT)).replace("/", "\\") for path in scan_roots],
        "proceeding_folders": args.proceeding_folders or [],
        "statistics": {
            "files": len(files),
            "archives": sum(item["kind"] == "archive" for item in files),
            "zip_entries": len(zip_entries),
            "screenshots": len(screenshots),
            "document_groups": len(summary_tasks),
            "needs_review": sum(bool(item["needs_review"]) for item in files),
        },
        "files": files,
        "zip_entries": zip_entries,
        "screenshots": screenshots,
    }
    (output_dir / "processing_queue.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "summary_tasks.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": payload["generated_at"],
                "items": summary_tasks,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result = {"output": str(output_dir), **payload["statistics"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
