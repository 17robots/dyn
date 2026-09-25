#!/usr/bin/env bash
set -euo pipefail
python3 compiler/tools/build.py all
./build/dyn build projects/memory-tour --output build/memory-tour --quiet
./build/memory-tour
printf '%s\n' 'Dyn ready. Read docs/agent-guide.md. Build with ./build/dyn build YOUR_MODULE.'
