#define _POSIX_C_SOURCE 200809L

#include "dyn.h"
#include "dyn_timing.h"
#include "dyn_location.h"
#include "dyn_ast.h"
#include "frontend.h"
#include "ir.h"
#include "link_elf.h"
#include "link_macho.h"
#include "link_coff.h"
#include "link_wasm.h"
#include "sema.h"
#include "native_asm.h"
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static void global_module_key(const char *name, char *out, size_t capacity) {
  if (!strncmp(name, "dyn_m", 5) && strlen(name) > 21 && name[21] == '_')
    snprintf(out, capacity, "%.21s", name);
  else
    snprintf(out, capacity, "root");
}
static bool module_owns(const char *owner_key, const char *name) {
  if (!owner_key)
    return true;
  char key[32];
  global_module_key(name, key, sizeof(key));
  return !strcmp(owner_key, key);
}
/* The object-file symbol of a Dyn function. Root-module functions keep their
   plain names, except where that would take a name the program also uses for
   a C function (an extern's link name, or exit/_exit, which the runtime calls
   when a C library is linked). Those get a ".dyn" suffix, the same in every
   object file, so the extern and the Dyn function never merge or get renamed
   differently per object. */
static uint64_t interface_bytes(uint64_t hash, const void *data, size_t length) {
  const unsigned char *bytes = data;
  for (size_t i = 0; i < length; ++i)
    hash = (hash ^ bytes[i]) * UINT64_C(1099511628211);
  return hash;
}
static uint64_t interface_span(uint64_t hash, DynSpan span, const DynSource *s) {
  if (span.end_byte > span.start_byte && span.end_byte <= s->length)
    hash = interface_bytes(hash, s->text + span.start_byte,
                           span.end_byte - span.start_byte);
  return interface_bytes(hash, "\n", 1);
}
static uint64_t interface_type(uint64_t hash, DynAstProgram *a, DynType type,
                               const DynSource *s) {
  char name[512];
  dyn_type_format(a, type, s, name, sizeof(name));
  return interface_bytes(hash, name, strlen(name) + 1);
}
/* Everything one object may depend on from the rest of the program, without
   function bodies. Reflection exposes types introduced in bodies, so a
   reflecting program hashes its whole text. */
static uint64_t interface_hash(DynAstProgram *a, const DynSource *s) {
  uint64_t hash = UINT64_C(1469598103934665603);
  for (size_t i = 0; i < a->expression_count; ++i)
    if (a->expressions[i].kind == DYN_EXPR_TYPEOF)
      return interface_bytes(hash, s->text, s->length);
  for (size_t i = 0; i < a->struct_count; ++i)
    hash = interface_span(hash, a->structs[i].span, s);
  for (size_t i = 0; i < a->enum_count; ++i)
    hash = interface_span(hash, a->enums[i].span, s);
  for (size_t i = 0; i < a->alias_count; ++i) {
    hash = interface_span(hash, a->aliases[i].name, s);
    hash = interface_type(hash, a, a->aliases[i].target, s);
  }
  for (size_t i = 0; i < a->global_count; ++i) {
    const DynAstGlobal *global = &a->globals[i];
    hash = interface_span(hash, global->name, s);
    hash = interface_span(hash, global->link_name, s);
    hash = interface_type(hash, a, global->type, s);
    bool flags[] = {global->is_const, global->foreign, global->is_public};
    hash = interface_bytes(hash, flags, sizeof(flags));
    if (global->initializer != DYN_NO_EXPR)
      hash = interface_span(hash, a->expressions[global->initializer].span, s);
  }
  for (size_t i = 0; i < a->function_count; ++i) {
    const DynAstFn *fn = &a->functions[i];
    if (fn->is_instance)
      continue;
    hash = interface_span(hash, fn->name, s);
    hash = interface_span(hash, fn->link_name, s);
    hash = interface_type(hash, a, fn->return_type, s);
    for (uint32_t p = 0; p < fn->param_count; ++p)
      hash = interface_type(hash, a, a->params[fn->param_start + p].type, s);
    bool flags[] = {fn->is_main, fn->foreign, fn->variadic, fn->is_public};
    hash = interface_bytes(hash, flags, sizeof(flags));
    if (fn->variadic)
      hash = interface_type(hash, a, fn->variadic_type, s);
  }
  return hash;
}
uint64_t dyn_codegen_chunk_instances(const DynSource *source,
                                     const DynIrProgram *ir,
                                     const char *owner_key, unsigned chunk,
                                     unsigned chunks) {
  uint64_t hash = UINT64_C(1469598103934665603);
  for (uint32_t i = 0; i < ir->function_count; ++i) {
    const DynIrFunction *fn = &ir->functions[i];
    if (!fn->instance || !module_owns(owner_key, fn->name))
      continue;
    const char *path = source->path;
    unsigned line, column;
    if (chunks > 1)
      dyn_location_get(&ir->locations, source, fn->source_offset, &path, &line, &column);
    if (dyn_chunk_of_path(path, chunks) != chunk)
      continue;
    for (const char *c = fn->name; ; ++c) {
      hash = (hash ^ (unsigned char)*c) * UINT64_C(1099511628211);
      if (!*c) break;
    }
  }
  return hash;
}
/* Assigned or address-taken locals may change; checks of them never carry
   over to later uses. Addresses taken of a field or element count too. */
static bool local_facts_build(DynIrProgram *ir) {
  ir->unstable_locals = calloc(ir->local_count ? ir->local_count : 1, sizeof(*ir->unstable_locals));
  ir->local_statements = calloc(ir->local_count ? ir->local_count : 1, sizeof(*ir->local_statements));
  if (!ir->unstable_locals || !ir->local_statements)
    return false;
  for (size_t i = 0; i < ir->statement_count; ++i) {
    const DynIrStmt *st = &ir->statements[i];
    if (st->kind == DYN_STMT_LOCAL && st->local_id < ir->local_count &&
        !ir->local_statements[st->local_id])
      ir->local_statements[st->local_id] = (uint32_t)i + 1;
    if (st->kind != DYN_STMT_ASSIGN)
      continue;
    /* A plain local assignment has no target expression. */
    if (st->target == DYN_NO_EXPR) {
      if (st->local_id < ir->local_count)
        ir->unstable_locals[st->local_id] = true;
    } else if (ir->expressions[st->target].kind == DYN_EXPR_NAME)
      ir->unstable_locals[ir->expressions[st->target].integer] = true;
  }
  for (size_t i = 0; i < ir->expression_count; ++i) {
    if (ir->expressions[i].kind != DYN_EXPR_UNARY ||
        ir->expressions[i].op != DYN_OP_ADDRESS)
      continue;
    DynExprId root = ir->expressions[i].left;
    while (root != DYN_NO_EXPR &&
           (ir->expressions[root].kind == DYN_EXPR_FIELD ||
            ir->expressions[root].kind == DYN_EXPR_INDEX ||
            ir->expressions[root].kind == DYN_EXPR_SLICE))
      root = ir->expressions[root].left;
    if (root != DYN_NO_EXPR && ir->expressions[root].kind == DYN_EXPR_NAME)
      ir->unstable_locals[ir->expressions[root].integer] = true;
  }
  return true;
}
static int codegen_prepare(const DynSource *source,
                           bool shared, const char *owner_key, DynIrProgram *ir) {
  memset(ir, 0, sizeof(*ir));
  DynAstProgram ast = {0};
  if (!source)
    return 1;
  DynAnalysisResult analysis = dyn_analyze(
      source, &ast,
      (DynAnalysisOptions){.owner_key = owner_key,
                           .main_path = !owner_key || !strcmp(owner_key, "root")
                                            ? source->path
                                            : NULL,
                           .require_main = !shared});
  if (!analysis.checked) {
    dyn_ast_program_free(&ast);
    return 1;
  }
  struct timespec phase = dyn_timing_start(&source->context);
  if (!dyn_ir_lower(&ast, source, ir)) {
    fprintf(stderr, "error: failed to lower typed Dyn IR\n");
    dyn_ast_program_free(&ast);
    return 2;
  }
  ir->interface_hash = interface_hash(&ast, source);
  dyn_ast_program_free(&ast);
  if (!local_facts_build(ir)) {
    dyn_ir_free(ir);
    return 2;
  }
  if (!dyn_location_build(&ir->locations, source)) {
    dyn_ir_free(ir);
    return 2;
  }
  if (!strcmp(dyn_context_target(&source->context)->arch, "wasm32")) {
    for (size_t i = 0; i < ir->function_count; ++i) {
      DynIrFunction *fn = &ir->functions[i];
      if ((fn->foreign && fn->variadic) || !strcmp(fn->name, "dyn_initialize")) {
        fprintf(stderr, "error: browser modules reserve dyn_initialize and do not support C variadic functions\n");
        dyn_ir_free(ir); return 1;
      }
    }
  }
  dyn_timing_phase(&source->context, &phase, "ir");
  return 0;
}
int dyn_codegen_prepare(const DynSource *source, bool shared,
                        const char *owner_key, DynIrProgram *ir) {
  return codegen_prepare(source, shared, owner_key, ir);
}
int dyn_codegen_prepare_owned(DynSource *source, bool shared,
                              const char *owner_key, DynIrProgram *ir) {
  return codegen_prepare(source, shared, owner_key, ir);
}
int dyn_codegen_module(const DynSource *source, const char *object_path,
                       const char *asm_path, bool release,
                       bool debug_info, bool shared, const char *owner_key) {
  DynIrProgram ir;
  int result = dyn_codegen_prepare(source, shared, owner_key, &ir);
  if (result)
    return result;
  result = dyn_codegen_emit(source, &ir, object_path, asm_path,
                            release, debug_info, shared, owner_key, 0, 1);
  dyn_ir_free(&ir);
  return result;
}
/* The prepared program is shared by concurrent emitters and never modified. */
int dyn_codegen_emit(const DynSource *source, const DynIrProgram *prepared,
                     const char *object_path,
                     const char *asm_path, bool release, bool debug_info,
                     bool shared, const char *owner_key, unsigned chunk,
                     unsigned chunks) {
  (void)owner_key;
  if (chunk || chunks != 1) {
    fprintf(stderr, "error: independent emission requires a complete prepared module\n");
    return 2;
  }
  int result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32")
    ? dyn_wasm_object(source, prepared, object_path, true)
    : dyn_native_object(source, prepared, object_path, !release, debug_info, shared, true);
  if (!result && asm_path)
    result = !strcmp(dyn_context_target(&source->context)->arch, "wasm32")
      ? dyn_wasm_assembly(source, prepared, asm_path, true)
      : dyn_native_assembly(object_path, asm_path);
  return result;
}
void dyn_codegen_release(DynIrProgram *ir) { dyn_ir_free(ir); }
int dyn_codegen_main(const DynSource *source, const char *object_path,
                     const char *asm_path, bool release,
                     bool debug_info, bool shared) {
  return dyn_codegen_module(source, object_path, asm_path, release,
                            debug_info, shared, NULL);
}
/* Links Windows output: an executable, or with import_library a DLL and its
   import library. */
static int link_coff(const char *runtime, const char *support, const char *const *objects, size_t object_count,
                     const char *const *link_inputs, size_t link_input_count, const char *temporary,
                     const char *output_path, const char *import_library, bool verbose) {
  const char **inputs = calloc(object_count + link_input_count + 2, sizeof(*inputs));
  if (!inputs)
    return 2;
  size_t count = 0;
  inputs[count++] = runtime;
  inputs[count++] = support;
  for (size_t i = 0; i < object_count; ++i)
    inputs[count++] = objects[i];
  for (size_t i = 0; i < link_input_count; ++i)
    inputs[count++] = link_inputs[i];
  if (verbose) {
    fprintf(stderr, "+ (built-in) link%s -o %s", import_library ? " -dll" : "", temporary);
    for (size_t i = 0; i < count; ++i)
      fprintf(stderr, " %s", inputs[i]);
    fputc('\n', stderr);
  }
  const char *slash = strrchr(output_path, '/');
  const char *backslash = strrchr(output_path, '\\');
  if (backslash && (!slash || backslash > slash))
    slash = backslash;
  DynCoffOptions options = {.shared = import_library != NULL,
                            .entry = import_library ? "DllMainCRTStartup" : "dyn_start",
                            .dll_name = slash ? slash + 1 : output_path,
                            .import_library = import_library};
  int status = dyn_link_coff(inputs, count, temporary, &options);
  free(inputs);
  if (status)
    return 2;
  if (rename(temporary, output_path)) {
    perror("error: rename output");
    remove(temporary);
    return 2;
  }
  return 0;
}
/* Links macOS output with the runtime, explicit inputs and the libSystem
   stub, then moves it into place. */
static int link_macho(const char *runtime, const char *support, const char *const *objects, size_t object_count,
                      const char *const *link_inputs, size_t link_input_count, const char *temporary,
                      const char *output_path, bool shared, bool verbose) {
  char system_stub[4096];
  bool stub = dyn_host_runtime_file("libSystem.tbd", system_stub, sizeof(system_stub));
  const char **inputs = calloc(object_count + link_input_count + 3, sizeof(*inputs));
  if (!inputs)
    return 2;
  size_t count = 0;
  inputs[count++] = runtime;
  inputs[count++] = support;
  for (size_t i = 0; i < object_count; ++i)
    inputs[count++] = objects[i];
  for (size_t i = 0; i < link_input_count; ++i)
    inputs[count++] = link_inputs[i];
  if (stub)
    inputs[count++] = system_stub;
  if (verbose) {
    fprintf(stderr, "+ (built-in) link%s -o %s", shared ? " -dylib" : "", temporary);
    for (size_t i = 0; i < count; ++i)
      fprintf(stderr, " %s", inputs[i]);
    fputc('\n', stderr);
  }
  DynMachOOptions options = {.shared = shared, .entry = "_dyn_start", .install_name = output_path};
  int status = dyn_link_macho(inputs, count, temporary, &options);
  free(inputs);
  if (status)
    return 2;
  if (rename(temporary, output_path)) {
    perror("error: rename output");
    remove(temporary);
    return 2;
  }
  return 0;
}
static int link_wasm(const DynContext *, const char *, const char *,
                     const char *const *, size_t, bool);
int dyn_link_executable_objects(const DynContext *context,
                                const char *const *object_paths,
                                size_t object_count, const char *output_path,
                                const char *const *link_inputs,
                                size_t link_input_count, bool release,
                                bool verbose) {
  char temporary[4096], runtime[4096], support[4096], executable[4096];
  bool dynamic = false;
  for (size_t i = 0; i < link_input_count; ++i) {
    const char *extension = strstr(link_inputs[i], ".so");
    if (extension && (extension[3] == 0 || extension[3] == '.'))
      dynamic = true;
  }
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >=
      (int)sizeof(temporary))
    return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0) {
    perror("error: locate compiler");
    return 2;
  }
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return 2;
  *slash = 0;
  const char *runtime_name =
      !strcmp(dyn_context_target(context)->kernel, "windows")
          ? (!strcmp(dyn_context_target(context)->arch, "aarch64") ? "dynrt_windows_arm64_start.o" : "dynrt_windows_start.o")
      : !strcmp(dyn_context_target(context)->kernel, "darwin")
          ? (!strcmp(dyn_context_target(context)->arch, "x86_64") ? "dynrt_macos_x64_start.o" : "dynrt_macos_start.o")
      : !strcmp(dyn_context_target(context)->kernel, "none")
          ? (!strcmp(dyn_context_target(context)->arch, "riscv32")
                 ? (release ? "dynrt_riscv32_none_release.o" : "dynrt_riscv32_none_start.o")
             : !strcmp(dyn_context_target(context)->arch, "thumbv7em")
                 ? (release ? "dynrt_thumbv7em_none_release.o" : "dynrt_thumbv7em_none_start.o")
                 : (release ? "dynrt_riscv64_none_release.o" : "dynrt_riscv64_none_start.o"))
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? (release ? "dynrt_aarch64_release.o" : "dynrt_aarch64_start.o")
          : !strcmp(dyn_context_target(context)->arch, "riscv64") ? (release ? "dynrt_riscv64_release.o" : "dynrt_riscv64_start.o")
          : (release ? "dynrt_release.o" : "dynrt_start.o");
  bool nucleo = !strcmp(dyn_context_target(context)->name, "thumbv7em-none-nucleo-h753zi");
  bool rv32_soft = !strcmp(dyn_context_target(context)->name, "riscv32-none-soft");
  bool thumb_soft = !strcmp(dyn_context_target(context)->name, "thumbv7em-none-soft");
  if (thumb_soft) runtime_name = release ? "dynrt_thumbv7em_none_soft_release.o" : "dynrt_thumbv7em_none_soft_start.o";
  if (rv32_soft) runtime_name = release ? "dynrt_riscv32_none_soft_release.o" : "dynrt_riscv32_none_soft_start.o";
  if (nucleo) runtime_name = release ? "dynrt_nucleo_h753zi_release.o" : "dynrt_nucleo_h753zi_start.o";
  if (snprintf(runtime, sizeof(runtime), "%s/%s", executable, runtime_name) >=
      (int)sizeof(runtime))
    return 2;
  if (access(runtime, R_OK) &&
      snprintf(runtime, sizeof(runtime), "%s/../lib/dyn/%s", executable,
               runtime_name) >= (int)sizeof(runtime))
    return 2;
  const char *support_name =
      !strcmp(dyn_context_target(context)->kernel, "windows")
          ? (!strcmp(dyn_context_target(context)->arch, "aarch64") ? "dynrt_windows_arm64_support.o" : "dynrt_windows_support.o")
      : !strcmp(dyn_context_target(context)->kernel, "darwin")
          ? (!strcmp(dyn_context_target(context)->arch, "x86_64") ? "dynrt_macos_x64_support.o" : "dynrt_macos_support.o")
      : !strcmp(dyn_context_target(context)->kernel, "none")
          ? (!strcmp(dyn_context_target(context)->arch, "riscv32") ? "dynrt_riscv32_none_support.o"
             : !strcmp(dyn_context_target(context)->arch, "thumbv7em") ? "dynrt_thumbv7em_none_support.o" : "dynrt_riscv64_none_support.o")
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? "dynrt_aarch64_support.o"
          : !strcmp(dyn_context_target(context)->arch, "riscv64") ? "dynrt_riscv64_support.o" : "dynrt_support.o";
  if (nucleo) support_name = "dynrt_nucleo_h753zi_support.o";
  if (rv32_soft) support_name = "dynrt_riscv32_none_soft_support.o";
  if (thumb_soft) support_name = "dynrt_thumbv7em_none_soft_support.o";
  if (snprintf(support, sizeof(support), "%s/%s", executable, support_name) >=
      (int)sizeof(support))
    return 2;
  if (access(support, R_OK) &&
      snprintf(support, sizeof(support), "%s/../lib/dyn/%s", executable,
               support_name) >= (int)sizeof(support))
    return 2;
  bool windows = !strcmp(dyn_context_target(context)->kernel, "windows");
  bool darwin = !strcmp(dyn_context_target(context)->kernel, "darwin");
  const char *linker = darwin ? DYN_DARWIN_LINKER : windows ? DYN_WINDOWS_LINKER : "ld.lld";
  /* DYN_LINKER=external selects the system linker for differential checks. */
  const char *external = getenv("DYN_LINKER");
  bool forced = external && !strcmp(external, "external");
  if (nucleo && forced) {
    fprintf(stderr, "error: NUCLEO-H753ZI requires the built-in linker for its flash/RAM layout\n");
    return 2;
  }
  /* Windows executables link in-process. */
  if (windows && !forced) {
    bool supported = true;
    for (size_t i = 0; supported && i < link_input_count; ++i)
      supported = dyn_link_coff_supported(link_inputs[i]);
    if (supported)
      return link_coff(runtime, support, object_paths, object_count, link_inputs, link_input_count, temporary,
                       output_path, NULL, verbose);
  }
  /* macOS executables link in-process. */
  if (darwin && !forced) {
    bool supported = true;
    for (size_t i = 0; supported && i < link_input_count; ++i)
      supported = dyn_link_macho_supported(link_inputs[i]);
    if (supported)
      return link_macho(runtime, support, object_paths, object_count, link_inputs, link_input_count,
                        temporary, output_path, false, verbose);
  }
  /* Linux executables link in-process. */
  bool bare = !strcmp(dyn_context_target(context)->kernel, "none");
  bool builtin = !forced && (bare || !strcmp(dyn_context_target(context)->kernel, "linux"));
  for (size_t i = 0; builtin && i < link_input_count; ++i)
    builtin = dyn_link_elf_supported(link_inputs[i]);
  if (builtin) {
    const char **inputs = calloc(object_count + link_input_count + 2, sizeof(*inputs));
    if (!inputs)
      return 2;
    size_t input_count = 0;
    inputs[input_count++] = runtime;
    inputs[input_count++] = support;
    for (size_t i = 0; i < object_count; ++i)
      inputs[input_count++] = object_paths[i];
    for (size_t i = 0; i < link_input_count; ++i)
      inputs[input_count++] = link_inputs[i];
    if (verbose) {
      fprintf(stderr, "+ (built-in) link -o %s", temporary);
      for (size_t i = 0; i < input_count; ++i)
        fprintf(stderr, " %s", inputs[i]);
      fputc('\n', stderr);
    }
    /* Bare-metal images load where the board's RAM starts; Cortex-M reads its
       vector table from address zero. */
    bool cortex_m = !strcmp(dyn_context_target(context)->arch, "thumbv7em");
    DynLinkOptions options = {.entry = "_start",
                              .interpreter = dyn_context_target(context)->dynamic_linker,
                              .base = nucleo ? 0x08000000u : bare && !cortex_m ? 0x80000000u : 0, .bare = bare,
                              .data_base = nucleo ? 0x24000000u : 0,
                              .image_end = nucleo ? 0x08200000u : 0, .data_end = nucleo ? 0x24080000u : 0};
    int status = dyn_link_elf(inputs, input_count, temporary, &options);
    free(inputs);
    if (status)
      return 2;
    if (rename(temporary, output_path)) {
      perror("error: rename output");
      return 2;
    }
    return 0;
  }
  if (!forced) {
    fprintf(stderr, "error: unsupported built-in linker input; external linking requires DYN_LINKER=external\n");
    return 2;
  }
  if (windows && !strcmp(dyn_context_target(context)->arch,"aarch64")) {
    fprintf(stderr,"error: external linking for aarch64-windows is unsupported; use DYN_LINKER=builtin\n");
    return 2;
  }
  if (verbose) {
    fprintf(
        stderr, "+ %s %s -o %s %s %s", linker,
        darwin ?
#ifdef __APPLE__
          (!strcmp(dyn_context_target(context)->arch,"x86_64") ? "-arch x86_64 -platform_version macos 15.0 15.0 -e _dyn_start" : "-arch arm64 -platform_version macos 15.0 15.0 -e _dyn_start")
#else
          (!strcmp(dyn_context_target(context)->arch,"x86_64") ? "cc --target=x86_64-macos.15.0-none -nostdlib -Wl,-e,_dyn_start" : "cc --target=aarch64-macos.15.0-none -nostdlib -Wl,-e,_dyn_start")
#endif
        : windows
            ? "-mi386pep --gc-sections --entry=dyn_start --subsystem console"
            : "--gc-sections",
        temporary, runtime, support);
    for (size_t i = 0; i < object_count; ++i)
      fprintf(stderr, " %s", object_paths[i]);
    if (dynamic && !darwin && !windows)
      fprintf(stderr, " --dynamic-linker %s",
              dyn_context_target(context)->dynamic_linker);
    for (size_t i = 0; i < link_input_count; ++i)
      fprintf(stderr, " %s", link_inputs[i]);
    fputc('\n', stderr);
  }
  char **arguments =
      calloc(object_count + link_input_count + 28, sizeof(*arguments));
  if (!arguments)
    return 2;
  size_t argument_count = 0;
  arguments[argument_count++] = (char *)linker;
  if (darwin) {
#ifdef __APPLE__
    arguments[argument_count++] = "-arch"; arguments[argument_count++] = !strcmp(dyn_context_target(context)->arch,"x86_64") ? "x86_64" : "arm64";
    arguments[argument_count++] = "-platform_version";
    arguments[argument_count++] = "macos";
    arguments[argument_count++] = "15.0"; arguments[argument_count++] = "15.0";
    arguments[argument_count++] = "-e"; arguments[argument_count++] = "_dyn_start";
#else
    arguments[argument_count++] = "cc";
    arguments[argument_count++] = !strcmp(dyn_context_target(context)->arch,"x86_64") ? "--target=x86_64-macos.15.0-none" : "--target=aarch64-macos.15.0-none";
    arguments[argument_count++] = "-nostdlib";
    arguments[argument_count++] = "-Wl,-e,_dyn_start";
#endif
  } else if (windows) {
    arguments[argument_count++] = "-mi386pep";
    arguments[argument_count++] = "--gc-sections";
    arguments[argument_count++] = "--entry=dyn_start";
    arguments[argument_count++] = "--subsystem";
    arguments[argument_count++] = "console";
  } else {
    arguments[argument_count++] = "--gc-sections";

  }
  arguments[argument_count++] = "-o";
  arguments[argument_count++] = temporary;
  arguments[argument_count++] = runtime;
  arguments[argument_count++] = support;
  for (size_t i = 0; i < object_count; ++i)
    arguments[argument_count++] = (char *)object_paths[i];
  if (dynamic && !darwin && !windows) {
    arguments[argument_count++] = "--dynamic-linker";
    arguments[argument_count++] =
        (char *)dyn_context_target(context)->dynamic_linker;
  }
  for (size_t i = 0; i < link_input_count; ++i)
    arguments[argument_count++] = (char *)link_inputs[i];
  char system_stub[4096];
  if (darwin && dyn_host_runtime_file("libSystem.tbd", system_stub, sizeof(system_stub)))
    arguments[argument_count++] = system_stub;
  int status;
  status = dyn_host_spawn(arguments);
  if (status == 127 && !strcmp(dyn_context_target(context)->name, "aarch64-linux")) {
    for (size_t i = argument_count; i > 0; --i)
      arguments[i + 1] = arguments[i];
    arguments[0] = "zig";
    arguments[1] = "ld.lld";
    status = dyn_host_spawn(arguments);
  }
  if (status == 127 && !strcmp(dyn_context_target(context)->name, "x86_64-linux")) {
    arguments[0] = "ld";
    status = dyn_host_spawn(arguments);
  }
  free(arguments);
  if (status != 0) {
    if (status == 127)
      fprintf(stderr, "error: target '%s' requires %s in PATH\n",
              dyn_context_target(context)->name, linker);
    else
      fprintf(stderr, "error: linker failed\n");
    return 2;
  }
  if (rename(temporary, output_path)) {
    perror("error: rename output");
    return 2;
  }
  return 0;
}
int dyn_link_executable(const DynContext *context, const char *object_path,
                        const char *output_path, const char *const *link_inputs,
                        size_t link_input_count, bool release, bool verbose) {
  if (!strcmp(dyn_context_target(context)->arch, "wasm32"))
    return link_wasm(context, object_path, output_path, link_inputs, link_input_count, verbose);

  return dyn_link_executable_objects(context, &object_path, 1, output_path,
                                     link_inputs, link_input_count, release,
                                     verbose);
}
/* Browser modules use a static Wasm link, not a native dynamic library. */
static int link_wasm(const DynContext *context, const char *object_path, const char *output_path,
                        const char *const *inputs, size_t count, bool verbose) {
  char executable[4096], support[4096], temporary[4096], imports[8192];
  char wasi_support[4096], wasi_start[4096];
  bool wasi = !strcmp(dyn_context_target(context)->kernel, "wasi");
  if (snprintf(imports, sizeof(imports), "--allow-undefined-file=%s.imports", object_path) >= (int)sizeof(imports)) return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0 || (size_t)n >= sizeof(executable) - 1) return 2;
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash) return 2;
  *slash = 0;
  if (snprintf(support, sizeof(support), "%s/dynrt_wasm.o", executable) >= (int)sizeof(support)) return 2;
  if (access(support, R_OK) && snprintf(support, sizeof(support), "%s/../lib/dyn/dynrt_wasm.o", executable) >= (int)sizeof(support)) return 2;
  if (wasi) {
    char *end = strrchr(support, '/');
    if (!end) return 2;
    size_t length = (size_t)(end - support);
    if (snprintf(wasi_support, sizeof(wasi_support), "%.*s/dynrt_wasi_support.o", (int)length, support) >= (int)sizeof(wasi_support) ||
        snprintf(wasi_start, sizeof(wasi_start), "%.*s/dynrt_wasi_start.o", (int)length, support) >= (int)sizeof(wasi_start)) return 2;
  }
  const char *selection = getenv("DYN_LINKER");
  if (!selection || strcmp(selection, "external")) {
    const char **objects = calloc(count + 4, sizeof(*objects));
    char **allowed = NULL;
    size_t object_count = 0, allowed_count = 0;
    uint32_t maximum = 0;
    int result = 2;
    if (!objects) return 2;
    objects[object_count++] = support;
    objects[object_count++] = object_path;
    if (wasi) { objects[object_count++] = wasi_support; objects[object_count++] = wasi_start; }
    for (size_t i = 0; i < count; ++i) {
      if (!strncmp(inputs[i], "--max-memory=", 13)) {
        char *end;
        unsigned long long value = strtoull(inputs[i] + 13, &end, 10);
        if (!inputs[i][13] || *end || !value || value > UINT32_MAX || value % 65536) {
          fprintf(stderr, "error: Wasm maximum memory must be a positive multiple of 65536 below 4 GiB\n");
          goto wasm_done;
        }
        maximum = (uint32_t)value;
      } else if (inputs[i][0] == '-') {
        fprintf(stderr, "error: unsupported built-in Wasm linker option: %s\n", inputs[i]);
        goto wasm_done;
      } else objects[object_count++] = inputs[i];
    }
    /* The emitter records explicitly declared imports. Undefined symbols must
       never silently become host imports. */
    char import_path[8192];
    if (snprintf(import_path, sizeof(import_path), "%s.imports", object_path) >= (int)sizeof(import_path)) goto wasm_done;
    FILE *file = fopen(import_path, "rb");
    if (!file) { fprintf(stderr, "error: cannot read Wasm import manifest: %s\n", import_path); goto wasm_done; }
    char line[4096];
    bool manifest_ok = true;
    while (fgets(line, sizeof(line), file)) {
      size_t length = strcspn(line, "\r\n");
      if (length == sizeof(line)-1) { manifest_ok = false; break; }
      line[length] = 0;
      if (!length) continue;
      char **grown = realloc(allowed, (allowed_count + 1) * sizeof(*allowed));
      if (!grown) { manifest_ok = false; break; }
      allowed = grown;
      allowed[allowed_count] = strdup(line);
      if (!allowed[allowed_count]) { manifest_ok = false; break; }
      ++allowed_count;
    }
    if (ferror(file)) manifest_ok = false;
    fclose(file);
    if (manifest_ok)
      result = dyn_link_wasm_objects(objects, object_count, output_path,
          (const char *const *)allowed, allowed_count, wasi, maximum, verbose);
wasm_done:
    for (size_t i = 0; i < allowed_count; ++i) free(allowed[i]);
    free(allowed);
    free(objects);
    return result;
  }
  /* Explicit external linker selection is an optional comparison tool. */
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >= (int)sizeof(temporary)) return 2;
  if (verbose) fprintf(stderr, "+ wasm-ld --no-entry --export-memory -o %s %s %s\n", temporary, support, object_path);
  char **args = calloc(count + 16, sizeof(*args));
  if (!args) return 2;
  size_t at = 0;
  args[at++] = "wasm-ld";
  args[at++] = "--no-entry";
  args[at++] = imports;
  args[at++] = "--export-memory";
  args[at++] = "-z"; args[at++] = "stack-size=1048576";
  args[at++] = "-o"; args[at++] = temporary;
  args[at++] = support; args[at++] = (char *)object_path;
  if (wasi) { args[at++] = wasi_support; args[at++] = wasi_start; }
  for (size_t i = 0; i < count; ++i) args[at++] = (char *)inputs[i];
  int status;
  status = dyn_host_spawn(args);
  free(args);
  if (status != 0) {
    fprintf(stderr, "error: Wasm link failed (wasm-ld required in PATH)\n");
    remove(temporary); return 2;
  }
  if (rename(temporary, output_path)) { remove(temporary); return 2; }
  return 0;
}
int dyn_link_shared(const DynContext *context, const char *object_path,
                    const char *output_path, const char *const *link_inputs,
                    size_t link_input_count, bool verbose) {
  if (!strcmp(dyn_context_target(context)->arch, "wasm32"))
    return link_wasm(context, object_path, output_path, link_inputs, link_input_count, verbose);
  char temporary[4096], support[4096], assembly[4096], executable[4096];
  char import_temporary[4096] = {0}, import_output[4096] = {0};
  if (snprintf(temporary, sizeof(temporary), "%s.tmp", output_path) >=
      (int)sizeof(temporary))
    return 2;
  ssize_t n = dyn_host_executable(executable, sizeof(executable) - 1);
  if (n < 0) {
    perror("error: locate compiler");
    return 2;
  }
  executable[n] = 0;
  char *slash = strrchr(executable, '/');
  if (!slash)
    return 2;
  *slash = 0;
  bool windows = !strcmp(dyn_context_target(context)->kernel, "windows");
  bool darwin = !strcmp(dyn_context_target(context)->kernel, "darwin");
  const char *link_output = windows ? output_path : temporary;
  if (windows && (snprintf(import_output, sizeof(import_output), "%s.a",
                           output_path) >= (int)sizeof(import_output) ||
                  snprintf(import_temporary, sizeof(import_temporary), "%s.tmp",
                           import_output) >= (int)sizeof(import_temporary)))
    return 2;
  const char *name = windows  ? (!strcmp(dyn_context_target(context)->arch, "aarch64") ? "dynrt_windows_arm64_support.o" : "dynrt_windows_support.o")
                     : darwin ? (!strcmp(dyn_context_target(context)->arch, "x86_64") ? "dynrt_macos_x64_support.o" : "dynrt_macos_support.o")
                     : !strcmp(dyn_context_target(context)->arch, "aarch64")
                         ? "dynrt_aarch64_support_pic.o"
                         : !strcmp(dyn_context_target(context)->arch, "riscv64") ? "dynrt_riscv64_support_pic.o" : "dynrt_support_pic.o";
  if (snprintf(support, sizeof(support), "%s/%s", executable, name) >=
      (int)sizeof(support))
    return 2;
  if (access(support, R_OK) &&
      snprintf(support, sizeof(support), "%s/../lib/dyn/%s", executable,
               name) >= (int)sizeof(support))
    return 2;
  const char *assembly_name =
      windows  ? (!strcmp(dyn_context_target(context)->arch, "aarch64") ? "dynrt_windows_arm64_shared.o" : "dynrt_windows_shared.o")
      : darwin ? (!strcmp(dyn_context_target(context)->arch, "x86_64") ? "dynrt_macos_x64_shared.o" : "dynrt_macos_shared.o")
      : !strcmp(dyn_context_target(context)->arch, "aarch64")
          ? "dynrt_aarch64_shared.o"
          : !strcmp(dyn_context_target(context)->arch, "riscv64") ? "dynrt_riscv64_shared.o" : "dynrt_shared.o";
  if (snprintf(assembly, sizeof(assembly), "%s/%s", executable,
               assembly_name) >= (int)sizeof(assembly))
    return 2;
  if (access(assembly, R_OK) &&
      snprintf(assembly, sizeof(assembly), "%s/../lib/dyn/%s", executable,
               assembly_name) >= (int)sizeof(assembly))
    return 2;
  const char *external = getenv("DYN_LINKER");
  if (windows && !(external && !strcmp(external, "external"))) {
    bool supported = true;
    for (size_t i = 0; supported && i < link_input_count; ++i)
      supported = dyn_link_coff_supported(link_inputs[i]);
    const char *object = object_path;
    if (supported) {
      int status = link_coff(assembly, support, &object, 1, link_inputs, link_input_count, temporary, output_path,
                             import_temporary, verbose);
      if (!status && rename(import_temporary, import_output)) {
        perror("error: rename import library");
        return 2;
      }
      return status;
    }
  }
  if (darwin && !(external && !strcmp(external, "external"))) {
    bool supported = true;
    for (size_t i = 0; supported && i < link_input_count; ++i)
      supported = dyn_link_macho_supported(link_inputs[i]);
    const char *object = object_path;
    if (supported)
      return link_macho(assembly, support, &object, 1, link_inputs, link_input_count, temporary, output_path,
                        true, verbose);
  }
  if (!strcmp(dyn_context_target(context)->kernel, "linux") &&
      !(external && !strcmp(external, "external"))) {
    bool builtin = true;
    for (size_t i = 0; builtin && i < link_input_count; ++i)
      builtin = dyn_link_elf_supported(link_inputs[i]);
    const char **inputs = builtin ? calloc(link_input_count + 3, sizeof(*inputs)) : NULL;
    if (builtin && !inputs)
      return 2;
    if (builtin) {
      size_t input_count = 0;
      inputs[input_count++] = assembly;
      inputs[input_count++] = support;
      inputs[input_count++] = object_path;
      for (size_t i = 0; i < link_input_count; ++i)
        inputs[input_count++] = link_inputs[i];
      if (verbose) {
        fprintf(stderr, "+ (built-in) link -shared -o %s", temporary);
        for (size_t i = 0; i < input_count; ++i)
          fprintf(stderr, " %s", inputs[i]);
        fputc('\n', stderr);
      }
      DynLinkOptions options = {.shared = true};
      int status = dyn_link_elf(inputs, input_count, temporary, &options);
      free(inputs);
      if (status)
        return 2;
      if (rename(temporary, output_path)) {
        perror("error: rename output");
        remove(temporary);
        return 2;
      }
      return 0;
    }
  }
  if (!(external && !strcmp(external, "external"))) {
    fprintf(stderr, "error: unsupported built-in linker input; external linking requires DYN_LINKER=external\n");
    return 2;
  }
  if (windows && !strcmp(dyn_context_target(context)->arch,"aarch64")) {
    fprintf(stderr,"error: external linking for aarch64-windows is unsupported; use DYN_LINKER=builtin\n");
    return 2;
  }
  if (verbose) {
    fprintf(stderr, "+ %s -o %s %s %s %s",
            darwin ?
#ifdef __APPLE__
                (!strcmp(dyn_context_target(context)->arch,"x86_64") ? "ld64.lld -arch x86_64 -platform_version macos 15.0 15.0 -dylib" : "ld64.lld -arch arm64 -platform_version macos 15.0 15.0 -dylib")
#else
                (!strcmp(dyn_context_target(context)->arch,"x86_64") ? "zig cc --target=x86_64-macos.15.0-none -dynamiclib -nostdlib" : "zig cc --target=aarch64-macos.15.0-none -dynamiclib -nostdlib")
#endif
            : windows ? DYN_WINDOWS_LINKER " -mi386pep -shared"
                      : "ld.lld -shared",
            temporary, assembly, support, object_path);
    for (size_t i = 0; i < link_input_count; ++i)
      fprintf(stderr, " %s", link_inputs[i]);
    fputc('\n', stderr);
  }
  char **arguments = calloc(link_input_count + 18, sizeof(*arguments));
  if (!arguments)
    return 2;
  size_t count = 0;
  arguments[count++] = darwin ? DYN_DARWIN_LINKER : windows ? DYN_WINDOWS_LINKER : "ld.lld";
  if (darwin) {
#ifdef __APPLE__
    arguments[count++] = "-arch"; arguments[count++] = !strcmp(dyn_context_target(context)->arch,"x86_64") ? "x86_64" : "arm64";
    arguments[count++] = "-platform_version"; arguments[count++] = "macos";
    arguments[count++] = "15.0"; arguments[count++] = "15.0";
    arguments[count++] = "-dylib";
#else
    arguments[count++] = "cc";
    arguments[count++] = !strcmp(dyn_context_target(context)->arch,"x86_64") ? "--target=x86_64-macos.15.0-none" : "--target=aarch64-macos.15.0-none";
    arguments[count++] = "-dynamiclib";
    arguments[count++] = "-nostdlib";
#endif
  } else {
    if (windows)
      arguments[count++] = "-mi386pep";
    arguments[count++] = "-shared";
    arguments[count++] = "--gc-sections";
    if (windows) {
      arguments[count++] = "--export-all-symbols";
      arguments[count++] = "--out-implib";
      arguments[count++] = import_temporary;
    }
  }
  arguments[count++] = "-o";
  arguments[count++] = (char *)link_output;
  arguments[count++] = assembly;
  arguments[count++] = support;
  arguments[count++] = (char *)object_path;
  for (size_t i = 0; i < link_input_count; ++i)
    arguments[count++] = (char *)link_inputs[i];
  char system_stub[4096];
  if (darwin && dyn_host_runtime_file("libSystem.tbd", system_stub, sizeof(system_stub)))
    arguments[count++] = system_stub;
  int status;
  status = dyn_host_spawn(arguments);
  if (status == 127 && !windows && !darwin &&
      !strcmp(dyn_context_target(context)->name, "aarch64-linux")) {
    for (size_t i = count; i > 0; --i)
      arguments[i + 1] = arguments[i];
    arguments[0] = "zig";
    arguments[1] = "ld.lld";
    status = dyn_host_spawn(arguments);
  }
  if (status == 127 && !windows && !darwin &&
      !strcmp(dyn_context_target(context)->name, "x86_64-linux")) {
    arguments[0] = "ld";
    status = dyn_host_spawn(arguments);
  }
  free(arguments);
  if (status != 0) {
    if (status == 127)
      fprintf(stderr, "error: target '%s' requires %s in PATH\n",
              dyn_context_target(context)->name,
              darwin    ? DYN_DARWIN_LINKER
              : windows ? DYN_WINDOWS_LINKER
                        : "ld.lld");
    else
      fprintf(stderr, "error: linker failed\n");
    remove(link_output);
    return 2;
  }
  if (!windows && rename(temporary, output_path)) {
    perror("error: rename output");
    remove(temporary);
    return 2;
  }
  if (windows && rename(import_temporary, import_output)) {
    perror("error: rename import library");
    return 2;
  }
  return 0;
}

