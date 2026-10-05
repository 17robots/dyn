#!/usr/bin/env python3
"""Standalone compiler regressions; no sibling projects or editor repositories."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(os.environ.get('BUILD',ROOT/'build')).resolve()
def run(*command):
    subprocess.run(list(map(str,command)),cwd=ROOT,check=True,timeout=300)
run(sys.executable, ROOT/'tests/allocator-builtins.py')
run(sys.executable, ROOT/'tests/memory-ergonomics.py')
run(sys.executable, ROOT/'tests/std-memory-contracts.py')
run(sys.executable, ROOT/'tests/array-extents.py')
run(sys.executable, ROOT/'tests/owner-warnings.py')
run(sys.executable, ROOT/'tests/documentation-examples.py')
for name in ('performance-contracts.py','backend-regressions.py','frontend-audit.py','regex-regressions.py','pool-regressions.py','deflate-regressions.py','library-audit.py','runtime-audit.py','http-fragments.py','unwind-registers.py','run-cache.py','thinlto-cache.py','net-contracts.py','concurrency-net-host.py','sync-host.py','dns-host.py','watch-contracts.py','windows-sockets.py','parser-contracts.py','vendor-bindings.py','vendor-provider-host.py','selfhost-readiness.py','aggregate-copy.py','shared-host.py', 'process-directory.py', 'panic-lifetime.py','compiler-contracts.py','lsp-contracts.py','lifetime-flow.py','semantic-combinations.py','compiler-regressions.py','standard-streams.py','stdlib-host.py','readiness-native.py','aggregate-abi.py','release-bundle.py'):
    run(sys.executable,ROOT/'tests'/name)
# Exercise real frontend/cache failure seams retained with the compiler.
artifacts=['cache-failure-test','interface-allocation-test','module-allocation-test','global-allocation-test','source-failure-test','ast-allocation-test','module-rewrite-allocation-test','stack-probe-test','frontend-state-test','frontend-failure-test','analysis-cache-test','codegen-failure-test','project-failure-test','syntax-cache-test','scope-index-test','unwind-capacity-test','build-plan-test','interface-test']
run(sys.executable,ROOT/'tools/build.py',*artifacts)
for name in artifacts:
    run(BUILD/name)
print('PASS standalone compiler regression suite')
