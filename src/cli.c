#include "dyn.h"
#include <stdio.h>
#include <string.h>

void dyn_cli_help(const char *command) {
  (void)command;
  puts("Dyn compiler\n\nUsage: dyn <command> [options] <directory>\n\n"
       "Commands:\n  check    parse and validate module\n  build    build "
       "executable module\n  run      build and run executable module\n"
       "  help     show help\n  version  show version\n"
       "  test     not implemented\n  fmt      not implemented\n  clean    not "
       "implemented\n\n"
       "Build options:\n  --output <path>  --debug  --release\n"
       "  --emit-ir  --emit-object  --emit-asm  --no-link\n  --target "
       "x86_64-linux\n"
       "  --link <object-archive-or-so>  (repeatable explicit FFI input)\n"
       "Global options:\n  --quiet  --verbose  --warnings-as-errors  "
       "--no-warnings");
}

int dyn_cli_parse(int argc, char **argv, DynOptions *o) {
  memset(o, 0, sizeof(*o));
  o->target = "x86_64-linux";
  if (argc < 2)
    return 2;
  o->command = argv[1];
  for (int i = 2; i < argc; ++i) {
    const char *a = argv[i];
    if (strcmp(a, "--output") == 0 || strcmp(a, "--target") == 0 ||
        strcmp(a, "--link") == 0) {
      if (++i >= argc) {
        fprintf(stderr, "error: %s requires a value\n", a);
        return 2;
      }
      if (strcmp(a, "--output") == 0)
        o->output = argv[i];
      else if (strcmp(a, "--target") == 0)
        o->target = argv[i];
      else if (o->link_input_count == 64) {
        fprintf(stderr, "error: at most 64 --link inputs are supported\n");
        return 2;
      } else
        o->link_inputs[o->link_input_count++] = argv[i];
    } else if (strcmp(a, "--debug") == 0)
      o->release = false;
    else if (strcmp(a, "--release") == 0)
      o->release = true;
    else if (strcmp(a, "--quiet") == 0)
      o->quiet = true;
    else if (strcmp(a, "--verbose") == 0)
      o->verbose = true;
    else if (strcmp(a, "--emit-ir") == 0)
      o->emit_ir = true;
    else if (strcmp(a, "--emit-object") == 0)
      o->emit_object = true;
    else if (strcmp(a, "--emit-asm") == 0)
      o->emit_asm = true;
    else if (strcmp(a, "--no-link") == 0)
      o->no_link = true;
    else if (strcmp(a, "--warnings-as-errors") == 0)
      o->warnings_as_errors = true;
    else if (strcmp(a, "--no-warnings") == 0)
      o->no_warnings = true;
    else if (a[0] == '-') {
      fprintf(stderr, "error: unknown option '%s'\n", a);
      return 2;
    } else if (!o->input)
      o->input = a;
    else {
      fprintf(stderr, "error: unexpected argument '%s'\n", a);
      return 2;
    }
  }
  return 0;
}
