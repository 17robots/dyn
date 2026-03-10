#!/usr/bin/env bash
set -euo pipefail

project_root="${1:-.}"
iterations="${2:-5}"

if ! [[ "${iterations}" =~ ^[0-9]+$ ]] || [[ "${iterations}" -lt 1 ]]; then
    echo "iterations must be a positive integer" >&2
    exit 1
fi

python - "${project_root}" "${iterations}" <<'PY'
import statistics
import subprocess
import sys
import time

project_root = sys.argv[1]
iterations = int(sys.argv[2])

stages = [
    ("resolve", ["cargo", "run", "--quiet", "--", "resolve", project_root]),
    ("parse", ["cargo", "run", "--quiet", "--", "parse", project_root]),
    ("hir", ["cargo", "run", "--quiet", "--", "hir", project_root]),
    ("mir", ["cargo", "run", "--quiet", "--", "mir", project_root]),
    ("build", ["cargo", "run", "--quiet", "--", "build", project_root]),
]

print(f"benchmark target={project_root!r} iterations={iterations}")
for stage_name, command in stages:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        if result.returncode != 0:
            sys.stderr.write(f"stage {stage_name!r} failed\n")
            if result.stdout:
                sys.stderr.write("stdout:\n")
                sys.stderr.write(result.stdout)
            if result.stderr:
                sys.stderr.write("stderr:\n")
                sys.stderr.write(result.stderr)
            raise SystemExit(result.returncode)
        samples.append(elapsed)

    mean = statistics.mean(samples)
    median = statistics.median(samples)
    low = min(samples)
    high = max(samples)
    print(
        f"{stage_name:8s} avg={mean:6.3f}s median={median:6.3f}s min={low:6.3f}s max={high:6.3f}s"
    )
PY
