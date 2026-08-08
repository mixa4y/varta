from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("extra", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.base.read_text(encoding="utf-8"))
    packages = list(payload.get("packages", []))
    known = {item["package_id"] for item in packages}
    for path in args.extra:
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["package_id"] in known:
            raise ValueError(f"Duplicate package_id: {item['package_id']}")
        packages.append(item)
        known.add(item["package_id"])
    payload["packages"] = packages
    payload["combined_from"] = [str(args.base), *[str(path) for path in args.extra]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "packages": len(packages)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
