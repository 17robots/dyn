# Experimental compact JSON reader, 2026-10-24

A separate read-only DOM inspired by compact tagged-value designs is available
as `std/encoding/json/read`. No yyjson source code was copied. The existing
mutable JSON module, application benchmark source, compiler, and DNA source are
unchanged. API and lifetime rules are in the [reader guide](../../guide/json-read.md).

Final retained-module median times on the fixed 60,000-record JSONL report:
existing mutable Dyn DOM 55.896 ms; compact read-only Dyn DOM 39.844 ms; GCC with
yyjson 13.300 ms. This is about 29% lower runtime than the mutable Dyn path, while yyjson
remains about 3 times faster. These are application/library measurements on one
Linux x64 host, not a language-wide ranking.

The read-only variant uses a complete DOM, parses ignored fields normally, owns
its input text, and validates the same output/schema. It does not use typed
schema deserialization or scan known source positions. The archived
[application source](main.dyn) changes only the report's DOM adapter; mutable
JSON remains used for output. The canonical benchmark source is not overwritten.
[Raw samples](applications.json) contain fifteen rotating paired samples after
two warmups on CPU 2. Builds and tests did not overlap measurement.

## Design and tradeoffs

Values occupy 16 bytes rather than the mutable tree's 72 bytes. Nodes are
contiguous; containers retain subtree spans rather than parent/sibling links.
One owned input buffer is decoded in place. Positive u64 and negative i64 values
are stored directly; decimal/exponent and larger integers use finite binary64.
This intentionally loses original numeric spelling and rejects real overflow.
The tree cannot be mutated or passed to the mutable writer directly.

The implementation parses once, grows node storage in place in a stable caller
arena, and trims unused tail capacity. Peak capacity can exceed final retained
storage. Strings and nodes share the arena lifetime; Value records cannot be
moved independently of their children.

The first compact implementation measured 50.5 ms. Tighter scalar scanning and
fewer internal accessor calls reduced it to about 40 ms. An aligned word scanner
measured 45.5 ms and was rejected. No compiler-budget changes or parser-specific
native intrinsics were added.

## Verification

Focused host debug/release checks cover independent Python-generated trees,
malformed inputs, Unicode/escapes, owned input, numeric boundaries/signed zero,
duplicates/empty keys, iterators, depth, buffer growth, misaligned backing, rollback
and peak/exhaustion panics. All eight RV32/Thumb hard/soft debug/release guest
checks passed, with soft-image instruction audits. Independent review found no
remaining concrete correctness finding under the documented pointer/lifetime
contract. The application adapter also passed existing escaped-schema,
malformed/schema-negative, and stdout-failure fixtures against the C comparator.

Final registered qualification passed **205/205 gates, zero skips**, in one
uninterrupted final-state run. All 666 source/runtime/test/tool hashes stayed
unchanged through qualification and final measurements. A separate 1,500-case
randomized acceptance/root-shape/rollback proof passes in debug and release;
[its exact cases and oracle outcomes](acceptance-cases.json) are archived. This
is finite test coverage, not exhaustive parser qualification.

During qualification, inspection found that the original node bound assumed
complete JSON. Truncated nesting such as `[[[` could panic. The hard limit now
allows one node per source byte; the smaller estimate is only an initial
capacity hint. Both debug/release [before/fixed regressions](bound-regression.json)
confirm the issue, and the durable suite includes 379 invalid cases, including
truncated nesting. The earlier interrupted qualification run is not counted.

For the first two corpus records, mutable parsing retains and peaks at 1,184
arena bytes. Read-only parsing retains 616 bytes and peaks at 728. The compact
DOM uses 25 records including keys (400 node bytes), versus 14 mutable nodes
(1,008 node bytes). Input storage, padding and other process memory are separate;
16-byte records do not imply 4.5 times less process memory. See
[arena-storage.json](arena-storage.json).

[Summary and artifact identities](summary.json), [qualification counts](qualification.json)
and [raw paired samples](applications.json) preserve the final evidence. The
paired bootstrap interval for the compact/current median-time ratio is
0.7093–0.7156 (10,000 resamples; finite same-host samples).

The adapter executable grows from 184,416 to 200,544 bytes because it links the
new reader alongside the existing mutable reader/writer and server path. These
are executable sizes, not total process footprints; C's external yyjson library
is not included in its executable size.

No DNA migration or editor responsiveness claim is part of this experiment.
The mutable parser's source hash is unchanged. The new reader is opt-in and
experimental, including its numeric and node-lifetime contracts.


To build the archived application adapter against the source SDK:

```sh
DYN_SDK=/path/to/compiler /path/to/compiler/build/dyn-release build \
  /path/to/compiler/docs/performance/2026-10-24-compact-json \
  --release --opt-level 3 --cpu generic --no-cache --output /tmp/json-read-app
/tmp/json-read-app report /path/to/events.jsonl
```

Local full logs, source hashes, discarded variants, the randomized proof driver,
and isolated SDK snapshots remain in `build/compact-json-20261024/`.
