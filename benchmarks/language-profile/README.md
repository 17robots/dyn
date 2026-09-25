# Dyn versus C microprofile

Both programs anonymously map 64 MiB, fill every byte, calculate the same checksum, unmap, and exit.
They use direct Linux syscalls and no libc. Build optimized static executables from repository root:

```sh
./build/dyn build benchmarks/language-profile/dyn --release --output build/profile-dyn
cc -O2 -static -nostdlib -fno-stack-protector \
  benchmarks/language-profile/c/main.c -o build/profile-c
```

This measures two bounded loops and memory traffic, not whole-language performance. Dyn retains its
normal overflow, bounds, pointer, and alignment safety semantics; C source contains no equivalent
per-access checks.

## Sample result

On the development x86-64 machine, 30 alternating runs after warmup produced:

| Metric | Dyn | C |
|---|---:|---:|
| Median wall time | 9.960 ms | 13.353 ms |
| Peak RSS | 65,544 KiB | 65,544 KiB |
| Executable file size | 9,176 bytes | 9,256 bytes |
| ELF text size | 705 bytes | 780 bytes |

Results are machine-specific. Release builds run LLVM's `default<O2>` pipeline. Safety checks remain
enabled; LLVM removes or vectorizes them only when it can prove that doing so preserves behavior.
LLVM vectorizes the fill loop. Typed-IR range analysis proves the bounded Dyn checksum cannot
overflow, so removing its per-iteration guard preserves checked-arithmetic semantics. Possible
aliases, writes through references, calls, defers, or nested control invalidate that proof. Dyn
measured about 9.2x faster than its former backend-only "optimized" build, which took 91.282 ms.
The advantage over C in this sample is machine-specific and is not a general language result.
