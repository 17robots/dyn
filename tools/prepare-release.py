#!/usr/bin/env python3
"""Assemble a release only from successful, checksum-verified CI evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(version, evidence, native, output):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', version):
        raise ValueError('Invalid release version')
    # Refuse reuse: a failed invocation cannot leave an older publishable bundle.
    output.mkdir(parents=True, exist_ok=False)
    try:
        report = json.loads((evidence/'release-check/report.json').read_text())
        package = json.loads((evidence/'dist/package-validation.json').read_text())
        if report['status'] != 'passed' or not report['stages'] or any(s['status'] != 'passed' for s in report['stages']):
            raise ValueError('Standalone compiler release validation must pass')
        if package['status'] != 'passed' or package['manifest']['version'] != 'dyn '+version:
            raise ValueError('SDK validation/version does not match release')
        sdk_name = f'dyn-{version}-linux-x86_64.tar.gz'
        if package['archive'] != sdk_name:
            raise ValueError('Unexpected SDK archive/platform')
        artifacts = report['artifacts']
        source = package['runtime_sources']
        if source['archive'] != f'dyn-{version}-runtime-sources.tar.gz' or artifacts.get('build/release-check/artifacts/'+source['archive']) != source['sha256']:
            raise ValueError('Missing matching runtime sources')
        sdk_key = 'build/release-check/artifacts/'+sdk_name
        if artifacts.get(sdk_key) != package['sha256']:
            raise ValueError('SDK evidence hash mismatch')
        for relative, expected in artifacts.items():
            name = Path(relative).name
            if relative != 'build/release-check/artifacts/'+name:
                raise ValueError('Unexpected artifact path')
            source = evidence/'release-check/artifacts'/name
            if sha(source) != expected:
                raise ValueError('Artifact hash mismatch: '+name)
            target = name.replace('-linux-x86_64.tar.gz', '-linux-x86_64-glibc2.39.tar.gz') if name == sdk_name else name
            shutil.copy2(source, output/target)
        counts = {}
        for target, expected_count in [('windows',14), ('macos',14), ('aarch64',12)]:
            path = native/f'native-{target}.json'
            result = json.loads(path.read_text())
            probes = result['probes']
            if result['target'] != target or result['status'] != 'passed' or len(probes) != expected_count or any(p['status'] != 'passed' for p in probes):
                raise ValueError('Native evidence incomplete: '+target)
            counts[target] = len(probes)
            shutil.copy2(path, output/path.name)
        for source, name in [(evidence/'release-check/report.json','linux-release-qualification.json'),
                             (evidence/'dist/package-validation.json','sdk-qualification.json'),
                             (ROOT/'LICENSE','LICENSE.txt'),
                             (ROOT/'THIRD_PARTY_NOTICES.md','THIRD_PARTY_NOTICES.md')]:
            shutil.copy2(source,output/name)
        sdk = output/f'dyn-{version}-linux-x86_64-glibc2.39.tar.gz'
        config = f'''# Linux x86-64, glibc 2.39+; LLVM, Tree-sitter and LLD included.
[tools."github:17robots/dyn"]
version = "{version}"
prerelease = true
asset_pattern = 'dyn-{{{{ version }}}}-{{{{ os() }}}}-{{{{ arch(x64="x86_64", arm64="aarch64") }}}}-glibc2.39.tar.gz'
strip_components = 1
bin_path = "bin"
checksum = "sha256:{sha(sdk)}"
'''
        (output/'mise.toml').write_text(config)
        notes = f'''# Dyn {version}

Linux x86-64 SDK, built on Ubuntu 24.04 with LLVM 19.
Standalone compiler regression and package validation passed. Native debug/release probes passed:
Windows {counts['windows']}, macOS Apple Silicon {counts['macos']}, Linux ARM {counts['aarch64']}.
These target tests do not provide Windows/macOS compiler executables.

LLVM 19, LLD 19 and Tree-sitter 0.25.8 are bundled. Requires glibc 2.39+
(e.g. Ubuntu 24.04 or current Arch Linux). Use the attached `mise.toml`
with `mise install` and `mise exec -- dyn version`.
See [installation instructions](https://github.com/17robots/dyn/blob/v{version}/README.md).

Source-available under the attached Dyn license; commercial application development allowed.
Compiler redistribution/modification restrictions apply. See LICENSE.txt for full terms.
'''
        (output/'RELEASE-NOTES.md').write_text(notes)
        (output/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(output.iterdir())))
    except BaseException:
        shutil.rmtree(output)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.version, args.evidence, args.native, args.output)
