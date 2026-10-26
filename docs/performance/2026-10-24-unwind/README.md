# Frame-local unwind ownership: measured follow-up

On this Linux x64 host, the retained runtime changes reduce the fixed JSONL application's median wall time from **59.243 ms to 55.847 ms (5.7%)**. This is an additional improvement over the [previous qualified build](../2026-10-24-c-levels/README.md), not a comparison with an early preview release.

| Fixed workload | Before | Current | C comparator |
|---|---:|---:|---:|
| JSONL report, 60,000 records | 59.243 ms | 55.847 ms | 13.319 ms |
| Large-file search | 9.377 ms | 9.086 ms | 31.496 ms |
| Compiler source snapshot search | 5.264 ms | 5.177 ms | 4.339 ms |

The JSON comparator is GCC with yyjson; the search comparator is the existing C application port. These are application/library comparisons, not a language-wide ranking. C remains about 4.2 times faster on the JSON workload. The previous gap is not closed.

## What changed

Linux x64 normal unwind completion now reads its owning runtime slot from a private word in the linked frame. This avoids a `gettid` syscall and slot search on unlink. Link still identifies the current thread. Bytes 72–79 are outside the saved-register bank in the existing 128-byte context. Other architectures return owner offset zero and keep lookup-based unlink; no frame size or language ABI changed.

Concurrency qualification also exposed an existing slot-selection bug: a vacant lower slot could be claimed before finding the same thread's active higher slot. Both the Dyn support runtime and C reference now search for existing ownership before claiming a vacancy. A deterministic nesting regression fails against the unchanged baseline and passes after the fix.

The compiler executable, std modules, application sources, and test inputs are unchanged. Rebuilding programs links the updated runtime. Programs without relevant runtime activity should not be assumed to gain the JSON improvement.

## Measurement and qualification

Measurements ran serially on CPU 2, with two warmups and fifteen samples per binary. Before/current/C order rotated and reversed. Every execution checked the exact existing output oracle. The paired bootstrap interval for the JSON current/before median ratio is 0.9367–0.9466; finite samples on one host do not establish performance on other machines.

- Compiler suite: **204/204 gates pass, zero skips**, one uninterrupted final-state run. All 664 source/test/runtime/tool hashes match before and after qualification and final measurement.
- DNA: **9/9 build, module, host, ABI and smoke checks pass**, zero skips, no source changes.
- Runtime regression: precise identity-call counts, register canaries, non-top/repeated unlink, concurrent pthreads, capacity and slot reuse.
- Existing cleanup qualification includes 552 embedded guests. Runtime register/context tests and all target runtime builds pass.

The C capacity test uses synthetic syscall thread identities and has a pre-existing non-Linux portability limitation. The new owner regression explicitly requires Linux x64. Cross-linking other targets is not native execution evidence.

## DNA results

Five alternating paired workflow samples used each binary's own native library and embedded runtime. The workflow runs under a dummy display and measures input-update work, not key-to-display latency.

| Median across runs | Before | Current |
|---|---:|---:|
| Mean input update | 1.755 ms | 1.774 ms |
| Maximum input update per run | 2.160 ms | 2.144 ms |
| RSS growth | 19,548 KiB | 19,804 KiB |

Samples vary in both directions. These data do not demonstrate a DNA responsiveness gain or improved memory use. The current executable is 40 bytes larger. No editor source changes were needed.

## Rejected experiments and limits

Early whitespace rejection and bit-mask classification measured 59.807 and 59.708 ms against a same-path 59.561 ms baseline. Neither was retained. Stopped-PC sampling suggested the investigation targets; it was not used as cycle attribution or as performance timing.

Unwind frames require balanced same-thread lifetimes. Migrating active stacks and foreign `longjmp` are unsupported. Raw-fork children cannot panic through inherited cleanup frames; cached normal completion can now release copied parent-owner slots, which is a documented behavior difference. No claim of complete fork equivalence or universal platform speedup is made.

Raw paired samples: [applications.json](applications.json). Editor samples: [dna-workflow.json](dna-workflow.json). Qualification and artifact identities: [summary.json](summary.json). Input/source identity proof: [input-proof.json](input-proof.json). Detailed local logs and rejected probes remain under `build/faster-20261024/` and the sibling editor's `build/faster-20261024/`.
