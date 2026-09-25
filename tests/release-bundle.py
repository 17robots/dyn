#!/usr/bin/env python3
"""Release bundles reject failed gates, altered artifacts and mismatched versions."""
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_release',ROOT/'tools/prepare-release.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='dyn-release-bundle-') as directory:
    work = Path(directory)
    evidence = work/'evidence'
    native = work/'native'
    native.mkdir()
    artifacts = evidence/'release-check/artifacts'
    artifacts.mkdir(parents=True)
    (evidence/'dist').mkdir()
    version = '0.1.0-preview.3'
    archive = artifacts/f'dyn-{version}-linux-x86_64.tar.gz'
    archive.write_bytes(b'test archive')
    report = dict(status='passed',stages=[dict(status='passed')],artifacts={'build/release-check/artifacts/'+archive.name:module.sha(archive)})
    package = dict(status='passed',manifest=dict(version='dyn '+version),archive=archive.name,sha256=module.sha(archive))
    source_archive=artifacts/f'dyn-{version}-runtime-sources.tar.gz'
    source_archive.write_bytes(b'test runtime sources')
    package['runtime_sources']=dict(archive=source_archive.name,sha256=module.sha(source_archive))
    report['artifacts']['build/release-check/artifacts/'+source_archive.name]=module.sha(source_archive)
    def write_evidence():
        (evidence/'release-check/report.json').write_text(json.dumps(report))
        (evidence/'dist/package-validation.json').write_text(json.dumps(package))
    write_evidence()
    for target,count in [('windows',14),('macos',14),('aarch64',12)]:
        (native/f'native-{target}.json').write_text(json.dumps(dict(target=target,status='passed',probes=[dict(status='passed') for _ in range(count)])))
    hosts=work/'hosts'; hosts.mkdir()
    for host,ext in [('macos-aarch64','tar.gz'),('windows-x86_64','zip')]:
        path=hosts/f'dyn-{version}-{host}.{ext}';path.write_bytes(host.encode())
        (hosts/f'package-{host}.json').write_text(json.dumps(dict(status='passed',version=version,platform=host,archive=path.name,sha256=module.sha(path),mise=True,isolated_path=True)))
    output = work/'release' 
    module.prepare(version,evidence,native,output,hosts)
    config = tomllib.loads((output/'mise.toml').read_text())['tools']['github:17robots/dyn']
    assert config['version']==version and config['platforms']['linux-x64']['checksum']=='sha256:'+module.sha(archive)
    assert len(list((output/'public').iterdir())) == 4
    assert set(config['platforms']) == {'linux-x64','macos-arm64','windows-x64'}
    for line in (output/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ')
        assert module.sha(output/name)==digest
    def rejected():
        destination=work/'rejected'
        try:
            module.prepare(version,evidence,native,destination,hosts)
        except (ValueError,FileNotFoundError):
            assert not destination.exists(), 'stale publishable output remains'
        else:
            raise AssertionError('invalid release was accepted')
    report['status']='partial';write_evidence();rejected()
    report['status']='passed';package['manifest']['version']='dyn 9.9.9';write_evidence();rejected()
    package['manifest']['version']='dyn '+version;write_evidence()
    archive.write_bytes(b'altered');rejected();archive.write_bytes(b'test archive')
    source_archive.write_bytes(b'altered sources');rejected();source_archive.write_bytes(b'test runtime sources')
    win=hosts/f'dyn-{version}-windows-x86_64.zip'
    win.write_bytes(b'altered');rejected();win.write_bytes(b'windows-x86_64')
    host_report=hosts/'package-windows-x86_64.json';saved=host_report.read_text()
    host_report.write_text(saved.replace('passed','packaged'));rejected();host_report.write_text(saved)
    (native/'native-macos.json').unlink();rejected()
print('PASS release checksums/config and rejection of partial gates, version mismatch, tampering, missing native evidence')
