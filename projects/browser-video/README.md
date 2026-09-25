# Browser video processing

```sh
just --justfile projects/justfile browser-video
python3 -m http.server 8000 --directory projects/build/browser-video
```

Open http://localhost:8000 and choose a video up to 16 MiB. The worker decodes up
to eight 160×90 RGBA frames, copies them into a Dyn arena, applies grayscale, and
encodes a silent one-second WebM. Cancel terminates the worker; each job gets fresh
FFmpeg/Dyn instances. No video is uploaded. FFmpeg assets are served locally.

The build downloads the pinned single-thread `@ffmpeg/core` 0.12.10 archive and
verifies its SHA-512 integrity. Assets, package metadata and provenance remain in
the output directory; source archives do not bundle the generated core binaries.
The upstream package declares GPL-2.0-or-later, and its external libraries have
their own terms: see [upstream licensing](https://ffmpegwasm.netlify.app/docs/faq/#what-is-the-license-of-ffmpegwasm).

With an installed SDK, `dyn-browser-ffmpeg` stages the same assets and bridge.
This is a JavaScript-mediated integration, not direct linking of native FFmpeg
bindings into Dyn's freestanding Wasm. The two modules have separate memories;
never pass a pointer from one to the other. A complete editor, audio sync,
long-form streaming, hardware codecs and multithreaded FFmpeg are outside this demo.
