#ifndef DYN_ANALYSIS_CACHE_H
#define DYN_ANALYSIS_CACHE_H
#include "frontend.h"

typedef struct {
  const char *path, *text;
  size_t length;
  uint64_t version,
      content_hash; /* Hash cached by the buffer owner per revision. */
} DynAnalysisInput;
typedef struct {
  char severity[8], path[256], message[256];
  unsigned line, column, end_line, end_column;
} DynAnalysisDiagnostic;
typedef struct {
  DynAnalysisDiagnostic *items;
  size_t count, capacity;
  bool allocation_failed;
} DynAnalysisDiagnostics;
uint64_t dyn_analysis_text_hash(const char *, size_t);
typedef struct {
  DynSource source;
  DynAstProgram ast;
  DynAnalysisResult result;
  size_t references;
  DynAnalysisDiagnostics diagnostics;
} DynAnalysisSnapshot;
typedef struct DynAnalysisCacheEntry DynAnalysisCacheEntry;
typedef struct DynModuleSnapshotEntry DynModuleSnapshotEntry;
typedef struct DynInterfaceCacheEntry DynInterfaceCacheEntry;
typedef struct {
  DynAnalysisCacheEntry *entries;
  DynModuleSnapshotEntry *modules;
  DynSyntaxCache syntax;
  DynInterfaceCacheEntry *interfaces;
  size_t interface_count, interface_bytes;
  uint64_t interface_hits, interface_misses;
  size_t count;
  uint64_t clock, hits, misses;
  size_t module_count, module_bytes;
  uint64_t module_hits, module_misses;
} DynAnalysisCache;
/* Canonical interface payloads keyed by exact rewritten source bytes, ordered
   paths, and target. Returned payloads are owned by the caller. */
bool dyn_analysis_interface_get(DynAnalysisCache *, const DynSources *, DynInterface *);
void dyn_analysis_interface_put(DynAnalysisCache *, const DynSources *, const DynInterface *);
/* Exact composed module text and source maps. Disk validation and overlays are
   applied before composing the input, independent of watcher notifications. */
DynAnalysisSnapshot *dyn_analysis_module_get(DynAnalysisCache *, const DynSource *);
DynAnalysisSnapshot *dyn_analysis_module_put(DynAnalysisCache *, DynSource *,
                                             DynAstProgram *, DynAnalysisResult);
/* Retained immutable snapshots survive eviction and cache destruction. */
DynAnalysisSnapshot *dyn_analysis_cache_get(DynAnalysisCache *,
                                            const char *root,
                                            const DynAnalysisInput *, size_t);
/* On success, moves source/ast into the cache and returns a retained snapshot.
   On allocation failure inputs remain owned by the caller. */
DynAnalysisSnapshot *
dyn_analysis_cache_put(DynAnalysisCache *, const char *root,
                       const DynSources *dependencies, const DynAnalysisInput *,
                       size_t, DynSource *, DynAstProgram *, DynAnalysisResult,
                       const DynAnalysisDiagnostics *);
void dyn_analysis_snapshot_release(DynAnalysisSnapshot *);
void dyn_analysis_cache_clear(DynAnalysisCache *);
#endif
