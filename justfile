# Standalone Dyn compiler. Configuration uses environment variables.
set positional-arguments
set shell := ["bash", "-euo", "pipefail", "-c"]
export COMPILER_DIR := justfile_directory()
export BUILD := absolute_path(env('BUILD', COMPILER_DIR / 'build'))
export DYN := env('DYN', BUILD / 'dyn-release')
export DYN_SDK := env('DYN_SDK', COMPILER_DIR)

all:
    python3 tools/build.py all

release: all
    python3 tools/build.py dyn-release

artifact +names:
    python3 tools/build.py "$@"

per-file:
    python3 tools/build.py dyn-per-file

smoke: release
    "$BUILD/dyn" build tests/smoke --no-cache --quiet --output "$BUILD/compiler-smoke"
    "$BUILD/compiler-smoke"
    "$BUILD/dyn-release" build tests/smoke --release --no-cache --quiet --output "$BUILD/compiler-smoke-release"
    "$BUILD/compiler-smoke-release"

test: smoke
    python3 tests/run.py

# Qualification of generated ABI bindings and the Tree-sitter provider binding
# (needs libtree-sitter; fetches the grammar it parses with).
test-vendors: release
    python3 tests/vendor-bindings.py
    python3 tools/fetch-grammar.py
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

# Language-server responses against a reference compiler over std, tests and an
# optional external project (REFERENCE=path/to/dyn, PROJECT=path).
test-lsp-differential: release
    python3 tools/lsp-differential.py --reference "${REFERENCE:?set REFERENCE to a reference dyn}" --candidate "$BUILD/dyn-release" --corpus std --corpus tests ${PROJECT:+--corpus "$PROJECT"}

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
