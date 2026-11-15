# 09 · primes

Count the primes below a limit, on as many threads as you like.

```sh
dyn run examples/09-primes --release -- 10000000 8
```

Each worker reports its share on standard error; the total goes to standard
output.

## What it teaches

- **Threads with typed context.** `thread.spawn_with_size(arena, stack_size,
  work, &workers[i])` starts `work` on a new thread with its own stack. The
  entry point is `fn work(w: *Worker) isize`: `spawn` infers the context type
  from it and checks that the pointer you pass is a `*Worker`.
- **Who owns what.** Each `Worker` is touched only by its own thread until
  `thread.join` returns, so its counts need no locks. The workers live in
  `main`'s frame, which outlives every thread because main joins them all
  before it returns.
- **Atomics.** The one shared value is `Shared.next_block`.
  `sync.fetch_add_u64` takes the next block in one indivisible step, so no
  two workers ever count the same numbers, and a fast worker simply takes
  more blocks.
- **Sizing a pool.** `thread.cpu_count()` is the number of CPUs this process
  may run on. The default uses all of them.
- **Release builds.** Compare `dyn run examples/09-primes -- 10000000` with
  the same command and `--release`. Debug builds check every addition and
  multiplication for overflow; release builds do not, and optimize.

## Exercises

1. Make each worker also find the longest gap between consecutive primes in
   its blocks. How do you combine gaps that span two blocks?
2. Replace trial division with a segmented sieve: each block marks the
   multiples of small primes in a `[BlockSize]bool` on the worker's stack.
3. Print progress while the workers run by having main read an atomic
   counter of finished blocks with `sync.load_u64`.
