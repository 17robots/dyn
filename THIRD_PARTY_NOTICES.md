# Third-party notices

Dyn's license does not replace third-party terms.

## Tree-sitter

The generated parser/support headers use Tree-sitter material. The compiler also
bundles the Tree-sitter runtime in SDK archives. Linux upstream revision:
`f2f197b6b27ce75c280c20f131d4f71e906b86f7` (v0.25.8).

The MIT License (MIT)

Copyright (c) 2018-2024 Max Brunsfeld

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Unicode data

The SDK includes its Unicode notice at `std/unicode/text/LICENSE-UNICODE.txt` in
source, or `share/dyn/unicode/text/LICENSE-UNICODE.txt` in the SDK archive.

## Bundled host dependencies

Linux SDK archives include LLVM, LLD, Tree-sitter and their non-glibc shared
library dependencies. Their own licenses apply independently of Dyn's license.
The archive's `share/dyn/licenses/` directory contains dependency copyright and
license notices, full common license texts, and exact Ubuntu package versions.
`manifest.json` records bundled libraries and file hashes. The release's
`dyn-VERSION-runtime-sources.tar.gz` asset provides matching Ubuntu GCC source
packages and build rules for the bundled GNU runtimes, plus the script used to
adjust their ELF library search paths. The host supplies glibc
and its matching dynamic loader; these are not bundled.

Windows SDKs bundle MSYS2 CLANG64 LLVM/LLD, Tree-sitter and their non-system
DLL dependencies. macOS SDKs bundle Homebrew LLVM/LLD, Tree-sitter and their
non-system dylib dependencies. Their license files and package provenance are
inside `share/dyn/licenses/`; `manifest.json` records bundled files and hashes.
Windows system DLLs and macOS system libraries are supplied by the operating system.
Windows libiconv corresponding source (upstream source, patches and MSYS2 build
recipe) is included in `share/dyn/sources/`. Compatible rebuilt DLLs can replace
the bundled copy.

Native providers remain separately installed and subject to their own licenses.
Provider source revisions are recorded in the repository manifests.
