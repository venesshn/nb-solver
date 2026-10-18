"""Unpack TextAssets from the UnityFS bundles shipped in the game client."""

from __future__ import annotations

import sys
from pathlib import Path

import UnityPy

UNITYFS_MAGIC = b"UnityFS"

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "extracted"


def is_bundle(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as fh:
        return fh.read(len(UNITYFS_MAGIC)) == UNITYFS_MAGIC


def unpack(path: Path, out_dir: Path) -> list[tuple[str, str, int]]:
    """Return (object_type, name, size) for every object written out."""
    env = UnityPy.load(str(path))
    written: list[tuple[str, str, int]] = []

    for obj in env.objects:
        try:
            data = obj.read()
        except Exception as exc:  # noqa: BLE001 - UnityPy raises arbitrary errors on malformed objects
            print(f"  ! {path.name}: cannot read {obj.type.name}: {exc}", file=sys.stderr)
            continue

        name = getattr(data, "m_Name", "") or f"{obj.type.name}_{obj.path_id}"

        if obj.type.name == "TextAsset":
            script = getattr(data, "m_Script", None)
            if script is None:
                continue
            payload = script.encode("utf-8", "surrogateescape") if isinstance(script, str) else bytes(script)
            target = out_dir / f"{path.stem}__{name}.bin"
            target.write_bytes(payload)
            written.append((obj.type.name, name, len(payload)))
        else:
            written.append((obj.type.name, name, 0))

    return written


def main() -> int:
    if not RAW_DIR.is_dir():
        print(f"missing {RAW_DIR}", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bundles = sorted(p for p in RAW_DIR.iterdir() if is_bundle(p))
    print(f"bundles: {len(bundles)}\n")

    type_counts: dict[str, int] = {}
    for bundle in bundles:
        results = unpack(bundle, OUT_DIR)
        texts = [r for r in results if r[0] == "TextAsset"]
        for obj_type, _, _ in results:
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        if texts:
            print(f"{bundle.name}")
            for _, name, size in texts:
                print(f"    {name:<40} {size:>9,} bytes")

    print("\nobject types across all bundles:")
    for obj_type, count in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {obj_type:<24} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
