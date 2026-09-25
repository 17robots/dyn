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


def prepare(version, evidence, native, output, hosts):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', version):
        raise ValueError('Invalid release version')
    # Refuse reuse: a failed invocation cannot leave an older publishable bundle.
    output.mkdir(parents=True, exist_ok=False)
    try:
        public = output/'public'; public.mkdir()
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
            shutil.copy2(source, public/target)
        counts = {}
        for target, expected_count in [('windows',14), ('macos',14), ('aarch64',12)]:
            path = native/f'native-{target}.json'
            result = json.loads(path.read_text())
            probes = result['probes']
            if result['target'] != target or result['status'] != 'passed' or len(probes) != expected_count or any(p['status'] != 'passed' for p in probes):
                raise ValueError('Native evidence incomplete: '+target)
            counts[target] = len(probes)

        sdk = public/f'dyn-{version}-linux-x86_64-glibc2.39.tar.gz'
        platforms = {'linux-x64': sdk}
        for host, key, extension in [('macos-aarch64','macos-arm64','tar.gz'), ('windows-x86_64','windows-x64','zip')]:
            qualification = json.loads((hosts/f'package-{host}.json').read_text())
            name = f'dyn-{version}-{host}.{extension}'
            if (qualification['status'] != 'passed' or qualification['version'] != version or
                qualification['platform'] != host or qualification['archive'] != name or
                qualification.get('mise') is not True or qualification.get('isolated_path') is not True):
                raise ValueError('Host package qualification incomplete: '+host)
            source = hosts/name
            if sha(source) != qualification['sha256']:
                raise ValueError('Host archive hash mismatch: '+host)
            shutil.copy2(source,public/name)
            platforms[key] = public/name
        config = f'''[tools."github:17robots/dyn"]
version = "{version}"
prerelease = true
strip_components = 1
bin_path = "bin"

[tools."github:17robots/dyn".platforms]
'''+''.join(f'{key} = {{ asset_pattern = "{path.name}", checksum = "sha256:{sha(path)}" }}\n' for key,path in platforms.items())
        (output/'mise.toml').write_text(config)
        checksums = ''.join(f'{sha(p)}  public/{p.name}\n' for p in sorted(public.iterdir()))
        (output/'SHA256SUMS').write_text(checksums)
        notes = f'''# Dyn {version}

Download the archive for your system, extract it, and add its `bin` directory to PATH.
The compiler, standard library, runtime and host linker are included.

| Download | Requirements |
| --- | --- |
| Linux x64 | glibc 2.39+ (Ubuntu 24.04 or current Arch) |
| Windows x64 | Windows 10/11 or Server 2022; no MSYS2 installation needed |
| macOS Apple Silicon | macOS 15+; no Homebrew or developer tools needed |

The runtime-sources archive is corresponding source for Linux's bundled GNU libraries;
it is not needed to run Dyn. Licenses and dependency notices are inside each SDK.
macOS binaries are ad-hoc signed, not notarized. Optional native providers remain external.

To install with mise, copy the configuration below into `mise.toml` (project) or
`~/.config/mise/config.toml` (global), merging it with any existing configuration.
Then run `mise install github:17robots/dyn` and `mise exec -- dyn version`.

<details>
<summary>Mise configuration and SHA-256 checksums</summary>

```toml
{config}```

```text
{checksums.replace('public/', '')}```
</details>

Compiler, native output, isolated SDK and mise checks passed before publication.
CI reports are retained in Actions rather than added to release downloads.
'''
        (output/'RELEASE-NOTES.md').write_text(notes)
    except BaseException:
        shutil.rmtree(output)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hosts', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.version, args.evidence, args.native, args.output, args.hosts)
