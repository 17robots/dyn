# Third-party notices

Dyn's license does not replace third-party terms.

## Unicode data

The SDK includes its Unicode notice at `std/unicode/text/LICENSE-UNICODE.txt` in
source, or `share/dyn/unicode/text/LICENSE-UNICODE.txt` in the SDK archive.

## Bundled host dependencies

Linux SDK archives include LLVM, LLD and their non-glibc shared
library dependencies. Their own licenses apply independently of Dyn's license.
The archive's `share/dyn/licenses/` directory contains dependency copyright and
license notices, full common license texts, and exact Ubuntu package versions.
`manifest.json` records bundled libraries and file hashes. The release's
`dyn-VERSION-runtime-sources.tar.gz` asset provides matching Ubuntu GCC source
packages and build rules for the bundled GNU runtimes, plus the script used to
adjust their ELF library search paths. The host supplies glibc
and its matching dynamic loader; these are not bundled.

Windows SDKs bundle MSYS2 CLANG64 LLVM/LLD and their non-system
DLL dependencies. macOS SDKs bundle Homebrew LLVM/LLD and their
non-system dylib dependencies. Their license files and package provenance are
inside `share/dyn/licenses/`; `manifest.json` records bundled files and hashes.
Windows system DLLs and macOS system libraries are supplied by the operating system.
Windows libiconv corresponding source (upstream source, patches and MSYS2 build
recipe) is included in `share/dyn/sources/`. Compatible rebuilt DLLs can replace
the bundled copy.

Native providers remain separately installed and subject to their own licenses.
Provider source revisions are recorded in the repository manifests.
