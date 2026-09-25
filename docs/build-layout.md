# Component build and release ownership

The root justfile only dispatches component `just` calls. No compiler, example or
grammar build recipe is implemented there.

| Component | Local entry points | Dependencies outside checkout |
| --- | --- | --- |
| `compiler/justfile` | `all`, `release`, `smoke`, `install`, `package`, `clean` | LLVM/Tree-sitter development libraries, Clang, grammar checkout selected by `TS_DIR` |
| `projects/justfile` | `all`, `build`, `run`, `check`, `test`, `package`, `clean` | installed/built Dyn selected by `DYN`; optional example providers |
| `tree-sitter-dyn/justfile` | `generate`, `all`, `test`, `release`, `package`, `install`, `clean` | pinned Tree-sitter CLI for regeneration/tests; runtime development library for native tests |

Compiler recipes live in its justfile; `compiler/tools/build.py` tracks native
artifact inputs and command signatures so unchanged builds do not recompile.
`tools/install.py` owns installation and safe cleanup. Shared
qualification targets live in `compiler/workspace.just` and run existing tests
from `WORKSPACE`; they require its fixtures. This keeps full
workspace evidence distinct from the compiler's self-contained SDK smoke test.

## Workspace commands

```sh
just perf-compiler
just test-c
just test-projects
just test-grammar
just package-sdk
just package-grammar
just package-projects
```

Compiler output stays in root `build/`, preserving scripts and CI artifact paths.
Root-dispatched project output goes to `build/projects/`, grammar test output to
`build/grammar/`. Recipes execute sequentially. The compiler build helper serializes artifact
writes within each build directory, including separate concurrent invocations.
Use `just artifact dyn-sanitize` for individual native outputs.

Root `clean` removes workspace outputs and grammar libraries/objects. Direct
component builds with different output directories should be cleaned with the
same `BUILD` setting used to create them. Clean does not delete source or generated
parser source. Do not run clean concurrently with builds using the same directory.

## Independent checkout commands

```sh
TS_DIR=/path/to/tree-sitter-dyn just --justfile compiler/justfile release
TS_DIR=/path/to/tree-sitter-dyn just --justfile compiler/justfile smoke
TS_DIR=/path/to/tree-sitter-dyn just --justfile compiler/justfile package
DYN=/path/to/installed/bin/dyn just --justfile projects/justfile test
PROJECT=memory-tour DYN=/path/to/installed/bin/dyn just --justfile projects/justfile run
just --justfile projects/justfile package
just --justfile tree-sitter-dyn/justfile package
```

Install `just` (CI pins 1.58.0), Python 3, and Bash. Configuration is passed through
environment variables **before** `just`, rather than trailing Make assignments.
There is no `-j` build flag. Example: `BUILD=/tmp/dyn-build just release`.
For project arguments: `PROJECT=memory-tour just --justfile projects/justfile run --help`.

A standalone compiler checkout defaults to its own `build/`; when shared workspace
fixtures are present it defaults to root `build/`. `BUILD` overrides either.
Projects and grammar default to their own build directories when invoked directly.

The compiler owns `tools/dyn-bind.py` and `tools/package-sdk.py`. Historical root
script paths remain thin compatibility entry points (including dyn-bind imports).
The grammar owns reproducibility, corpus/highlight checks and source packaging.
Root grammar scripts similarly delegate. Projects carry their validation and
source-packaging tools and can use an installed SDK without compiler sources.

Only workspace editor checks require `zed-dyn` and its recorded provenance.
`just --justfile tree-sitter-dyn/justfile check-workspace` performs those additional checks.
A standalone grammar release can build/test/package without Zed or the compiler.
No target publishes, pushes or changes release versions/pins.

The editor grammar mirror also has a `zed-dyn/grammars/dyn/justfile`; its native
library recipes use the existing CMake project with Ninja. Upstream dependencies
(such as the Tree-sitter runtime) still use their own build systems.

## Validation

`python3 tests/just-components.py` copies the three components to temporary
checkouts without a parent justfile or shared fixtures. It builds/tests/packages
and unpacks the grammar, builds and packages the compiler against that extracted
grammar, runs projects against the relocated installed SDK, unpacks the project
archive, and runs the memory tour. It also verifies component clean preserves
source and unrelated sibling files. Detailed output: `build/just-components.log`.

Workspace qualification remains separate: use `just test-c`, provider/project
checks and release gates as appropriate. A standalone smoke test is not a claim
of complete compiler conformance or cross-platform release qualification.
