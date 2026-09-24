#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void) {
  char text[] =
      "pub struct Pair { x: i64, y: i64 }\n"
      "pub enum(u8) State { off, on }\n"
      "pub type Number = i64\n"
      "pub distinct type Handle = u64\n"
      "pub count: i64 = 1\n"
      "pub extern foreign_count \"foreign_count\": i64\n"
      "pub extern fn foreign_add \"foreign_add\" (a: i64, b: i64) i64\n"
      "pub fn add(a: i64, b: i64) i64 { return a + b }\n"
      "fn private() i64 { return 9 }\n";
  DynSource source = {.path = "module/main.dyn", .text = text,
                      .length = strlen(text)};
  DynSources sources = {.items = &source, .count = 1};
  DynInterface made, loaded;
  assert(dyn_interface_build(&sources, &made) == 0);
  assert(strstr(made.data, "pub struct Pair{x:i64,y:i64}\n"));
  assert(strstr(made.data, "pub extern count \"count\":i64\n"));
  assert(strstr(made.data, "pub fn add(a:i64,b:i64)i64{}\n"));
  assert(!strstr(made.data, "return"));
  assert(!strstr(made.data, "private"));
  DynSource declaration_source = {.path = "cached/interface.dyn",
      .text = made.data, .length = made.length};
  DynSources declaration_sources = {.items = &declaration_source, .count = 1};
  DynInterface rebuilt;
  assert(dyn_interface_build(&declaration_sources, &rebuilt) == 0);
  dyn_interface_free(&rebuilt);

  char inferred_text[] = "pub inferred := 1\n";
  DynSource inferred_source = {.path = "module/inferred.dyn",
      .text = inferred_text, .length = strlen(inferred_text)};
  DynSources inferred_sources = {.items = &inferred_source, .count = 1};
  assert(dyn_interface_build(&inferred_sources, &rebuilt) == 3);


  char path[] = "/tmp/dyn-interface-XXXXXX";
  int descriptor = mkstemp(path); assert(descriptor >= 0); close(descriptor);
  assert(dyn_interface_store(path, "x86_64-linux", "dyn-c-1", &made) == 0);
  assert(dyn_interface_load(path, "x86_64-linux", "dyn-c-1",
                            made.source_hash, &loaded) == DYN_INTERFACE_HIT);
  assert(loaded.interface_hash == made.interface_hash);
  assert(loaded.length == made.length && !memcmp(loaded.data, made.data, made.length));
  dyn_interface_free(&loaded);
  assert(dyn_interface_load(path, "aarch64-linux", "dyn-c-1",
                            made.source_hash, &loaded) == DYN_INTERFACE_MISS);
  assert(dyn_interface_load(path, "x86_64-linux", "dyn-c-2",
                            made.source_hash, &loaded) == DYN_INTERFACE_MISS);
  assert(dyn_interface_load(path, "x86_64-linux", "dyn-c-1",
                            made.source_hash + 1, &loaded) == DYN_INTERFACE_MISS);

  FILE *file = fopen(path, "r+b"); assert(file);
  assert(fseek(file, -1, SEEK_END) == 0); int byte = fgetc(file);
  assert(byte != EOF && fseek(file, -1, SEEK_END) == 0);
  assert(fputc(byte ^ 1, file) != EOF); assert(fclose(file) == 0);
  assert(dyn_interface_load(path, "x86_64-linux", "dyn-c-1",
                            made.source_hash, &loaded) == DYN_INTERFACE_MISS);
  unlink(path); dyn_interface_free(&made);
  return 0;
}
