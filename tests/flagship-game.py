#!/usr/bin/env python3
"""Flagship game: headless Breakout with a per-frame arena, deterministic on every build."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
GAME = ROOT / 'tests/flagship-game'
with tempfile.TemporaryDirectory(prefix='dyn-flagship-game-') as temporary:
    work = Path(temporary)
    outputs = []
    for release in (False, True):
        program = work / ('game-release' if release else 'game-debug')
        subprocess.run([DYN, 'build', str(GAME), '--no-cache', '--quiet', '--output', str(program)] +
                       (['--release'] if release else []), check=True, timeout=120)
        outputs.append(subprocess.run([str(program)], check=True, capture_output=True, text=True,
                                      timeout=60).stdout)
    assert outputs[0] == outputs[1], outputs
    result = dict(line.split() for line in outputs[0].splitlines())
    assert result['score'] == '50' and result['lives'] != '0', result
    # The draw list for a full board is about 1 KiB; doubling growth stays bounded.
    assert int(result['frame_peak']) <= 4096, result
    # The core has no OS dependencies: it builds for the browser and other hosts.
    subprocess.run([DYN, 'build', str(GAME / 'breakout'), '--target', 'wasm32-browser', '--shared', '--quiet',
                    '--no-cache', '--output', str(work / 'breakout.wasm')], check=True, timeout=120)
    assert (work / 'breakout.wasm').read_bytes()[:4] == b'\0asm'
    for target in ('aarch64-linux', 'x86_64-windows', 'aarch64-macos'):
        subprocess.run([DYN, 'build', str(GAME), '--target', target, '--quiet', '--no-cache',
                        '--output', str(work / f'game-{target}')], check=True, timeout=120)
print(f"PASS flagship Breakout: cleared in {result['frames']} frames, identical debug/release frames, "
      'bounded frame arena, wasm32-browser core and cross-target builds')
