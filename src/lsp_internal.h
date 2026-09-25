#ifndef DYN_LSP_INTERNAL_H
#define DYN_LSP_INTERNAL_H
/* Internal editor interfaces. Documents own text/trees; semantic views are
   released through lsp_semantic_free, including cached and partial results. */
#include "analysis_cache.h"
#include "dyn.h"
#include "dyn_ast.h"
#include "dyn_syntax.h"
#include "frontend.h"
#include "lsp_json.h"
#include "sema.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <tree_sitter/api.h>
#include <unistd.h>

typedef struct {
  char *uri;
  char *text;
  DynAnalysisCache *analysis_cache;
  uint64_t revision, content_hash;
  TSParser *parser;
  TSTree *tree;
  size_t parsed_length;
  TSPoint parsed_end;
  bool dirty, syntax_too_deep;
} LspDocument;
typedef struct {
  DynSource source;
  DynAstProgram ast;
  bool ok, checked;
  DynAnalysisSnapshot *snapshot;
  DynAnalysisDiagnostics diagnostics;
} LspSemantic;
typedef DynAnalysisDiagnostic LspDiagnostic;
typedef DynAnalysisDiagnostics LspDiagnostics;
typedef struct {
  char path[512], alias[512];
  TSNode node, alias_node;
} LspImport;
typedef bool (*LspPublicVisitor)(const char *, size_t, DynDeclarationKind,
                                 void *);

typedef struct {
  char uri[1024];
  size_t line, column, length;
} LspOrigin;

const DynTarget *lsp_target_current(void);
DynWork *lsp_work_current(void);
static inline bool lsp_work_step(uint64_t units) {
  DynContext context = {.target = lsp_target_current(), .work = lsp_work_current()};
  return dyn_work_step(&context, units);
}
TSTree *lsp_parse(const char *, size_t);

/* actions */
void lsp_code_actions(long id, LspDocument *documents, size_t count,
                      LspDocument *document, const char *body_text);
void lsp_format(long id, const LspDocument *document);

/* analysis */
void lsp_publish_semantic(LspDocument *documents, size_t count);
void lsp_ignore_diagnostic(const char *a, const char *b, unsigned c, unsigned d,
                           unsigned e, unsigned f, const char *g, void *h);
LspSemantic lsp_semantic_build(LspDocument *documents, size_t count);
LspSemantic lsp_semantic_build_related(LspDocument *documents, size_t count,
                                       LspDocument *requested);
LspSemantic lsp_semantic_project(LspDocument *documents, size_t count,
                                 LspDocument *requested,
                                 const char *replacement);
void lsp_semantic_free(LspSemantic *semantic);
bool lsp_semantic_offset(LspSemantic *semantic, LspDocument *document,
                         size_t line, size_t character, uint32_t *offset);

/* completion */
void lsp_completion_signature(const char *start, char *out, size_t capacity);
void lsp_completion(long id, LspDocument *documents, size_t count,
                    LspDocument *requested, size_t line, size_t character);
TSNode lsp_type_node(TSNode node);

/* document */
LspDocument *lsp_document(LspDocument *documents, size_t count,
                          const char *uri);
void lsp_uri_paths_clear(void);
void lsp_declarations_clear(void);
void lsp_declaration_documents(LspDocument *documents, size_t count);
const char *lsp_file_path(const char *uri);
char *lsp_directory(const char *path);
char *lsp_project_root(const char *uri);
size_t lsp_imports(const LspDocument *document, LspImport *imports,
                   size_t capacity);
char *lsp_resolve_import(const LspDocument *document, const char *path);
char *lsp_first_dyn_file(const char *directory);
char *lsp_path_uri(const char *path);
bool lsp_directory_has_dyn(const char *directory);
bool lsp_directory_contains_dyn(const char *directory, unsigned depth);
bool lsp_has_import(const LspDocument *document, const char *path);
char *lsp_read_source(const char *path);
bool lsp_public_declarations(const char *path, LspPublicVisitor visit,
                             void *context);
char *lsp_apply_changes(LspDocument *document, char *body);
bool identifier_at(const char *text, size_t line, size_t character,
                   const char **start, size_t *length);
bool find_declaration(const char *text, const char *word, size_t word_length,
                      size_t *line, size_t *column, const char **display,
                      size_t *display_length);
TSPoint lsp_text_end(const char *text);
bool lsp_publish_syntax(LspDocument *document);

/* navigation */
const char *lsp_builtin_hover(const char *text, size_t line, size_t character);
size_t lsp_active_parameter(const char *text, size_t line, size_t character);
bool lsp_call_identifier(const char *text, size_t line, size_t character,
                         const char **start, size_t *length);
void lsp_references(long id, LspDocument *documents, size_t count,
                    const char *word, size_t word_length,
                    const char *replacement, const char *project_root);
void lsp_rename(long id, LspDocument *documents, size_t count, const char *word,
                size_t word_length, const char *replacement,
                const char *project_root);
void lsp_document_symbols(long id, const LspDocument *document);
void lsp_folding_ranges(long id, const LspDocument *document);
void lsp_selection_range(long id, const LspDocument *document,
                         const char *request);
void lsp_semantic_tokens(long id, LspDocument *documents, size_t count,
                         LspDocument *document);
void lsp_workspace_symbols(long id, LspDocument *documents, size_t count,
                           const char *workspace_root, const char *query);
void lsp_inlay_hints(long id, LspDocument *documents, size_t count,
                     LspDocument *requested, size_t range_start,
                     size_t range_end);
bool lsp_valid_identifier(const char *name);
bool lsp_origin_identifier(const DynSource *source, DynSpan span,
                           LspOrigin *origin);
void lsp_document_highlight(long id, LspDocument *documents, size_t count,
                            LspDocument *document, size_t line,
                            size_t character);
void lsp_semantic_references(long id, LspSemantic *semantic,
                             LspDocument *documents, size_t count,
                             DynSpan target);
void lsp_semantic_rename(long id, LspSemantic *semantic, LspDocument *documents,
                         size_t count, DynSpan target, const char *replacement);
void lsp_prepare_call_hierarchy(long id, LspDocument *documents, size_t count,
                                LspDocument *requested, size_t line,
                                size_t character);
void lsp_call_hierarchy(long id, LspDocument *documents, size_t count,
                        const char *request, bool incoming);
bool lsp_typed_symbol(LspSemantic *semantic, uint32_t offset, char *hover,
                      size_t capacity, DynSpan *definition);
bool lsp_type_definition_span(LspSemantic *semantic, uint32_t offset,
                              DynSpan *definition);
bool lsp_import_definition(LspDocument *document, size_t line, size_t character,
                           char **uri, size_t *out_line, size_t *out_column,
                           size_t *out_length);
void lsp_import_hover_text(const char *path, size_t line, char *out,
                           size_t capacity);

/* server */
char *json_string_after(const char *body, const char *key, size_t maximum);
bool json_point(const char *point, size_t *line, size_t *character);
bool json_range_positions(const char *body, size_t *sl, size_t *sc, size_t *el,
                          size_t *ec);
char *json_escape(const char *text, size_t length);

void lsp_send(const char *body);
int lsp_bounded_printf(char *, size_t, const char *, ...);
size_t lsp_wire_column(const char *, size_t, size_t, bool);
bool lsp_import_path_representable(const char *path);
#endif
