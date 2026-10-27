`condition_wait_timeout(condition, mutex, nanoseconds)` waits with a relative,
monotonic timeout. Hold the mutex before calling it and always recheck the
protected predicate after a successful return:

```dyn
sync.lock(&mutex)
for !ready {
  waited := sync.condition_wait_timeout(&condition, &mutex, 250000000)
  if !waited.ok { break }
  if waited.status == sync.ConditionWaitStatus.TimedOut { break }
}
sync.unlock(&mutex)
```

`ConditionWaitResult` contains `ok`, `status`, `kind` and the native `error`.
`Signaled` and `TimedOut` are both successful outcomes. Signaled may represent a
spurious wake. Timeout does not mean that the predicate is false: a signal can
race with expiration. Zero returns TimedOut without unlocking. Negative
nanoseconds return InvalidInput without unlocking. All other returns reacquire
the mutex, including native or clock errors. Scheduling and mutex reacquisition
can extend the total call duration beyond the timeout.

Interrupted waits retry using the original monotonic deadline. Windows rounds
positive fractions up to milliseconds and splits waits exceeding its finite
DWORD range. Linux uses relative futex timeouts. macOS uses the public
[os_sync_wait_on_address_with_timeout ABI](https://github.com/apple-oss-distributions/libplatform/blob/main/include/os/os_sync_wait_on_address.h)
with OS_CLOCK_MACH_ABSOLUTE_TIME; its existing deployment floor remains 15.0.
The native waiting behavior follows the
[Linux futex contract](https://man7.org/linux/man-pages/man2/FUTEX_WAIT.2const.html)
and [Windows WaitOnAddress contract](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitonaddress).
