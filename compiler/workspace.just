# Workspace-only qualification recipes. Build/install/package remain standalone.

perf-compiler: release _dyn-perf
    #!/usr/bin/env bash
    set -euo pipefail


sanitize-test: all _dyn-sanitize
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1   UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1   DYN="${BUILD}"/dyn-sanitize sh tests/run.sh

sanitize-test-c: all _dyn-sanitize
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1   UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1   BUILD="${BUILD}/frontend-sanitize" CFLAGS="${CFLAGS} -O1 -fno-omit-frame-pointer -fsanitize=address,undefined" just --justfile "${COMPILER_DIR}/justfile" test-frontend
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1   UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1   DYN="${BUILD}"/dyn-sanitize sh tests/run.sh
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/audit-editor-contracts.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/audit-contracts.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/readiness-robustness.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/readiness-ffi.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/aggregate-abi.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/semantic-combinations.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/analysis-budgets.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 DYN="${BUILD}"/dyn-sanitize python3 tests/bind-layout.py
    cd "${WORKSPACE}" && ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 DYN="${BUILD}"/dyn-sanitize python3 tests/bind-lexical.py

fuzz-c: all
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && DYN="${BUILD}"/dyn sh tests/fuzz-smoke.sh
    cd "${WORKSPACE}" && DYN="${BUILD}"/dyn python3 tests/frontend-fuzz.py

quality-c: per-file test-c sanitize-test-c fuzz-c test-static-analysis
    #!/usr/bin/env bash
    set -euo pipefail


test-build-plan:
    python3 tools/build.py build-plan-test
    "$BUILD/build-plan-test"

test-interface:
    python3 tools/build.py interface-test
    "$BUILD/interface-test"

test-bind: _dyn _dynrt_start-o _dynrt_release-o _dynrt_support-o
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/vendor-bindings.py
    cd "${WORKSPACE}" && python3 tests/bind-named.py
    cd "${WORKSPACE}" && DYN="${BUILD}"/dyn python3 tests/bind-lexical.py
    cd "${WORKSPACE}" && python3 tools/dyn-bind.py tests/bind/sample.h -o "${BUILD}"/bind.dyn
    cd "${WORKSPACE}" && diff -u tests/bind/expected.txt "${BUILD}"/bind.dyn
    cd "${WORKSPACE}" && mkdir -p "${BUILD}"/bind-check
    cd "${WORKSPACE}" && rm -f "${BUILD}"/bind-check/main.dyn "${BUILD}"/bind-check/bindings.dyn
    cd "${WORKSPACE}" && cp "${BUILD}"/bind.dyn "${BUILD}"/bind-check/bindings.dyn
    cd "${WORKSPACE}" && "${BUILD}"/dyn check "${BUILD}"/bind-check --quiet

test-c: all test-build-plan test-interface test-bind test-contracts
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && sh tests/run.sh

test-editor: all test-grammar
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/lsp-contracts.py
    cd "${WORKSPACE}" && python3 tests/audit-editor-contracts.py
    cd "${WORKSPACE}" && python3 tests/lsp-export-cache.py
    cd "${WORKSPACE}" && python3 tests/lsp-edit-stress.py
    cd "${WORKSPACE}" && python3 tests/lsp-scheduling.py
    cd "${WORKSPACE}" && python3 tests/language-rejections.py
    cd "${WORKSPACE}" && python3 tests/lsp.py
    cd "${WORKSPACE}" && python3 tests/lsp-completion.py
    cd "${WORKSPACE}" && python3 tests/neovim.py
    cd "${WORKSPACE}" && python3 tests/lsp-index.py
    cd "${WORKSPACE}" && python3 tests/lsp-project.py
    cd "${WORKSPACE}" && python3 tests/lsp-targets.py

test-modules: all
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/check-modules.py

test-contracts: _unwind-capacity-test test-frontend test-editor test-modules _cache-failure-test _interface-allocation-test _module-allocation-test _global-allocation-test _source-failure-test _ast-allocation-test _stack-probe-test _module-rewrite-allocation-test
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && "${BUILD}"/module-rewrite-allocation-test
    cd "${WORKSPACE}" && "${BUILD}"/stack-probe-test
    cd "${WORKSPACE}" && "${BUILD}"/ast-allocation-test
    cd "${WORKSPACE}" && "${BUILD}"/source-failure-test
    cd "${WORKSPACE}" && "${BUILD}"/global-allocation-test
    cd "${WORKSPACE}" && "${BUILD}"/interface-allocation-test
    cd "${WORKSPACE}" && "${BUILD}"/module-allocation-test
    cd "${WORKSPACE}" && "${BUILD}"/cache-failure-test
    cd "${WORKSPACE}" && python3 tests/compiler-contracts.py
    cd "${WORKSPACE}" && python3 tests/agent-readiness.py
    cd "${WORKSPACE}" && python3 tests/lifetime-flow.py
    cd "${WORKSPACE}" && python3 tests/compiler-diagnostics.py
    cd "${WORKSPACE}" && python3 tests/large-function-contracts.py
    cd "${WORKSPACE}" && python3 tests/member-contracts.py
    cd "${WORKSPACE}" && python3 tests/typed-metamorphic.py
    cd "${WORKSPACE}" && python3 tests/compiler-stress.py
    cd "${WORKSPACE}" && python3 tests/compiler-timings.py
    cd "${WORKSPACE}" && python3 tests/incremental-cache.py
    cd "${WORKSPACE}" && python3 tests/constant-array-codegen.py
    cd "${WORKSPACE}" && "${BUILD}"/unwind-capacity-test
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/stdlib-contracts --no-cache --output "${BUILD}"/stdlib-contracts --quiet
    cd "${WORKSPACE}" && "${BUILD}"/stdlib-contracts
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/stdlib-contracts --release --no-cache --output "${BUILD}"/stdlib-contracts-release --quiet
    cd "${WORKSPACE}" && "${BUILD}"/stdlib-contracts-release
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/json-dom --no-cache --output "${BUILD}"/json-dom-contract --quiet
    cd "${WORKSPACE}" && "${BUILD}"/json-dom-contract
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/owned-arenas --no-cache --output "${BUILD}"/owned-arenas-test --quiet
    cd "${WORKSPACE}" && "${BUILD}"/owned-arenas-test
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/owned-arenas --release --no-cache --output "${BUILD}"/owned-arenas-release --quiet
    cd "${WORKSPACE}" && "${BUILD}"/owned-arenas-release
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/owned-arenas --target aarch64-macos --no-cache --quiet --output "${BUILD}"/owned-arenas-macos
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/owned-arenas --target x86_64-windows --no-cache --quiet --output "${BUILD}"/owned-arenas-windows
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/path-contracts --no-cache --quiet --output "${BUILD}"/path-contracts
    cd "${WORKSPACE}" && "${BUILD}"/path-contracts
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/sdk-boundaries --no-cache --quiet --output "${BUILD}"/sdk-boundaries
    cd "${WORKSPACE}" && "${BUILD}"/sdk-boundaries
    cd "${WORKSPACE}" && "${BUILD}"/dyn build tests/sdk-boundaries --release --no-cache --quiet --output "${BUILD}"/sdk-boundaries-release
    cd "${WORKSPACE}" && "${BUILD}"/sdk-boundaries-release
    cd "${WORKSPACE}" && python3 tests/environment-contracts.py
    cd "${WORKSPACE}" && python3 tests/terminal-progress.py
    cd "${WORKSPACE}" && python3 tests/float-parsing.py
    cd "${WORKSPACE}" && python3 tests/debug-multifile.py

test-frontend: _scope-index-test _syntax-cache-test _project-failure-test _frontend-state-test _frontend-failure-test _analysis-cache-test _codegen-failure-test
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && "${BUILD}"/scope-index-test
    cd "${WORKSPACE}" && "${BUILD}"/syntax-cache-test
    cd "${WORKSPACE}" && "${BUILD}"/project-failure-test
    cd "${WORKSPACE}" && "${BUILD}"/frontend-state-test
    cd "${WORKSPACE}" && "${BUILD}"/frontend-failure-test
    cd "${WORKSPACE}" && "${BUILD}"/analysis-cache-test
    cd "${WORKSPACE}" && "${BUILD}"/codegen-failure-test

test-vendors: all
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/vendor-packages.py
    cd "${WORKSPACE}" && python3 tests/vendor-extra.py

test-libraries: all
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/vendor-packages.py
    cd "${WORKSPACE}" && python3 tests/vendor-extra.py
    cd "${WORKSPACE}" && python3 tests/library-contracts.py
    cd "${WORKSPACE}" && python3 tests/codec-contracts.py
    cd "${WORKSPACE}" && python3 tests/compression-contracts.py
    cd "${WORKSPACE}" && python3 tests/streaming-window.py
    cd "${WORKSPACE}" && python3 tests/zstd-streaming.py
    cd "${WORKSPACE}" && python3 tests/dns-transport.py
    cd "${WORKSPACE}" && python3 tests/dns-owners.py
    cd "${WORKSPACE}" && python3 tests/archive-extensions.py
    cd "${WORKSPACE}" && python3 tests/tar-extensions.py
    cd "${WORKSPACE}" && python3 tests/tar-metadata.py
    cd "${WORKSPACE}" && python3 tests/tar-stream-memory.py
    cd "${WORKSPACE}" && python3 tests/unicode-conformance.py
    cd "${WORKSPACE}" && python3 tests/process-contracts.py
    cd "${WORKSPACE}" && python3 tests/native-abi.py
    cd "${WORKSPACE}" && python3 tests/fs-copy-contracts.py
    cd "${WORKSPACE}" && python3 tests/audit-contracts.py

test-static-analysis: 
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tests/static-analysis.py

test-readiness: release test-followups
    #!/usr/bin/env bash
    set -euo pipefail
    export DYN="${BUILD}/dyn-release"
    cd "${WORKSPACE}" && python3 tools/readiness-inventory.py --check
    cd "${WORKSPACE}" && python3 tests/readiness-conformance.py
    cd "${WORKSPACE}" && python3 tests/readiness-robustness.py
    cd "${WORKSPACE}" && python3 tests/readiness-ffi.py
    cd "${WORKSPACE}" && python3 tests/readiness-native.py
    cd "${WORKSPACE}" && python3 tests/readiness-soak.py
    cd "${WORKSPACE}" && python3 tests/reproducible-builds.py

sdk-reference: release
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 tools/readiness-inventory.py --check
    cd "${WORKSPACE}" && python3 tools/sdk-reference.py --check

test-followups: release sdk-reference
    #!/usr/bin/env bash
    set -euo pipefail
    export DYN="${BUILD}/dyn-release"
    cd "${WORKSPACE}" && python3 tests/aggregate-abi.py
    cd "${WORKSPACE}" && python3 tests/semantic-combinations.py
    cd "${WORKSPACE}" && python3 tests/analysis-budgets.py
    cd "${WORKSPACE}" && python3 tests/bind-layout.py
    cd "${WORKSPACE}" && python3 tests/bind-lexical.py
    cd "${WORKSPACE}" && "${BUILD}"/dyn-release build tests/sdk-api-contracts --no-cache --quiet --output "${BUILD}"/sdk-api-contracts
    cd "${WORKSPACE}" && "${BUILD}"/sdk-api-contracts
    cd "${WORKSPACE}" && "${BUILD}"/dyn-release build tests/sdk-api-contracts --no-cache --release --quiet --output "${BUILD}"/sdk-api-contracts-release
    cd "${WORKSPACE}" && "${BUILD}"/sdk-api-contracts-release
    cd "${WORKSPACE}" && "${BUILD}"/dyn-release build tests/sdk-pool-alignment --no-cache --quiet --output "${BUILD}"/sdk-pool-alignment
    cd "${WORKSPACE}" && "${BUILD}"/sdk-pool-alignment
    cd "${WORKSPACE}" && "${BUILD}"/dyn-release build tests/sdk-pool-alignment --no-cache --release --quiet --output "${BUILD}"/sdk-pool-alignment-release
    cd "${WORKSPACE}" && "${BUILD}"/sdk-pool-alignment-release

test-grammar: 
    #!/usr/bin/env bash
    set -euo pipefail
    BUILD="${TS_DIR}/build" just --justfile "${TS_DIR}/justfile" check-workspace

selfhost-ready: test-c
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && "${BUILD}"/dyn check selfhost --no-cache --quiet
    cd "${WORKSPACE}" && "${BUILD}"/dyn build selfhost --no-cache --quiet --output "${BUILD}"/dyn-selfhost    --link "${BUILD}"/tree-sitter-dyn-parser.o    --link "${BUILD}"/tree-sitter-dyn-scanner.o    --link "${BUILD}"/tree-sitter-dyn-bridge.o    --link "${BUILD}"/llvm-bridge.o    --link /usr/lib/libtree-sitter.so    --link /usr/lib/libLLVM.so    --link /usr/lib/libc.so.6
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost --self-test
    cd "${WORKSPACE}" && file "${BUILD}"/selfhost-aarch64-linux.o | grep -q 'ELF 64-bit.*ARM aarch64'
    cd "${WORKSPACE}" && file "${BUILD}"/selfhost-aarch64-macos.o | grep -q 'Mach-O 64-bit arm64 object'
    cd "${WORKSPACE}" && file "${BUILD}"/selfhost-x86_64-windows.o | grep -q 'x86-64 COFF object'
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost tests/selfhost-basic/main.dyn -o "${BUILD}"/selfhost-basic
    status=0
    cd "${WORKSPACE}" && "${BUILD}"/selfhost-basic || status=$?
    test "$status" -eq 42
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost --package tests/selfhost-package -o "${BUILD}"/selfhost-package
    status=0
    cd "${WORKSPACE}" && "${BUILD}"/selfhost-package || status=$?
    test "$status" -eq 42
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost --package tests/selfhost-c -o "${BUILD}"/selfhost-c
    status=0
    cd "${WORKSPACE}" && "${BUILD}"/selfhost-c || status=$?
    test "$status" -eq 42
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost --package tests/selfhost-c-variadic -o "${BUILD}"/selfhost-c-variadic
    status=0
    cd "${WORKSPACE}" && "${BUILD}"/selfhost-c-variadic || status=$?
    test "$status" -eq 42
    cd "${WORKSPACE}" && "${BUILD}"/dyn-selfhost --workspace tests/selfhost-import -o "${BUILD}"/selfhost-import
    status=0
    cd "${WORKSPACE}" && "${BUILD}"/selfhost-import || status=$?
    test "$status" -eq 42

selfhost-compare: 
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && test -n "${STAGE2}" -a -n "${STAGE3}" ||    { echo "usage: STAGE2=... STAGE3=... just selfhost-compare" >&2; exit 2; }
    cd "${WORKSPACE}" && sh tools/selfhost-compare.sh "${STAGE2}" "${STAGE3}"

release-check: 
    #!/usr/bin/env bash
    set -euo pipefail
    cd "${WORKSPACE}" && python3 "${COMPILER_DIR}/tools/release-check.py" ${RELEASE_FLAGS}

_dyn-release:
    python3 tools/build.py dyn-release

_dyn:
    python3 tools/build.py dyn

_dynrt_start-o:
    python3 tools/build.py dynrt_start.o

_dynrt_release-o:
    python3 tools/build.py dynrt_release.o

_dynrt_support-o:
    python3 tools/build.py dynrt_support.o

_dynrt_support_pic-o:
    python3 tools/build.py dynrt_support_pic.o

_dynrt_aarch64_support_pic-o:
    python3 tools/build.py dynrt_aarch64_support_pic.o

_dynrt_shared-o:
    python3 tools/build.py dynrt_shared.o

_dynrt_aarch64_shared-o:
    python3 tools/build.py dynrt_aarch64_shared.o

_dynrt_aarch64_start-o:
    python3 tools/build.py dynrt_aarch64_start.o

_dynrt_aarch64_release-o:
    python3 tools/build.py dynrt_aarch64_release.o

_dynrt_aarch64_support-o:
    python3 tools/build.py dynrt_aarch64_support.o

_dynrt_windows_start-o:
    python3 tools/build.py dynrt_windows_start.o

_dynrt_windows_shared-o:
    python3 tools/build.py dynrt_windows_shared.o

_dynrt_windows_support-o:
    python3 tools/build.py dynrt_windows_support.o

_dynrt_macos_start-o:
    python3 tools/build.py dynrt_macos_start.o

_dynrt_macos_shared-o:
    python3 tools/build.py dynrt_macos_shared.o

_dynrt_macos_support-o:
    python3 tools/build.py dynrt_macos_support.o

_tree-sitter-dyn-parser-o:
    python3 tools/build.py tree-sitter-dyn-parser.o

_tree-sitter-dyn-scanner-o:
    python3 tools/build.py tree-sitter-dyn-scanner.o

_tree-sitter-dyn-bridge-o:
    python3 tools/build.py tree-sitter-dyn-bridge.o

_llvm-bridge-o:
    python3 tools/build.py llvm-bridge.o

_dyn-sanitize:
    python3 tools/build.py dyn-sanitize

_dynrt_wasm-o:
    python3 tools/build.py dynrt_wasm.o

_dynrt_wasi_start-o:
    python3 tools/build.py dynrt_wasi_start.o

_dynrt_wasi_support-o:
    python3 tools/build.py dynrt_wasi_support.o

_dyn-perf:
    python3 tools/build.py dyn-perf

_cache-failure-test:
    python3 tools/build.py cache-failure-test

_interface-allocation-test:
    python3 tools/build.py interface-allocation-test

_module-allocation-test:
    python3 tools/build.py module-allocation-test

_global-allocation-test:
    python3 tools/build.py global-allocation-test

_source-failure-test:
    python3 tools/build.py source-failure-test

_ast-allocation-test:
    python3 tools/build.py ast-allocation-test

_module-rewrite-allocation-test:
    python3 tools/build.py module-rewrite-allocation-test

_stack-probe-test:
    python3 tools/build.py stack-probe-test

_frontend-state-test:
    python3 tools/build.py frontend-state-test

_frontend-failure-test:
    python3 tools/build.py frontend-failure-test

_analysis-cache-test:
    python3 tools/build.py analysis-cache-test

_codegen-failure-test:
    python3 tools/build.py codegen-failure-test

_project-failure-test:
    python3 tools/build.py project-failure-test

_syntax-cache-test:
    python3 tools/build.py syntax-cache-test

_scope-index-test:
    python3 tools/build.py scope-index-test

_unwind-capacity-test:
    python3 tools/build.py unwind-capacity-test


# Focused declaration-query and memory-contract qualification.
test-agent-readiness: all
    cd "${WORKSPACE}" && python3 tests/agent-readiness.py
    cd "${WORKSPACE}" && python3 tests/lifetime-flow.py

# Linux isolation, capability, observation and semantic database integration.
test-preview: all
    cd "${WORKSPACE}" && python3 tests/preview-platform.py
