# Dense loop-ID repair

Original debug compiler crashed SIGSEGV (-11) on first retained browser Wasm repeat. Exact retained source: `/home/mdray/.cache/dyn-tmp/dyn-wasm-rk1uubyl/module`. GDB recorded `wasm_object_impl` symbol serialization calling strlen through `wstr` with name pointer `0x200000000`.

IR had 787 statements but maximum loop ID923. Wasm allocates statement_count+1 WLoop entries. Out-of-bounds loop writes corrupted immediately adjacent symbol storage. Checked IR requires FOR and BREAK/CONTINUE IDs below statement_count (`ir.c:364-365`). Inliner disjoint-range reservation violated this invariant.

Repair collects/sorts unique original loop IDs and consistently remaps FOR/BREAK/CONTINUE across private expanded output, including retained prefixes. Allocation/work bounded by 2^22 statement cap, overflow-safe. Missing targets reject expansion. No budget or physical record-growth increase.

Verified:
- Deterministic 202-caller sparse-ID fixture fails pre-fix assertion with SIGABRT (-6); fixed passes.
- Direct UINT32_MAX/17 identity remap and unmapped-target rejection.
- ASan/UBSan complete current expression/loop harness passes.
- 30 separate temporary-directory runs of full browser Wasm test pass, including debug/release, Node execution, C ABI, arenas and canvas. Expected frontend-negative failures remain expected.
- Existing inlining-expressions, inlining-casts, inlining-budget, native-leaf-inline and native-optimization pass.
- Independent static review: no findings.

No global rebuild or runtime timings. Isolated debug compiler: ../dyn-loopfix.
