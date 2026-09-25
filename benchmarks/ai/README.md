# Dyn AI authoring trial

On 2026-09-24, six fresh agent contexts attempted one small Dyn task each.
Five compiled on their first check; all six passed independent debug and release
behavior checks after at most one correction. Checked sum needed an explicit cast
for mixed-width arithmetic. This is encouraging evidence for these six tasks,
not a statistically meaningful general score or comparison against other languages.

Tasks: bounded copy, retained arena string, checked sum, validated port parsing,
retained slot-map copy, and an enum state model. Specifications live in
`tasks/manifest.json`. Trial solutions, original attempt logs, hashes and measured
results are preserved in `results/2026-09-24/`.

Each author received a fresh context, the same task instructions and repository/SDK
access; no prior conversation or other solution was supplied. They were instructed
not to inspect the evaluator or other submissions. This is instruction separation,
not an adversarial filesystem boundary. The original report records the compiler
hash used then. Model identity/settings were inherited by the runner and were not
captured as a reproducible model pin. Do not claim cross-model comparability.

To rerun behavior checks on preserved solutions with the current compiler:

```sh
python3 benchmarks/ai/evaluate.py --dyn ./build/dyn \
  --solutions benchmarks/ai/results/2026-09-24 \
  --output build/ai-benchmark/reevaluation.json
```

This reuses historical first-attempt logs; it does not measure new first-attempt
performance. For a new trial, start fresh contexts with only one task specification,
the docs and SDK. Allow at most three compiler attempts, preserve every attempt and
final source, then evaluate separately. Extend tasks before drawing broader conclusions:
async resource cleanup, loops/branches with lifetimes, FFI and larger multi-module apps
are absent here.
