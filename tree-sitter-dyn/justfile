set shell := ["bash", "-euo", "pipefail", "-c"]
export BUILD := absolute_path(env('BUILD', 'build'))
export DIST := absolute_path(env('DIST', BUILD / 'dist'))
export WORKSPACE := absolute_path(env('WORKSPACE', '..'))
export TS := env('TS', 'tree-sitter')

all:
    python3 tools/build.py all

generate:
    python3 tools/build.py generate

alias grammar := generate

install:
    python3 tools/build.py install

uninstall:
    python3 tools/build.py uninstall

clean:
    python3 tools/build.py clean

test:
    python3 tools/build.py highlights
    python3 tools/check.py
    "$BUILD/highlights-test" neovim/highlights.scm helix/highlights.scm

check-workspace: test
    python3 tools/check.py --workspace "$WORKSPACE" --provenance-only
    "$BUILD/highlights-test" "$WORKSPACE/zed-dyn/languages/dyn/highlights.scm"

editor-grammar:
    python3 tools/build.py highlights
    cp grammar.js "$WORKSPACE/zed-dyn/grammars/dyn/grammar.js"
    cp src/parser.c src/scanner.c src/node-types.json src/grammar.json "$WORKSPACE/zed-dyn/grammars/dyn/src/"
    "$TS" build --wasm -o "$WORKSPACE/zed-dyn/grammars/dyn.wasm" .

verify-published-grammar:
    python3 "$WORKSPACE/tools/verify-published-grammar.py"

release: all test

package: release
    python3 tools/package.py --dist "$DIST"

help:
    @just --list
