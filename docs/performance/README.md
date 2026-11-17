# Performance records

Each dated directory records one investigation: the question, the programs
measured, the commands and the results, as they were on that date.

The `.dyn` sources in these directories are evidence, not maintained
examples. They use the language and standard library of their date, and
many no longer compile, because the language has changed since (failure
handling, arenas, loop labels and more). They are not updated, so that each
record still shows exactly what was measured.

For current numbers and sources that build today:

- [`PERFORMANCE.md`](../../PERFORMANCE.md) has the latest comparison against
  C, Go and Zig.
- [`tools/bench`](../../tools/bench) holds the kernels and the runner
  (`python3 tools/bench/run.py`).
