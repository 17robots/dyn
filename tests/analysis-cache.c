#define _POSIX_C_SOURCE 200809L
#include "analysis_cache.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "fault-alloc.h"

static void write_file(const char *path, const char *text) {
  FILE *file = fopen(path, "wb"); assert(file);
  assert(fputs(text, file) >= 0); assert(!fclose(file));
}
static DynSource source_copy(void) {
  return (DynSource){.path = strdup("main.dyn"), .text = strdup("fn main() {}"), .length = 12};
}
static void module_snapshots(void) {
  DynAnalysisResult checked = {.parsed = true, .checked = true};
  for (size_t failure = 0; failure <= 2; ++failure) {
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    fail_at = failure; calls = failed = 0;
    DynAnalysisSnapshot *snapshot = dyn_analysis_module_put(&cache, &source, &ast, checked);
    fail_at = 0;
    if (failure) { assert(!snapshot && source.text && failed); dyn_source_free(&source); }
    else {
      assert(snapshot && !source.text);
      DynSource equal = source_copy();
      DynAnalysisSnapshot *hit = dyn_analysis_module_get(&cache, &equal);
      assert(hit == snapshot); dyn_analysis_snapshot_release(hit);
      equal.text[3] = 'x'; assert(!dyn_analysis_module_get(&cache, &equal));
      dyn_source_free(&equal);
      for (unsigned i = 0; i < 70; ++i) {
        source = source_copy(); free(source.path);
        char path[32]; snprintf(path, sizeof(path), "module-%u.dyn", i); source.path = strdup(path);
        hit = dyn_analysis_module_put(&cache, &source, &ast, checked);
        assert(hit); dyn_analysis_snapshot_release(hit);
      }
      assert(cache.module_count == 64);
      dyn_analysis_cache_clear(&cache);
      assert(!strcmp(snapshot->source.text, "fn main() {}"));
      dyn_analysis_snapshot_release(snapshot);
    }
    dyn_analysis_cache_clear(&cache);
  }
}
static void interface_payloads(void) {
  DynSource source = {.path = "main.dyn", .text = "pub fn f() {}", .length = 13};
  DynSources sources = {&source, 1};
  DynInterface value = {.data = "payload", .length = 7, .source_hash = 123, .interface_hash = 456};
  for (size_t failure = 0; failure <= 3; ++failure) {
    DynAnalysisCache cache = {0}; DynInterface out = {0};
    calls = failed = 0; fail_at = failure;
    dyn_analysis_interface_put(&cache, &sources, &value);
    fail_at = 0;
    if (failure) assert(failed && !cache.interface_count);
    else {
      for (size_t get_failure = 1; get_failure <= 2; ++get_failure) {
        calls = failed = 0; fail_at = get_failure;
        assert(!dyn_analysis_interface_get(&cache, &sources, &out) && failed);
        fail_at = 0;
      }
      assert(dyn_analysis_interface_get(&cache, &sources, &out));
      assert(!strcmp(out.data, value.data) && out.source_hash == 123 && out.interface_hash == 456);
      free(out.data);
      source.text = "pub fn g() {}";
      assert(!dyn_analysis_interface_get(&cache, &sources, &out));
      source.text = "pub fn f() {}";
      source.path = "other.dyn";
      assert(!dyn_analysis_interface_get(&cache, &sources, &out));
      source.path = "main.dyn";
      source.context.target = dyn_target_find("aarch64-linux");
      assert(!dyn_analysis_interface_get(&cache, &sources, &out));
      source.context.target = NULL;
      for (unsigned i = 0; i < 70; ++i) {
        char path[64]; snprintf(path, sizeof(path), "module%u.dyn", i);
        source.path = path; dyn_analysis_interface_put(&cache, &sources, &value);
      }
      source.path = "main.dyn";
      assert(cache.interface_count == 64);
    }
    dyn_analysis_cache_clear(&cache);
    assert(!cache.interface_count && !cache.interface_bytes);
  }
}
int main(void) {
  module_snapshots();
  interface_payloads();
  char root[] = "/tmp/dyn-analysis-cache-XXXXXX"; assert(mkdtemp(root));
  char library[256], path[256], imported[256], added[256], manifest[256];
  snprintf(library, sizeof(library), "%s/lib", root); assert(!mkdir(library, 0700));
  snprintf(path, sizeof(path), "%s/main.dyn", root);
  snprintf(imported, sizeof(imported), "%s/lib/module.dyn", root);
  snprintf(added, sizeof(added), "%s/lib/new.dyn", root);
  snprintf(manifest, sizeof(manifest), "%s/dyn.project", root);
  write_file(path, "fn main() {}"); write_file(imported, "pub const Answer: i32 = 1");
  DynSource dependencies_items[] = {{.path = path}, {.path = imported}};
  DynSources dependencies = {dependencies_items, 2};
  DynAnalysisInput input = {path, "fn main() {}", 12, 1, 0};
  DynAnalysisResult result = {.parsed = true, .checked = true};
  DynAnalysisDiagnostic diagnostic_item = {0};
  DynAnalysisDiagnostics collected = {.items = &diagnostic_item, .count = 1, .capacity = 1};
  size_t total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    fail_at = 0;
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    calls = failed = 0; fail_at = iteration;
    DynAnalysisSnapshot *snapshot = dyn_analysis_cache_put(&cache, root, &dependencies, &input, 1, &source, &ast, result, &collected);
    if (!iteration) { assert(snapshot); total = calls; }
    else { assert(failed && !snapshot); assert(source.text && source.path); assert(!cache.count); }
    fail_at = 0;
    dyn_analysis_snapshot_release(snapshot); dyn_analysis_cache_clear(&cache);
    dyn_source_free(&source); dyn_ast_program_free(&ast);
  }
  /* Hits reuse both diagnostics and prehashed buffers without allocating. */
  {
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    DynAnalysisDiagnostic item = {0};
    DynAnalysisDiagnostics diagnostics = {.items = &item, .count = 1, .capacity = 1};
    strcpy(diagnostics.items[0].message, "unknown name");
    DynAnalysisInput hashed = input;
    hashed.content_hash = dyn_analysis_text_hash(hashed.text, hashed.length);
    DynAnalysisSnapshot *held = dyn_analysis_cache_put(&cache, root, &dependencies, &hashed, 1, &source, &ast, result, &diagnostics);
    assert(held); memset(&diagnostics, 0, sizeof(diagnostics)); memset(&item, 0, sizeof(item));
    calls = 0;
    DynAnalysisSnapshot *hit = dyn_analysis_cache_get(&cache, root, &hashed, 1);
    assert(hit == held && calls == 0);
    assert(hit->diagnostics.count == 1 && !strcmp(hit->diagnostics.items[0].message, "unknown name"));
    dyn_analysis_snapshot_release(hit);
    ++hashed.version;
    hit = dyn_analysis_cache_get(&cache, root, &hashed, 1);
    assert(hit == held); dyn_analysis_snapshot_release(hit);
    hashed.text = "fn main() { "; hashed.content_hash = dyn_analysis_text_hash(hashed.text, hashed.length);
    assert(!dyn_analysis_cache_get(&cache, root, &hashed, 1));
    dyn_analysis_snapshot_release(held); dyn_analysis_cache_clear(&cache);
  }
  /* Unrelated buffers and non-source files do not invalidate this graph. */
  {
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    DynAnalysisSnapshot *held = dyn_analysis_cache_put(&cache, root, &dependencies, &input, 1, &source, &ast, result, NULL);
    assert(held);
    DynAnalysisInput others[] = {input, {"/unrelated/main.dyn", "fn other() {}", 13, 91, 0}};
    char output[256]; snprintf(output, sizeof(output), "%s/program", root);
    write_file(output, "not source");
    DynAnalysisSnapshot *hit = dyn_analysis_cache_get(&cache, root, others, 2);
    assert(hit == held); dyn_analysis_snapshot_release(hit); unlink(output);
    dyn_analysis_cache_clear(&cache); dyn_analysis_snapshot_release(held);
  }
  /* Failed lookup must release cache ownership while preserving retained views. */
  total = 0;
  for (size_t iteration = 0; !iteration || iteration <= total; ++iteration) {
    fail_at = 0;
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    DynAnalysisSnapshot *held = dyn_analysis_cache_put(&cache, root, &dependencies, &input, 1, &source, &ast, result, NULL);
    assert(held);
    char output[256]; snprintf(output, sizeof(output), "%s/output", root);
    write_file(output, "membership change forces a scan");
    calls = failed = 0; fail_at = iteration;
    DynAnalysisSnapshot *hit = dyn_analysis_cache_get(&cache, root, &input, 1);
    if (!iteration) { assert(hit == held); total = calls; }
    else assert(failed && !hit);
    unlink(output);
    fail_at = 0;
    assert(!strcmp(held->source.text, "fn main() {}"));
    dyn_analysis_snapshot_release(hit); dyn_analysis_cache_clear(&cache); dyn_analysis_snapshot_release(held);
  }
  for (unsigned change = 1; change < 6; ++change) {
    DynAnalysisCache cache = {0}; DynSource source = source_copy(); DynAstProgram ast = {0};
    DynAnalysisSnapshot *held = dyn_analysis_cache_put(&cache, root, &dependencies, &input, 1, &source, &ast, result, NULL);
    assert(held && !source.text);
    DynAnalysisSnapshot *hit = dyn_analysis_cache_get(&cache, root, &input, 1);
    assert(hit == held); dyn_analysis_snapshot_release(hit);
    if (change == 1) input.text = "fn main() { ";
    if (change == 2) write_file(imported, "pub const Answer: i32 = 2");
    if (change == 3) write_file(added, "pub const New: bool = true");
    if (change == 4) assert(!unlink(added));
    if (change == 5) write_file(manifest, "dependency fixture = ./lib\n");
    assert(!dyn_analysis_cache_get(&cache, root, &input, 1));
    assert(!strcmp(held->source.text, "fn main() {}")); /* Retained across invalidation. */
    dyn_analysis_cache_clear(&cache); dyn_analysis_snapshot_release(held);
  }
  /* Repeated capacity eviction preserves independently retained snapshots. */
  {
    char roots[8][256];
    DynAnalysisSnapshot *held[8] = {0};
    DynAnalysisCache cache = {0};
    for (unsigned i = 0; i < 8; ++i) {
      snprintf(roots[i], sizeof(roots[i]), "%s/cache%u", root, i);
      assert(!mkdir(roots[i], 0700));
      DynSource source = source_copy(); DynAstProgram ast = {0};
      held[i] = dyn_analysis_cache_put(&cache, roots[i], &dependencies, &input, 1,
                                      &source, &ast, result, &collected);
      assert(held[i] && cache.count == (i < 4 ? i + 1 : 4));
      for (unsigned previous = 0; previous <= i; ++previous)
        assert(!strcmp(held[previous]->source.text, "fn main() {}"));
    }
    assert(!dyn_analysis_cache_get(&cache, roots[0], &input, 1));
    dyn_analysis_cache_clear(&cache);
    assert(!cache.count && !cache.entries);
    for (unsigned i = 0; i < 8; ++i) {
      assert(!strcmp(held[i]->source.text, "fn main() {}"));
      dyn_analysis_snapshot_release(held[i]);
      assert(!rmdir(roots[i]));
    }
  }
  unlink(path); unlink(imported); unlink(manifest); rmdir(library); rmdir(root);
  return 0;
}
