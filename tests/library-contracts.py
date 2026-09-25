#!/usr/bin/env python3
"""Execute SDK fixtures against the shipped std/vendor, including native providers."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get("DYN", ROOT / "build/dyn")).resolve()
provider = ROOT / "build/sdk-tls-provider.o"
subprocess.run([os.environ.get("CC", "cc"), "-fPIC", "-fno-stack-protector", "-c",
                "tests/stdlib-tls/provider.c", "-o", str(provider)], cwd=ROOT, check=True)
sdl = subprocess.run(["pkg-config", "--exists", "sdl3"], check=False).returncode == 0
for package in sorted((ROOT / "tests").glob("sdk-*")):
    if not (package / "main.dyn").exists():
        continue
    if package.name == "sdk-sdl3" and not sdl:
        if os.environ.get("DYN_REQUIRE_ALL") == "1": raise SystemExit("SDL3 required for release checks")
        subprocess.run([str(DYN), "check", str(package), "--quiet"], cwd=ROOT, check=True)
        print("SKIP sdk-sdl3 runtime: native SDL3 unavailable (semantic check passed)", flush=True)
        continue
    links = ["--link", str(provider)] if package.name == "sdk-tls" else []
    for mode in ([], ["--release"]):
        output = ROOT / "build" / (package.name + ("-release" if mode else "-debug"))
        subprocess.run([str(DYN), "build", str(package), "--no-cache", "--quiet",
                        "--output", str(output), *mode, *links], cwd=ROOT, check=True)
        subprocess.run([str(output)], cwd=ROOT, check=True, timeout=30)
    print(f"PASS {package.name}", flush=True)
