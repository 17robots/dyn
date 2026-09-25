# Threads and atomics

Linux x86-64 and AArch64 provide caller-stack threads, futex mutexes, condition variables,
counting semaphores, once initialization, and sequentially consistent
32/64-bit atomics. `thread.spawn(&thread, stack, entry, context)` never allocates: caller keeps
both thread handle and stack storage stable until `thread.join`. Entry status is currently discarded.

`std/thread` provides thread lifecycle; `std/sync` provides atomic and synchronization types.
Atomic objects must be naturally aligned. `Mutex` is non-recursive. Moving a live `Thread`,
`Mutex`, or atomic object while another thread references it is invalid. These low-level APIs do
not provide language TLS, cancellation, detach, or cross-platform implementations. Condition waits may
wake spuriously and must be used in a predicate loop. A successful `once_begin` must always be
paired with `once_complete`.
Debug stack traces use 64 bounded, atomically claimed per-thread slots with 64 frames each.
They allocate nothing; tracing is dropped when capacity is exhausted and release builds omit it.
