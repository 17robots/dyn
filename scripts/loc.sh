#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"

python - "$root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
if not root.exists():
    raise SystemExit(f"path does not exist: {root}")

exclude_dir_names = {"target", ".git", ".jj", "node_modules", "__pycache__"}
exclude_dir_prefixes = ("tmp_",)
include_roots = {"src", "std"}
include_exts = {".rs", ".dyn"}

total = 0
files = []

for path in root.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(root)
    if not rel.parts:
        continue
    if rel.parts[0] not in include_roots:
        continue
    if path.suffix not in include_exts:
        continue

    parent_parts = rel.parts[:-1]
    if any(part in exclude_dir_names for part in parent_parts):
        continue
    if any(part.startswith(exclude_dir_prefixes) for part in parent_parts):
        continue

    with path.open("rb") as handle:
        line_count = handle.read().count(b"\n") + 1
    total += line_count
    files.append((line_count, rel.as_posix()))

print(f"source_loc={total}")
print("largest_files:")
for line_count, rel in sorted(files, reverse=True)[:10]:
    print(f"  {line_count:6d} {rel}")
PY
