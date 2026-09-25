# Third-party notices

Dyn's license does not replace third-party terms.

## Tree-sitter

The generated parser/support headers use Tree-sitter material. The compiler also
links to a separately installed Tree-sitter runtime. Upstream revision:
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

## Separately installed dependencies

LLVM and native providers are not bundled in the SDK archive. Their independently
installed libraries and any binaries you redistribute remain subject to their own
licenses. The archive manifest records linked library dependencies; provider source
revisions are recorded in the repository manifests.
