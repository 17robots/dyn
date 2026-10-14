# Standalone Dyn compiler. Configuration uses environment variables.
set positional-arguments
set shell := ["bash", "-euo", "pipefail", "-c"]
export COMPILER_DIR := justfile_directory()
export BUILD := absolute_path(env('BUILD', COMPILER_DIR / 'build'))
export DYN := env('DYN', BUILD / 'dyn-release')
export DYN_SDK := env('DYN_SDK', COMPILER_DIR)

deps:
    python3 tools/fetch-grammar.py

all: deps
    python3 tools/build.py all

release: all
    python3 tools/build.py dyn-release

artifact +names: deps
    python3 tools/build.py "$@"

per-file: deps
    python3 tools/build.py dyn-per-file

smoke: release
    "$BUILD/dyn" build tests/smoke --no-cache --quiet --output "$BUILD/compiler-smoke"
    "$BUILD/compiler-smoke"
    "$BUILD/dyn-release" build tests/smoke --release --no-cache --quiet --output "$BUILD/compiler-smoke-release"
    "$BUILD/compiler-smoke-release"

test: smoke
    python3 tests/run.py

# Qualification of generated ABI bindings and the compiler's required provider.
test-vendors: release
    python3 tests/vendor-bindings.py
    python3 tests/vendor-provider-host.py

# Requires native Lua 5.4, PCRE2, SQLite, LZ4 and zstd development packages.
test-vendors-native: release
    python3 tests/vendor-packages.py
    python3 tests/vendor-raw.py

# Requires setup-vendor-tests.py and the native development packages in vendor-native.yml.
test-vendors-all: release
    python3 tools/bind-vendors.py --prefix "$BUILD/vendor-deps/install" --sources "$BUILD/extra-vendor-sources" --output "$BUILD/raw-sdk" --dyn "$DYN" --clang "${BIND_CLANG:-clang}"
    python3 tests/vendor-all-raw.py
    python3 tests/vendor-extra.py
    python3 tests/vendor-media.py
    python3 tests/vendor-sanitize.py

# Real compiler-building primitives; does not claim bootstrap equivalence.
selfhost-ready: release
    python3 tests/selfhost-readiness.py

install: release
    python3 tools/install.py

package: release
    python3 tools/package-sdk.py

alias package-sdk := package
alias install-check := package

release-check:
    python3 tools/release-check.py

# Cold check/debug/release lines per second; fails below the regression floors.
bench-scale: release
    python3 tools/scale-benchmark.py --budget

# Isolated parser experiment; does not select a different production parser.
test-parser-experiment: deps
    python3 tools/parser-experiment/check.py --sources --corpus std --corpus tests

# Opt-in declaration reader; production syntax/recovery/depth policy stays authoritative.
test-compact-declarations: release
    python3 tools/build.py dyn-legacy dyn-compact-declarations frontend-state-compact-test frontend-failure-compact-test
    "$BUILD/frontend-state-compact-test"
    "$BUILD/frontend-failure-compact-test"
    python3 tools/parser-experiment/check-declarations.py --compiler "$BUILD/dyn-compact-declarations" --reference "$BUILD/dyn-legacy"

# Opt-in retained source consumers; syntax, recovery, AST and editor still use Tree-sitter.
test-compact-sources: release
    python3 tools/build.py dyn-legacy dyn-compact-sources frontend-state-sources-test frontend-failure-sources-test
    python3 tools/parser-experiment/check-sources.py
    python3 tools/parser-experiment/check-scopes.py
    python3 tools/parser-experiment/check-refs.py
    python3 tools/parser-experiment/check-rewrite.py
    python3 tools/parser-experiment/check-interfaces.py
    "$BUILD/frontend-state-sources-test"
    "$BUILD/frontend-failure-sources-test"
    python3 tools/parser-experiment/check-declarations.py --compiler "$BUILD/dyn-compact-sources" --reference "$BUILD/dyn-legacy"
    DYN="$BUILD/dyn-compact-sources" python3 tests/frontend-audit.py
    DYN="$BUILD/dyn-compact-sources" python3 tests/compiler-contracts.py
    DYN="$BUILD/dyn-compact-sources" python3 tests/lsp-contracts.py
    DYN="$BUILD/dyn-compact-sources" python3 tests/generics.py

# Direct compact AST lowering with retained aliases/generics; default remains Tree-sitter.
test-compact-ast: release
    python3 tools/build.py dyn-legacy dyn-compact-ast frontend-state-ast-test frontend-failure-ast-test batch-trees-ast-test
    python3 tools/parser-experiment/check-ast.py --corpus std --corpus tests
    "$BUILD/frontend-state-ast-test"
    "$BUILD/frontend-failure-ast-test"
    "$BUILD/batch-trees-ast-test"
    python3 tools/parser-experiment/check-declarations.py --compiler "$BUILD/dyn-compact-ast" --reference "$BUILD/dyn-legacy"
    DYN="$BUILD/dyn-compact-ast" python3 tests/run.py

# Compact-first parity against the Tree-sitter-only dyn-legacy rollback artifact.
test-compact-first: release
    python3 tools/build.py dyn-legacy dyn-compact-first
    python3 tools/parser-experiment/check-depth.py --corpus std --corpus tests
    python3 tools/parser-experiment/check-first.py
    python3 tools/parser-experiment/check-declarations.py --compiler "$BUILD/dyn-compact-first" --reference "$BUILD/dyn-legacy"
    evidence="$(mktemp -d "$BUILD/compact-first-acceptance.XXXXXX")"; python3 tools/parser-experiment/check-acceptance.py --compiler "$BUILD/dyn-compact-first" --reference "$BUILD/dyn-legacy" --samples 1000 --corpus std --corpus tests --output "$evidence/run"
    DYN="$BUILD/dyn-compact-first" python3 tests/run.py

# Test-only x86-64 Linux scalar object emitter; never selects a production backend.
test-backend-experiment: release
    python3 tools/backend-experiment/build.py
    python3 tools/backend-experiment/test.py

# Default debug builds emit natively on x86_64 Linux; dyn-legacy is the LLVM reference.
test-native-debug: release
    python3 tools/build.py dyn dyn-legacy
    python3 tools/backend-experiment/check-compiler.py --compiler "$BUILD/dyn" --reference "$BUILD/dyn-legacy"

# AArch64 Linux native emission against LLVM under qemu-aarch64 (skips without qemu).
test-native-a64: release
    python3 tools/build.py dyn
    python3 tools/backend-experiment/native-differential.py --target aarch64-linux

# x86-64 Windows native emission against LLVM under wine (skips without wine).
test-native-windows: release
    python3 tools/build.py dyn
    python3 tools/backend-experiment/native-differential.py --target x86_64-windows

# AArch64 macOS native emission against LLVM (runs on Apple silicon Macs only).
test-native-macos: release
    python3 tools/build.py dyn
    python3 tools/backend-experiment/native-differential.py --target aarch64-macos

# Regression suite with native emission required wherever it is eligible.
test-native-strict: release
    python3 tools/build.py dyn
    DYN_REAL="$BUILD/dyn" python3 tools/backend-experiment/strict-suite.py

# Matched prepared-IR timing; correctness and runtime checks are outside emission timing.
bench-backend-experiment: release
    python3 tools/build.py backend-benchmark
    python3 tools/backend-experiment/benchmark.py

native-probes: release
    python3 tools/build-native-probes.py

vendor-libs:
    python3 tools/build-vendors.py --prefix "$BUILD/vendor-deps/install" ${VENDOR_PACKAGES:-}

vendor-bindings: release
    python3 tools/bind-vendors.py --prefix "$BUILD/vendor-deps/install" --sources "$BUILD/extra-vendor-sources" --output "$BUILD/raw-sdk" --dyn "$BUILD/dyn-release" --clang "${BIND_CLANG:-clang}" ${VENDOR_PACKAGES:-}

clean:
    python3 tools/install.py --clean

help:
    @just --list
