# Concurrency

Dyn provides several concurrency primitives in standard library to enable safe and efficient parallel programming.

## Threads

Threads allow multiple execution paths to run simultaneously. Each thread has its own stack and can execute code independently.

**Use threads when:**

- Performing CPU-bound parallel computations
- Need true parallel execution across multiple cores
- Tasks are largely independent and don't share much data

**Key considerations:**

- Thread creation has overhead - use for longer-running tasks
- Shared data requires synchronization (see below)
- Too many threads can degrade performance

## Async/Await

Async functions allow concurrent I/O-bound operations without blocking. When you `await` an async operation, current task yields and can resume later.

**Use async/await when:**

- Working with I/O operations (files, network, etc.)
- Need to coordinate many lightweight concurrent tasks
- Want cooperative multitasking without threading overhead

**Key considerations:**

- Single-threaded cooperative multitasking
- Async functions that don't await can block
- Great for high I/O concurrency scenarios

## Channels

Channels provide a way for concurrent tasks to communicate by sending messages.

**Use channels when:**

- Need safe communication between threads or async tasks
- Want to share data without explicit locking
- Following message-passing patterns

**Key considerations:**

- Buffered vs unbuffered channels have different behaviors
- Sending blocks if buffer is full (unbuffered channels always block on send)
- Receiving blocks if no data is available

## Mutexes

Mutexes (mutual exclusions) protect shared data by ensuring only one task can access it at a time.

**Use mutexes when:**

- Multiple tasks need to access mutable shared data
- Lock-free alternatives aren't available
- Need fine-grained control over synchronization

**Key considerations:**

- Always acquire and release in matching pairs (defer helps)
- Never acquire a mutex you already hold on same task
- Minimize time spent holding locks to reduce contention

## Atomic Operations

Atomics provide lock-free operations on primitive types for simple synchronization needs.

**Use atomics when:**

- Need simple counters, flags, or state indicators
- Want to avoid mutex overhead
- Working with primitive types that support atomic ops

**Key considerations:**

- Limited to specific operations (load, store, compare-and-swap, etc.)
- Memory ordering semantics are important for correctness
- Not suitable for complex data structures

## Choosing Right Primitive

| Scenario                | Recommended Approach   |
|------------------------|----------------------|
| CPU parallel computation | Threads              |
| High I/O concurrency   | Async/Await           |
| Task coordination       | Channels             |
| Shared mutable data     | Mutexes              |
| Simple counters/flags   | Atomics              |
| Mixed workloads        | Combination of above |
