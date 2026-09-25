#include "dyn.h"
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
    {"aarch64-macos", "arm64-apple-macosx", NULL, "aarch64", "darwin", "aapcs",
     "system", "little", "64", true},
    {"x86_64-windows", "x86_64-pc-windows-msvc", NULL, "x86_64", "windows",
     "win64", "system", "little", "64", true}};

const DynTarget *dyn_target_find(const char *name) {
  for (size_t i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i)
    if (!strcmp(name, targets[i].name))
      return &targets[i];
  return NULL;
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
  return NULL;
}

bool dyn_target_syscall_number(const DynTarget *target, uint64_t source,
                               uint64_t *native) {
  if (strcmp(target->kernel, "linux"))
    return false;
  if (!strcmp(target->arch, "x86_64")) {
    *native = source;
    return true;
  }
  /* Dyn's portable Linux syscall IDs are the x86-64 IDs. Only calls with the
     same argument ABI are mapped; architecture-specific calls stay errors. */
  static const struct {
    uint16_t portable, aarch64;
  } map[] = {
      {0, 63},    {1, 64},    {3, 57},   {8, 62},   {9, 222},   {11, 215},
      {13, 134},  {16, 29},   {24, 124}, {32, 23},  {33, 24},   {35, 101},
      {39, 172},  {41, 198},  {42, 203}, {43, 202}, {44, 206},  {45, 207},
      {48, 210},  {49, 200},  {50, 201}, {51, 204}, {52, 205},  {54, 208}, {55, 209}, {56, 220},
      {59, 221},  {60, 93},   {61, 260}, {62, 129}, {72, 25},   {73, 32}, {74, 82},
      {76, 45},   {77, 46},   {79, 17},   {80, 49},  {90, 52},  {109, 154}, {110, 173},
      {160, 261}, {186, 178}, {202, 98}, {217, 61}, {228, 113}, {232, 22},
      {233, 21},  {254, 27},  {255, 28}, {257, 56}, {258, 34},  {263, 35},
      {264, 38},  {265, 37},  {266, 36}, {267, 78}, {271, 73},  {291, 20},
      {293, 59},  {294, 26},  {318, 278}, {332, 291}, {437, 437}};
  for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); ++i)
    if (map[i].portable == source) {
      *native = map[i].aarch64;
      return true;
    }
  return false;
}

unsigned dyn_target_pointer_bytes(const DynTarget *target) {
  return !strcmp(target->pointer_bits, "32") ? 4 : 8;
}
