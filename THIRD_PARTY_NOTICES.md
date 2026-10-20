# Third-party notices

Dyn's license does not replace third-party terms.

## Unicode data

The SDK includes its Unicode notice at `std/unicode/text/LICENSE-UNICODE.txt` in
source, or `share/dyn/unicode/text/LICENSE-UNICODE.txt` in the SDK archive.

## Bundled host dependencies

Current independent SDK builds do not bundle LLVM or LLD. The compiler does not
link their libraries. Linux uses the host's glibc and dynamic loader; macOS uses
system libraries. These operating-system libraries are not bundled.

Windows packaging checks imported DLLs and records any copied toolchain
runtime dependencies, their package versions, and their licenses under
`share/dyn/licenses/`. If libiconv is copied, its matching source, patches, and
MSYS2 build recipe are included under `share/dyn/sources/`. Windows system DLLs
are supplied by the operating system.

`manifest.json` records packaged file hashes and dependency details. The
`dyn-VERSION-runtime-sources.tar.gz` asset contains the matching Dyn runtime
sources and generator tools. Older LLVM-based SDK releases retain the bundled
dependency notices and corresponding-source assets shipped with those releases.

Native providers remain separately installed and subject to their own licenses.
Provider source revisions are recorded in the repository manifests.
