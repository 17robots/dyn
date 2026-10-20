#!/usr/bin/env python3
"""Stage release kernels, then measure them on the target hardware.

The host C builds supply checksums only, never cross-machine timing ratios.
WASI timings use Node and include process startup and module compilation.
Browser timings use Playwright Chromium, fresh pages and exported checksums.
RISC-V can use --qemu qemu-riscv64; reports label emulated results explicitly.
Reports contain every sample, executable hashes, and host/runtime metadata.
"""
import argparse
import hashlib
import json
import os
import base64
from contextlib import ExitStack
import re
import tempfile
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TARGETS = ['x86_64-linux', 'aarch64-linux', 'x86_64-macos',
           'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'riscv64-linux',
           'wasm32-wasi', 'wasm32-browser']
WASI_RUNNER = """const {WASI}=require('node:wasi'),fs=require('node:fs');
(async()=>{const wasi=new WASI({version:'preview1',args:['benchmark'],returnOnExit:true});
const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[2]),
{wasi_snapshot_preview1:wasi.wasiImport}); process.exitCode=wasi.start(instance);
})().catch(e=>{console.error(e);process.exit(1)});
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True,
                          text=True, timeout=300).stdout.strip()


def stage(args):
    compiler = args.dyn.resolve()
    args.stage.mkdir(parents=True, exist_ok=True)
    targets = args.target or TARGETS
    manifest = {'schema': 1, 'compiler_sha256': digest(compiler), 'targets': {},
                'revision': os.environ.get('GITHUB_SHA'),
                'checksum_oracle': execute([args.cc, '--version']).splitlines()[0]}
    for name in args.kernels or sorted(p.name for p in HERE.iterdir() if (p/'main.dyn').exists()):
        source = HERE/name
        oracle = args.stage/(name+'-oracle')
        subprocess.run([args.cc, '-O2', str(source/'main.c'), '-o', str(oracle)], check=True)
        expected = execute([oracle.resolve()])
        oracle.unlink()
        for target in targets:
            directory = args.stage/target
            directory.mkdir(exist_ok=True)
            suffix = '.wasm' if target.startswith('wasm32-') else '.exe' if target.endswith('windows') else ''
            output = directory/(name+suffix)
            with tempfile.TemporaryDirectory(prefix='dyn-browser-bench-') as temporary:
                module = source
                flags = []
                if target == 'wasm32-browser':
                    # Browser modules expose a checksum instead of requiring std/io.
                    text = (source/'main.dyn').read_text().replace('use "std/io"', '')
                    if text.count('fn main() {') != 1:
                        raise SystemExit(f'{name}: unsupported browser entry point')
                    text = text.replace('fn main() {', 'pub fn checksum() u64 {')
                    text, count = re.subn(r'  _ = io.println\(io.stdout\(\), "{}", (.+)\)\n\}\s*$',
                                         r'  return #cast(u64) (\1)\n}\n', text)
                    if count != 1:
                        raise SystemExit(f'{name}: unsupported checksum output')
                    module = Path(temporary)
                    (module/'main.dyn').write_text(text)
                    flags = ['--shared']
                subprocess.run([str(compiler), 'build', str(module), '--release', '--quiet',
                                '--no-cache', '--target', target, '--output', str(output), *flags], check=True)
            manifest['targets'].setdefault(target, []).append({
                'kernel': name, 'file': output.name, 'expected': expected,
                'source_sha256': digest(source/'main.dyn'),
                'sha256': digest(output), 'bytes': output.stat().st_size})
    (args.stage/'wasi.cjs').write_text(WASI_RUNNER)
    (args.stage/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    shutil.copy2(__file__, args.stage/'runtime.py')


def measure(args):
    manifest = json.loads((args.run/'manifest.json').read_text())
    target = args.target[0]
    wasi = target == 'wasm32-wasi'
    browser_target = target == 'wasm32-browser'
    report = {'schema': 1, 'target': target, 'host': platform.platform(),
              'machine': platform.machine(), 'processor': platform.processor(),
              'runner': os.environ.get('RUNNER_NAME'),
              'revision': manifest.get('revision'), 'python': platform.python_version(),
              'compiler_sha256': manifest['compiler_sha256'],
              'timing': 'wall clock including process startup' +
                        (' and WASI module compilation' if wasi else ''),
              'execution': 'QEMU emulation' if args.qemu else 'native hardware',
              'warmups': args.warmups, 'samples': args.samples, 'kernels': []}
    if wasi:
        report['runtime'] = execute([args.node, '--version'])
    if args.qemu:
        report['runtime'] = execute([args.qemu, '--version']).splitlines()[0]
    with ExitStack() as stack:
        browser = None
        if browser_target:
            from playwright.sync_api import sync_playwright
            playwright = stack.enter_context(sync_playwright())
            browser = playwright.chromium.launch()
            stack.callback(browser.close)
            report['runtime'] = 'Chromium '+browser.version
            report['timing'] = 'wall clock including fresh browser page, module compilation and checksum; browser launch excluded'
        measure_kernels(args, manifest, target, wasi, browser, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')


def measure_kernels(args, manifest, target, wasi, browser, report):
    for item in manifest['targets'][target]:
        binary = (args.run/target/item['file']).resolve()
        if digest(binary) != item['sha256']:
            raise SystemExit(f'{binary}: executable hash mismatch')
        if not wasi and not browser:
            binary.chmod(binary.stat().st_mode | 0o111)
        command = [args.node, str((args.run/'wasi.cjs').resolve()), binary] if wasi else [binary]
        if args.qemu:
            command = [args.qemu, *command]
        encoded = base64.b64encode(binary.read_bytes()).decode() if browser else None
        samples = []
        for index in range(args.warmups + args.samples):
            start = time.perf_counter()
            if browser:
                page = browser.new_page()
                try:
                    actual = page.evaluate('''async bytes => {
                      const data=Uint8Array.from(atob(bytes), c=>c.charCodeAt(0));
                      const {instance,module}=await WebAssembly.instantiate(data,{});
                      if (WebAssembly.Module.imports(module).length) throw Error('unexpected imports');
                      instance.exports.dyn_initialize();
                      return BigInt.asUintN(64,instance.exports.checksum()).toString();
                    }''', encoded)
                finally:
                    page.close()
            else:
                actual = execute(command)
            elapsed = time.perf_counter()-start
            if actual != item['expected']:
                raise SystemExit(f"{item['kernel']}: checksum {actual!r}, expected {item['expected']!r}")
            if index >= args.warmups:
                samples.append(elapsed)
        result = dict(item, seconds=samples, median_seconds=statistics.median(samples))
        report['kernels'].append(result)
        print(f"{item['kernel']}: {result['median_seconds']:.6f} s, {item['bytes']} bytes, checksum {actual}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--stage', type=Path)
    mode.add_argument('--run', type=Path)
    parser.add_argument('--dyn', type=Path, default=ROOT/'build/dyn-release')
    parser.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    parser.add_argument('--target', action='append', choices=TARGETS)
    parser.add_argument('--samples', type=int, default=7)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--node', default='node')
    parser.add_argument('--qemu', help='QEMU user-mode executable; timings are explicitly labelled emulated')
    parser.add_argument('--output', type=Path, default=Path('benchmark.json'))
    parser.add_argument('kernels', nargs='*')
    args = parser.parse_args()
    if args.samples < 1 or args.warmups < 0:
        parser.error('samples must be positive and warmups nonnegative')
    if args.run and (not args.target or len(args.target) != 1):
        parser.error('--run requires exactly one --target')
    (stage if args.stage else measure)(args)


if __name__ == '__main__':
    main()
