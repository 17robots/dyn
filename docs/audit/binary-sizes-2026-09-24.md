# Example binary size audit — 2026-09-24

Linux x86-64, Dyn 0.1.0-dev. Fresh builds used an isolated compiler/runtime and cache under `/tmp/dyn-binary-size-20260924`, because workspace build outputs changed during inspection. No compiler, standard-library, or project sources were changed. Stripping was performed on copies only.

Compiler SHA-256: `f2d28cf3eaaaf1afabe0f87aa6bdf499d18b25e440ef974a5e9f1938815f0ff8`. Host linker: LLD 22.1.8. The controlled IR experiments used Clang 23.1.1; the C yardsticks used GCC 16.2.1.

## Native file sizes

All figures are KiB (1,024 bytes), from actual file lengths, not `du` allocation units or `size` totals. Release means the program was built with `--release`; an optimized compiler executable by itself does not select that mode. Release+stripped means a copy processed with `strip --strip-all`.

| Project / fixture | Debug | Release | Release + stripped | Direct shared dependencies |
| --- | ---: | ---: | ---: | --- |
| empty (synthetic fixture) | 2.7 | 1.0 | 0.7 | none |
| println (synthetic fixture) | 87.5 | 3.1 | 2.5 | none |
| write (synthetic fixture) | 87.5 | 1.5 | 1.1 | none |
| multi-module | 4.2 | 1.0 | 0.7 | none |
| hello | 140.3 | 13.7 | 12.6 | none |
| example | 114.7 | 12.0 | 11.2 | libsqlite3.so.0 |
| memory-tour | 238.4 | 16.3 | 14.7 | none |
| field-notes | 236.9 | 15.3 | 14.4 | none |
| json-check | 428.5 | 18.6 | 17.2 | none |
| recursive-search | 366.3 | 17.3 | 15.8 | none |
| process-supervisor | 182.3 | 20.1 | 18.4 | none |
| http-server | 277.1 | 11.3 | 10.0 | none |
| http-client | 275.6 | 11.1 | 10.0 | none |
| websocket-server | 337.4 | 16.5 | 15.1 | none |
| tar-inspect | 327.5 | 22.0 | 20.4 | none |
| raw-terminal | 91.5 | 11.9 | 10.8 | none |
| sqlite-example | 169.4 | 9.7 | 8.2 | libsqlite3.so.0 |
| stuff-sdl | 181.8 | 10.4 | 8.7 | libSDL3.so.0 |
| sdl3-example | 179.7 | 8.4 | 7.0 | libSDL3.so.0 |
| sdl3-gpu-example | 317.4 | 11.8 | 10.0 | libSDL3.so.0 |
| regex-example | 233.4 | 9.1 | 7.8 | libpcre2-8.so.0 |
| lua-example | 232.4 | 9.2 | 8.0 | liblua5.4.so.5.4 |
| curl-example | 196.8 | 17.9 | 16.4 | libcurl.so.4 |

`stb-example` could not be measured: the local `dyn_stb` native provider is missing. Other optional examples were not included in this sample. The `multi-module` example does effectively no observable work, so its release result is equivalent to the empty fixture. The `hello` project includes loops, formatting, structs/enums and arenas; it is not a minimal hello-world.

## Why debug is much larger

1. Debug is the CLI default, enables DWARF, and skips the release O2 pipeline. Release disables DWARF by default. See `compiler/src/cli.c` and `compiler/src/codegen.c`.
2. Debug retains unused functions from imported modules. The current emitted object groups functions into a common `.text` section; the existing linker `--gc-sections` can discard sections, not arbitrary functions within a retained section. The JSON checker includes unused `remove_tree` and `spawn_environment` functions. Even the plain printing fixture includes terminal key decoding.
3. Unoptimized bounds checks, panic/trace calls, argument packing and ordinary code also occupy more space. Stripping symbols does not remove that executable code.

JSON checker debug breakdown: 256,327 bytes of `.text`, 119,551 bytes of DWARF, 29,357 bytes of `.rodata`, plus unwind tables, ELF metadata and symbol/string tables. Stripping reduces 438,776 bytes to 299,744 bytes, still far larger than the 19,072-byte release.

### Controlled dead-code experiment

Emitted unoptimized, uncached Dyn IR; compiled the same IR with Clang `-O0`, with and without `-ffunction-sections -fdata-sections`; linked both against the same debug runtime using `ld.lld --gc-sections`. This isolates section granularity from optimization level. These are experiment binaries, not a compiler patch.

| Fixture | Clang control debug | Separate sections debug | Separate sections, stripped |
| --- | ---: | ---: | ---: |
| println | 84.6 KiB | 54.6 KiB | 29.5 KiB |
| json-check | 418.1 KiB | 183.8 KiB | 66.1 KiB |

The JSON experiment is about 56% smaller with debug information retained. Printed output matched; JSON validation matched on valid input, invalid input and the no-argument usage path. This is targeted behavioral evidence, not qualification of a general compiler change. Cached-module and uncached-monolithic baselines differ slightly, so the experiment is reported separately from the project table.

## Release costs and avoidable dependencies

- The JSON checker retains about 5.1 KiB for `print_arguments` and 1.5 KiB for floating-point formatting. Its runtime `any` formatting path supports more kinds than the particular string messages need. Generic formatting has a real footprint; it is not all JSON parsing.
- A minimal `io.write_all` fixture is 1,488 bytes; `io.println` is 3,136 bytes. This is a narrowly controlled literal-message example, not a guarantee that every println call has the same cost.
- `projects/example` imports SQLite without using it. Removing that import in a temporary copy preserved output, reduced release size from 12,256 to 11,232 bytes, and removed `libsqlite3.so.0` from DT_NEEDED. Removing unused imports or using carefully validated as-needed linking is an independent improvement opportunity.
- Release files retain normal symbols; stripping saves roughly 0.3–1.9 KiB across this sample. Most of the size reduction comes from release optimization, not stripping.

## File size is not runtime or deployment footprint

- Debug trace storage reserves 65 KiB of zero-filled `.bss`. Most sampled debug programs additionally reserve 2.5 KiB for unwind storage. These zero-filled bytes do not occupy equivalent file space, and virtual reservations are not measurements of resident memory.
- An arena created at runtime does not embed its requested capacity in the executable. Allocating a 16 MiB arena is different from shipping 16 MiB of initialized data.
- SDL examples load SDL dynamically. The local SDL library itself is 3,299,512 bytes (about 3.15 MiB); SQLite is 1,673,352 bytes (about 1.60 MiB). Those sizes exclude transitive dependencies and are not part of the example executable sizes above.
- `.ll`, `.o`, `.dyncache` and cache directories are build artifacts, not all part of a deployed native program.

## Browser and WASI

Fresh release module sizes:

| Module | Bytes | KiB |
| --- | ---: | ---: |
| browser-canvas | 1,607 | 1.6 |
| browser-video | 3,005 | 2.9 |
| wasi-hello | 13,546 | 13.2 |

The staged browser FFmpeg core is 32,232,419 bytes (30.74 MiB). It is the separately compiled upstream media engine, not Dyn runtime overhead. The cached download archive is another 20,634,719 bytes (19.68 MiB); `core.tgz` is not needed by the browser at runtime. This media engine is substantial for a short grayscale-preview demo, but its general-purpose decode/encode capability explains the scale. A purpose-built codec configuration could reduce it, at the cost of supported formats.

## Assessment

The native release examples are modest in absolute size: mostly 8–22 KiB before stripping. The SDL/SQLite/Lua/etc. examples depend on external engines; their small executable is not their full deployment size. Debug files are still modest for desktop development, but clearly contain avoidable code relative to what these examples do.

For a local reference, ordinary GCC `-O2` C empty-main and puts programs were 15,784 and 15,968 bytes, or 14,320 and 14,472 stripped, using dynamic libc and normal system startup. Dyn uses its own freestanding startup, so this is a conventional-build yardstick, not evidence of an intrinsic size advantage over C. A freestanding C build can also be much smaller.

Priorities suggested by the measurements: improve debug function/data section granularity and validate it across targets; avoid unused native dependencies; retain ordinary release stripping as an optional packaging step. There is no evidence here that native release programs need an urgent size overhaul.

## Reproduction

```sh
BUILD=/tmp/dyn-binary-size-20260924 just all
DYN_SDK="$PWD/compiler" DYN_CACHE_DIR=/tmp/dyn-size-cache \
  /tmp/dyn-binary-size-20260924/dyn build projects/json-check \
  --release --output /tmp/json-check
readelf -SW /tmp/json-check
readelf -d /tmp/json-check
nm -S --size-sort /tmp/json-check
cp /tmp/json-check /tmp/json-check.stripped
strip --strip-all /tmp/json-check.stripped
```

Full local measurements and experiment scripts: `/tmp/dyn-binary-size-20260924/audit/{sizes.json,probes.json,measure.py,probes.py}`. These temporary files may disappear on cleanup; the measured tables and interpretation are retained in this report.
