#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static bool is_command(const DynOptions *o, const char *s) {
  return strcmp(o->command, s) == 0;
}
int main(int argc, char **argv) {
  DynOptions o;
  int cli = dyn_cli_parse(argc, argv, &o);
  if (cli) {
    dyn_cli_help(NULL);
    return cli;
  }
  if (is_command(&o, "help")) {
    dyn_cli_help(o.input);
    return 0;
  }
  if (is_command(&o, "version")) {
    puts("dyn 0.1.0-dev");
    return 0;
  }
  bool run = is_command(&o, "run");
  if (!is_command(&o, "check") && !is_command(&o, "build") && !run) {
    fprintf(stderr, "error: command '%s' is not implemented\n", o.command);
    return 2;
  }
  if (!o.input) {
    fprintf(stderr, "error: %s requires a module directory\n", o.command);
    return 2;
  }
  if (run && o.no_link) {
    fprintf(stderr, "error: run cannot be combined with --no-link\n");
    return 2;
  }
  if (!dyn_path_is_directory(o.input)) {
    fprintf(stderr, "error: input must be a module directory: '%s'\n", o.input);
    return 2;
  }
  if (strcmp(o.target, DYN_TARGET_NAME) != 0) {
    fprintf(stderr, "error: target '%s' is not implemented; supported target: "
                    DYN_TARGET_NAME "\n",
            o.target);
    return 2;
  }
  DynSources sources;
  int result = dyn_sources_load(o.input, &sources);
  if (result)
    return result;
  DynSources project_sources = {0};
  result = dyn_module_load_project(o.input, &sources, &project_sources);
  if (result) {
    dyn_sources_free(&sources);
    return result;
  }
  dyn_sources_free(&sources);
  sources = project_sources;
  char *main_path = dyn_path_join(o.input, "main.dyn");
  bool build = is_command(&o, "build") || run;
  DynCheckResult checked = dyn_check_sources(&sources, main_path, build);
  if (checked.errors) {
    dyn_sources_free(&sources);
    free(main_path);
    return 1;
  }
  if (!build) {
    if (!o.quiet)
      puts("ok");
    dyn_sources_free(&sources);
    free(main_path);
    return 0;
  }
  char *base = dyn_path_basename(o.input);
  char run_output[] = "/tmp/dyn-run-XXXXXX";
  if (run) {
    int temporary = mkstemp(run_output);
    if (temporary < 0) {
      perror("error: create run executable");
      dyn_sources_free(&sources);
      free(main_path);
      free(base);
      return 2;
    }
    close(temporary);
    remove(run_output);
  }
  const char *output = run ? run_output : o.output ? o.output : base;
  char object[4096], ir[4096], assembly[4096];
  snprintf(object, sizeof(object), "%s.o", output);
  snprintf(ir, sizeof(ir), "%s.ll", output);
  snprintf(assembly, sizeof(assembly), "%s.s", output);
  DynSource module_source = {0};
  result = dyn_sources_merge(&sources, main_path, &module_source);
  if (!result)
    result = dyn_codegen_main(&module_source, object, o.emit_ir ? ir : NULL,
                              o.emit_asm ? assembly : NULL, o.release);
  dyn_source_free(&module_source);
  if (!result && !o.no_link)
    result = dyn_link_executable(object, output, o.link_inputs,
                                 o.link_input_count, o.verbose);
  if (!o.emit_object && !o.no_link)
    remove(object);
  if (!result && !o.quiet)
    printf("built %s\n", o.no_link ? object : output);
  if (!result && run) {
    pid_t child = fork();
    if (child < 0) {
      perror("error: run");
      result = 2;
    } else if (child == 0) {
      execl(output, output, (char *)NULL);
      _exit(127);
    } else {
      int status = 0;
      if (waitpid(child, &status, 0) < 0) {
        perror("error: run");
        result = 2;
      } else if (WIFEXITED(status))
        result = WEXITSTATUS(status);
      else
        result = 128 + WTERMSIG(status);
    }
    remove(output);
  }
  dyn_sources_free(&sources);
  free(main_path);
  free(base);
  return result;
}
