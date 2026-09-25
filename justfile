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

install: release
    python3 tools/install.py

package: release
    python3 tools/package-sdk.py

alias package-sdk := package
alias install-check := package

release-check:
    python3 tools/release-check.py

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
