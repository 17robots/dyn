#include "dyn.h"
#include <stdint.h>
#include <string.h>

static const DynTarget targets[] = {
    {"wasm32-wasi", "wasm32-unknown-wasi", NULL, "wasm32", "wasi",
     "wasm", "none", "little", "32", true},
    {"wasm32-browser", "wasm32-unknown-unknown", NULL, "wasm32", "browser",
     "wasm", "none", "little", "32", true},
    {"x86_64-linux", "x86_64-unknown-linux-gnu", "/lib64/ld-linux-x86-64.so.2",
     "x86_64", "linux", "sysv", "none", "little", "64", true},
    {"aarch64-linux", "aarch64-unknown-linux-gnu", "/lib/ld-linux-aarch64.so.1",
     "aarch64", "linux", "sysv", "none", "little", "64", true},
    {"riscv64-linux", "riscv64-unknown-linux-gnu", "/lib/ld-linux-riscv64-lp64d.so.1",
     "riscv64", "linux", "lp64d", "none", "little", "64", true},
    /* Bare metal: the QEMU virt board, machine mode, no operating system. */
    {"riscv64-none", "riscv64-unknown-none-elf", NULL, "riscv64", "none", "lp64d",
     "none", "little", "64", true},
    /* Bare metal, 32-bit: the QEMU virt board with RV32GC, machine mode. */
    {"riscv32-none", "riscv32-unknown-none-elf", NULL, "riscv32", "none", "ilp32d",
     "none", "little", "32", true},
    {"riscv32-none-soft", "riscv32-unknown-none-elf", NULL, "riscv32", "none", "ilp32",
     "none", "little", "32", true},
    /* Bare metal, 32-bit Arm: the QEMU mps2-an500 board, Cortex-M7 with a
       double-precision FPU. */
    {"thumbv7em-none", "thumbv7em-none-eabihf", NULL, "thumbv7em", "none", "aapcs",
     "none", "little", "32", true},
    {"thumbv7em-none-soft", "thumbv7em-none-eabi", NULL, "thumbv7em", "none", "aapcs-soft",
     "none", "little", "32", true},
    /* NUCLEO-H753ZI: Cortex-M7, flash boot, AXI SRAM data and DTCM stack. */
    {"thumbv7em-none-nucleo-h753zi", "thumbv7em-none-eabihf", NULL, "thumbv7em", "none", "aapcs",
     "none", "little", "32", true},
    {"x86_64-macos", "x86_64-apple-macosx", NULL, "x86_64", "darwin", "sysv",
     "system", "little", "64", true},
    {"aarch64-macos", "arm64-apple-macosx", NULL, "aarch64", "darwin", "aapcs",
     "system", "little", "64", true},
    {"aarch64-windows", "aarch64-pc-windows-msvc", NULL, "aarch64", "windows",
     "aapcs", "system", "little", "64", true},
    {"x86_64-windows", "x86_64-pc-windows-msvc", NULL, "x86_64", "windows",
     "win64", "system", "little", "64", true}};

const DynTarget *dyn_target_find(const char *name) {
  for (size_t i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i)
    if (!strcmp(name, targets[i].name))
      return &targets[i];
  return NULL;
}

const DynTarget *dyn_target_at(size_t index) {
  return index < sizeof(targets) / sizeof(targets[0]) ? &targets[index] : NULL;
}

const char *dyn_target_property(const DynTarget *target, const char *key) {
  if (!strcmp(key, "arch"))
    return target->arch;
  if (!strcmp(key, "kernel"))
    return target->kernel;
  if (!strcmp(key, "abi"))
    return target->abi;
  if (!strcmp(key, "libc"))
    return target->libc;
  if (!strcmp(key, "endian"))
    return target->endian;
  if (!strcmp(key, "pointer_bits"))
    return target->pointer_bits;
  /* Floating point in software: the soft-float ABIs, whose code calls the
     dyn_soft_* helpers. Everything else has a hardware FPU. */
  if (!strcmp(key, "float"))
    return !strcmp(target->abi, "ilp32") || !strcmp(target->abi, "aapcs-soft") ? "soft" : "hard";
  /* Linux and macOS share POSIX code: one #target(family: unix) file serves
     both. Every other kernel is its own family. */
  if (!strcmp(key, "family"))
    return !strcmp(target->kernel, "linux") || !strcmp(target->kernel, "darwin") ? "unix" : target->kernel;
  /* Standard input, output and error: every target but the browser. */
  if (!strcmp(key, "streams"))
    return strcmp(target->kernel, "browser") ? "yes" : "no";
  return NULL;
}

/* Dyn's portable Linux syscall numbers are the x86-64 ones. Each maps to the
   target's call of the same name; a call the target lacks stays an error that
   names its replacement. Two calls map to a superset whose extra trailing
   argument is zero: dup2 to dup3 and epoll_wait to epoll_pwait. Number
   translation does not change argument order or structure layout: clone takes
   tls before child_tid on aarch64 and riscv64, and struct stat, struct
   epoll_event and riscv64's struct sigaction differ from x86-64's. */
enum { NONE = 0xFFFF };
static const struct {
  uint16_t portable, aarch64, riscv64;
  const char *name, *replacement;
} linux_syscalls[] = {
#include "linux_syscalls.inc"
};

static size_t linux_syscall_row(uint64_t source) {
  size_t low = 0, high = sizeof(linux_syscalls) / sizeof(linux_syscalls[0]);
  while (low < high) {
    size_t middle = low + (high - low) / 2;
    if (linux_syscalls[middle].portable < source) low = middle + 1;
    else high = middle;
  }
  return low < sizeof(linux_syscalls) / sizeof(linux_syscalls[0]) &&
                 linux_syscalls[low].portable == source
             ? low
             : SIZE_MAX;
}

bool dyn_target_syscall_number(const DynTarget *target, uint64_t source,
                               uint64_t *native) {
  if (strcmp(target->kernel, "linux"))
    return false;
  if (!strcmp(target->arch, "x86_64")) {
    *native = source;
    return true;
  }
  size_t row = linux_syscall_row(source);
  if (row == SIZE_MAX) return false;
  uint16_t number = !strcmp(target->arch, "aarch64")   ? linux_syscalls[row].aarch64
                    : !strcmp(target->arch, "riscv64") ? linux_syscalls[row].riscv64
                                                       : NONE;
  if (number == NONE) return false;
  *native = number;
  return true;
}

bool dyn_target_syscall_name(uint64_t source, const char **name, const char **replacement) {
  size_t row = linux_syscall_row(source);
  if (row == SIZE_MAX) return false;
  *name = linux_syscalls[row].name;
  *replacement = linux_syscalls[row].replacement;
  return true;
}

unsigned dyn_target_pointer_bytes(const DynTarget *target) {
  return !strcmp(target->pointer_bits, "32") ? 4 : 8;
}
