# Writing and modifying Dyn examples

- Read the current idiomatic Dyn guide and memory contracts in `../docs` when
  working in the combined workspace. `../docs/agent-guide.md` describes declaration
  queries, memory guarantees and validation. `../PROMPT.md` is a historical compiler
  brief, not application instructions.
- Look up actual SDK declarations with `dyn docs MODULE_DIRECTORY --json` (or
  Markdown output). The export is syntax-only; check the consuming application to
  resolve imports and target availability. Never invent APIs from another language.
- Each returned or retained pointer/slice needs known backing storage and a known
  invalidation event. Caller output and scratch must have compatible lifetimes;
  copy retained data before scratch is reclaimed. An arena argument does not imply
  all inputs were copied. Do not independently mutate copied arena/map descriptors.
- For independently deleted objects, use slot-map handles and reacquire views at
  the point of use. Use a disjoint caller-owned copy when data must survive deletion.
  Generation backing stays alive and is initialized to zero only once.
- Handle capacity/provider failures explicitly. Close native resources and join
  workers before reclaiming their storage. Do not test by reading expired pointers.
- Build and execute changed examples in debug and release when behavior changes.
  In the workspace, `just test-agent-readiness` checks memory/query contracts.
  Standalone: set `DYN` to the installed compiler, then use this directory's
  `just build`/`just run` recipes with `PROJECT` and `MODE` environment variables.
