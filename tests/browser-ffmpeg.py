#!/usr/bin/env python3
"""Pinned real FFmpeg Wasm + Dyn media pipeline, in both compiler modes."""
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=os.environ.get('DYN',str(ROOT/'build/dyn'))
subprocess.run([sys.executable,str(ROOT/'compiler/tools/setup-browser-ffmpeg.py')],cwd=ROOT,check=True,timeout=180)
with tempfile.TemporaryDirectory(prefix='dyn-browser-ffmpeg-') as directory:
 output=Path(directory)/'filter.wasm'
 for flags in ([],['--release']):
  subprocess.run([DYN,'build',str(ROOT/'projects/browser-video'),'--target','wasm32-browser','--shared','--output',str(output),*flags],cwd=ROOT,check=True,timeout=120)
  subprocess.run(['node',str(ROOT/'tests/browser-ffmpeg.mjs'),str(output)],cwd=ROOT,check=True,timeout=90)
