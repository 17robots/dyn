#include "dyn.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void dyn_cli_help(const char *command) {
  (void)command;
  printf("Dyn compiler\n\nUsage: dyn <command> [options] <directory>\n\n"
       "Commands:\n  check    parse and validate module\n  build    build "
       "executable module\n  run      build and run executable module\n"
       "  fmt      canonicalize source whitespace\n"
       "  docs     print public declarations as Markdown\n"
       "  lsp      run stdio language server\n"
       "  cache    inspect or clean shared compilation cache\n"
       "  help     show help\n  version  show version\n\n"
       "Build options:\n  --output <path>  --debug  --release  --debug-info\n"
       "  --emit-ir  --emit-object  --emit-asm  --no-link\n"
       "  --target <x86_64-linux|aarch64-linux|aarch64-macos|x86_64-windows>\n"
       "  --jobs <1..256>\n"
       "  --link <object-archive-or-so>  (repeatable explicit FFI input)\n"
       "Global options:\n  --quiet  --verbose  --timings  --no-cache  "
       "--warnings-as-errors  --no-warnings\n"
       "  --diagnostics json  --check (fmt only)");
}

int dyn_cli_parse(int argc, char **argv, DynOptions *o) {
  memset(o, 0, sizeof(*o));
  o->debug_info = true;
  o->target = dyn_target->name;
  if (argc < 2)
    return 2;
  o->command = argv[1];
  for (int i = 2; i < argc; ++i) {
    const char *a = argv[i];
    if (strcmp(a, "--output") == 0 || strcmp(a, "--target") == 0 ||
        strcmp(a, "--link") == 0 || strcmp(a, "--diagnostics") == 0 ||
        strcmp(a, "--jobs") == 0) {
      if (++i >= argc) {
        fprintf(stderr, "error: %s requires a value\n", a);
        return 2;
      }
      if (strcmp(a, "--output") == 0)
        o->output = argv[i];
      else if (strcmp(a, "--target") == 0)
        o->target = argv[i];
      else if (strcmp(a, "--diagnostics") == 0) {
        if (strcmp(argv[i], "json")) {
          fprintf(stderr, "error: --diagnostics accepts only 'json'\n");
          return 2;
        }
        o->json_diagnostics = true;
      } else if (strcmp(a, "--jobs") == 0) {
        char *end = NULL;
        unsigned long jobs = strtoul(argv[i], &end, 10);
        if (!argv[i][0] || *end || jobs == 0 || jobs > 256) {
          fprintf(stderr, "error: --jobs requires an integer from 1 to 256\n");
          return 2;
        }
        o->jobs = (unsigned)jobs;
      } else if (o->link_input_count == 64) {
        fprintf(stderr, "error: at most 64 --link inputs are supported\n");
        return 2;
      } else
        o->link_inputs[o->link_input_count++] = argv[i];
    } else if (strcmp(a, "--debug") == 0) {
      o->release = false;
      if (!o->debug_info_set) o->debug_info = true;
    } else if (strcmp(a, "--release") == 0) {
      o->release = true;
      if (!o->debug_info_set) o->debug_info = false;
    } else if (strcmp(a, "--debug-info") == 0) {
      o->debug_info = true;
      o->debug_info_set = true;
    }
    else if (strcmp(a, "--quiet") == 0)
      o->quiet = true;
    else if (strcmp(a, "--verbose") == 0)
      o->verbose = true;
    else if (strcmp(a, "--timings") == 0)
      o->timings = true;
    else if (strcmp(a, "--no-cache") == 0)
      o->no_cache = true;
    else if (strcmp(a, "--check") == 0)
      o->format_check = true;
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
