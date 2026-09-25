#ifndef DYN_LSP_WORK_H
#define DYN_LSP_WORK_H
/* Read-ahead keeps request order while allowing cancellation during analysis.
   It never mutates documents from inside a compiler traversal. */
typedef struct LspQueued {
  char *body;
  bool may_cancel;
  struct LspQueued *next;
} LspQueued;
typedef struct {
  LspInput *input;
  LspQueued *head, *tail;
  size_t count, bytes;
  const char *id;
  DynWork work;
} LspWork;
static DynWork *lsp_active_work;
DynWork *lsp_work_current(void) { return lsp_active_work; }
static bool lsp_cancel_matches(const char *body, const char *id) {
  if (!id || !lsp_json_valid(body)) return false;
  char *method = json_string_after(body, "\"method\"", 256);
  bool cancel = method && !strcmp(method, "$/cancelRequest");
  free(method);
  if (!cancel) return false;
  const char *params = lsp_json_member(body, "\"params\"");
  const char *value = params ? lsp_json_member(params, "\"id\"") : NULL;
  const char *end = value ? lsp_json_end(value, 0) : NULL;
  if (!end) return false;
  if ((size_t)(end - value) == strlen(id) && !memcmp(value, id, strlen(id))) return true;
  if (*id == '"' && *value == '"') {
    size_t size = strlen(id) + 16;
    char *wrapper = malloc(size);
    if (!wrapper) return false;
    snprintf(wrapper, size, "{\"id\":%s}", id);
    char *left = json_string_after(wrapper, "\"id\"", 64u * 1024u);
    char *right = json_string_after(params, "\"id\"", 64u * 1024u);
    bool same = left && right && !strcmp(left, right);
    free(wrapper); free(left); free(right); return same;
  }
  return false;
}
static bool lsp_is_cancel(const char *body) {
  char *method = json_string_after(body, "\"method\"", 256);
  bool result = method && !strcmp(method, "$/cancelRequest");
  free(method); return result;
}
static bool lsp_work_poll(void *data) {
  LspWork *state = data;
  LspQueued **at = &state->head, *previous = NULL;
  while (*at) {
    LspQueued *item = *at;
    if (item->may_cancel && lsp_cancel_matches(item->body, state->id)) {
      *at = item->next;
      if (state->tail == item) state->tail = previous;
      --state->count; state->bytes -= strlen(item->body);
      free(item->body); free(item); return true;
    }
    previous = item; at = &item->next;
  }
  /* One newly read frame can take storage above 16 MiB, but never above 32 MiB. */
  while (state->count < 64 && state->bytes < 16u * 1024u * 1024u) {
    char *body = lsp_input_next(state->input, false);
    if (!body) break;
    bool cancel = lsp_is_cancel(body);
    if (cancel && lsp_cancel_matches(body, state->id)) { free(body); return true; }
    LspQueued *item = calloc(1, sizeof(*item));
    if (!item) { free(body); state->input->failed = true; return true; }
    item->body = body; item->may_cancel = cancel;
    if (state->tail) state->tail->next = item; else state->head = item;
    state->tail = item; ++state->count; state->bytes += strlen(body);
  }
  return false;
}
static char *lsp_work_next(LspWork *state, bool wait) {
  if (!state->head) return lsp_input_next(state->input, wait);
  LspQueued *item = state->head;
  state->head = item->next;
  if (!state->head) state->tail = NULL;
  --state->count; state->bytes -= strlen(item->body);
  char *body = item->body; free(item); return body;
}
static uint64_t lsp_work_setting(const char *name, uint64_t fallback, uint64_t maximum) {
  const char *text = getenv(name);
  if (!text || !*text || *text < '0' || *text > '9') return fallback;
  char *end;
  errno = 0;
  unsigned long long n = strtoull(text, &end, 10);
  return errno || *end || !n || n > maximum ? fallback : n;
}
static void lsp_work_begin(LspWork *state) {
  uint64_t units = lsp_work_setting("DYN_LSP_MAX_WORK", 100000000, UINT64_MAX);
  uint64_t milliseconds = lsp_work_setting("DYN_LSP_CPU_MS", 2000, 60000);
  state->id = NULL;
  state->work = (DynWork){.remaining = units, .deadline = clock() + (clock_t)(milliseconds * CLOCKS_PER_SEC / 1000),
      .cancelled = lsp_work_poll, .data = state};
  lsp_active_work = &state->work;
}
#endif
