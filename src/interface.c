#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
#include <unistd.h>

extern const TSLanguage *tree_sitter_dyn(void);

#define DYNMI_VERSION 1u
#define DYNMI_SCHEMA 2u
#define DYNMI_MAX_SIZE (64u * 1024u * 1024u)
static const unsigned char magic[8] = {'D','Y','N','M','I','\r','\n',0x1a};

static uint64_t interface_hash_bytes(uint64_t h, const void *p, size_t n) {
  const unsigned char *s = p;
  while (n--) { h ^= *s++; h *= UINT64_C(1099511628211); }
  return h;
}
static uint64_t hash_start(void) { return UINT64_C(1469598103934665603); }
static int interface_source_compare(const void *a, const void *b) {
  const DynSource *const *x = a, *const *y = b;
  return strcmp((*x)->path, (*y)->path);
}
uint64_t dyn_interface_source_hash(const DynSources *sources) {
  uint64_t h = hash_start();
  DynSource **order = malloc(sources->count * sizeof(*order));
  if (!order && sources->count) return 0;
  for (size_t i = 0; i < sources->count; ++i) order[i] = &sources->items[i];
  if (sources->count)
    qsort(order, sources->count, sizeof(*order), interface_source_compare);
  for (size_t i = 0; i < sources->count; ++i) {
    uint64_t n = strlen(order[i]->path), z = order[i]->length;
    h = interface_hash_bytes(h, &n, sizeof(n)); h = interface_hash_bytes(h, order[i]->path, n);
    h = interface_hash_bytes(h, &z, sizeof(z)); h = interface_hash_bytes(h, order[i]->text, z);
  }
  free(order); return h;
}

static bool word(unsigned char c) { return isalnum(c) || c == '_'; }
static char *canonical(const char *p, size_t n, size_t *out_n) {
  char *out = malloc(n + 2); size_t j = 0; bool space = false;
  if (!out) return NULL;
  for (size_t i = 0; i < n;) {
    if (p[i] == '/' && i + 1 < n && p[i + 1] == '/') {
      i += 2; while (i < n && p[i] != '\n') ++i; space = true; continue;
    }
    if (isspace((unsigned char)p[i])) { space = true; ++i; continue; }
    if (p[i] == '"' || p[i] == '\'') {
      if (space && j && word((unsigned char)out[j - 1])) out[j++] = ' ';
      space = false; char quote = p[i]; out[j++] = p[i++];
      while (i < n) {
        out[j++] = p[i];
        if (p[i] == '\\' && i + 1 < n) out[j++] = p[++i];
        else if (p[i] == quote) { ++i; break; }
        ++i;
      }
      continue;
    }
    if (space && j && word((unsigned char)out[j - 1]) &&
        word((unsigned char)p[i])) out[j++] = ' ';
    space = false; out[j++] = p[i++];
  }
  out[j] = 0; *out_n = j; return out;
}
static int string_compare(const void *a, const void *b) {
  return strcmp(*(char *const *)a, *(char *const *)b);
}
static bool public_wrapper(TSNode n, const DynSource *s) {
  uint32_t a = ts_node_start_byte(n);
  return a + 3 <= s->length && !memcmp(s->text + a, "pub", 3) &&
         (a + 3 == s->length || isspace((unsigned char)s->text[a + 3]));
}
int dyn_interface_build(const DynSources *sources, DynInterface *result) {
  memset(result, 0, sizeof(*result));
  TSParser *parser = ts_parser_new(); char **decls = NULL; size_t count = 0;
  if (!parser || !ts_parser_set_language(parser, tree_sitter_dyn())) goto fail;
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *s = &sources->items[si];
    if (dyn_source_target_enabled(s) == 0) continue;
    TSTree *tree = ts_parser_parse_string(parser, NULL, s->text,
                                          (uint32_t)s->length);
    if (!tree || ts_node_has_error(ts_tree_root_node(tree))) {
      if (tree) ts_tree_delete(tree);
      goto fail;
    }
    TSNode root = ts_tree_root_node(tree);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      TSNode wrapper = ts_node_named_child(root, i);
      if (strcmp(ts_node_type(wrapper), "declaration")) continue;
      TSNode d = ts_node_named_child(wrapper, ts_node_named_child_count(wrapper)-1);
      const char *kind = ts_node_type(d);
      bool representation = !strcmp(kind, "struct") || !strcmp(kind, "enum") ||
                            !strcmp(kind, "type_alias");
      if (!public_wrapper(wrapper, s) && !representation) continue;
      uint32_t a = ts_node_start_byte(wrapper), b = ts_node_end_byte(wrapper);
      if (!strcmp(ts_node_type(d), "fn")) {
        for (uint32_t k = 0; k < ts_node_named_child_count(d); ++k) {
          TSNode child = ts_node_named_child(d, k);
          if (!strcmp(ts_node_type(child), "block")) { b = ts_node_start_byte(child); break; }
        }
        size_t raw_length = (size_t)(b - a) + 4;
        char *raw = malloc(raw_length);
        if (!raw) { ts_tree_delete(tree); goto fail; }
        int written = snprintf(raw, raw_length, "%.*s{}", (int)(b-a), s->text+a);
        size_t length = 0;
        char *text = written > 0 ? canonical(raw, (size_t)written, &length) : NULL;
        free(raw);
        char **next = realloc(decls, (count + 1) * sizeof(*next));
        if (!text || !next) { free(text); ts_tree_delete(tree); goto fail; }
        decls = next; decls[count++] = text;
        continue;
      }
      if (!strcmp(kind, "variable")) {
        TSNode name = ts_node_named_child(d, 0), type = {0};
        for (uint32_t k = 1; k < ts_node_named_child_count(d); ++k) {
          TSNode child = ts_node_named_child(d, k);
          if (!strcmp(ts_node_type(child), "type_qualifier") ||
              !strcmp(ts_node_type(child), "type")) { type = child; break; }
        }
        if (ts_node_is_null(type)) {
          ts_tree_delete(tree);
          for (size_t k = 0; k < count; ++k) free(decls[k]);
          free(decls); ts_parser_delete(parser); return 3;
        }
        TSNode actual = !strcmp(ts_node_type(type), "type_qualifier")
                            ? ts_node_named_child(type, 0) : type;
        uint32_t na=ts_node_start_byte(name),nb=ts_node_end_byte(name),
                 ta=ts_node_start_byte(actual),tb=ts_node_end_byte(actual);
        size_t raw_length=(nb-na)*2+(tb-ta)+21;char *raw=malloc(raw_length);
        if(!raw){ts_tree_delete(tree);goto fail;}
        int written=snprintf(raw,raw_length,"pub extern %.*s \"%.*s\":%.*s",
          (int)(nb-na),s->text+na,(int)(nb-na),s->text+na,
          (int)(tb-ta),s->text+ta);
        size_t length=0;char *text=written>0?canonical(raw,(size_t)written,&length):NULL;
        free(raw);char **next=realloc(decls,(count+1)*sizeof(*next));
        if(!text||!next){free(text);ts_tree_delete(tree);goto fail;}
        decls=next;decls[count++]=text;continue;
      }
      size_t length = 0; char *text = canonical(s->text + a, b - a, &length);
      char **next = realloc(decls, (count + 1) * sizeof(*next));
      if (!text || !next) { free(text); ts_tree_delete(tree); goto fail; }
      decls = next; decls[count++] = text;
    }
    ts_tree_delete(tree);
  }
  if (count) qsort(decls, count, sizeof(*decls), string_compare);
  size_t total = 0;
  for (size_t i = 0; i < count; ++i) total += strlen(decls[i]) + 1;
  result->data = malloc(total + 1);
  if (!result->data) goto fail;
  result->length = total; total = 0;
  for (size_t i = 0; i < count; ++i) {
    size_t n = strlen(decls[i]); memcpy(result->data + total, decls[i], n);
    result->data[total + n] = '\n'; total += n + 1;
  }
  result->data[total] = 0;
  result->source_hash = dyn_interface_source_hash(sources);
  result->interface_hash = interface_hash_bytes(hash_start(), result->data, result->length);
  for (size_t i = 0; i < count; ++i) free(decls[i]);
  free(decls);
  ts_parser_delete(parser);
  return 0;
fail:
  for (size_t i = 0; i < count; ++i) free(decls[i]);
  free(decls);
  if (parser) ts_parser_delete(parser);
  dyn_interface_free(result);
  return 1;
}

typedef struct {
  unsigned char magic[8]; uint32_t version, schema;
  uint64_t source_hash, interface_hash, payload_length, digest;
  uint32_t target_length, compiler_length;
} Header;
static uint64_t artifact_digest(Header h, const char *target, const char *compiler,
                                const char *payload) {
  h.digest = 0; uint64_t d = interface_hash_bytes(hash_start(), &h, sizeof(h));
  d = interface_hash_bytes(d, target, h.target_length);
  d = interface_hash_bytes(d, compiler, h.compiler_length);
  return interface_hash_bytes(d, payload, (size_t)h.payload_length);
}
int dyn_interface_store(const char *path, const char *target,
                        const char *compiler, const DynInterface *value) {
  size_t pn = strlen(path); char *temporary = malloc(pn + 48);
  if (!temporary) return 1;
  snprintf(temporary, pn + 48, "%s.%ld.tmp", path, (long)getpid());
  Header h = {0}; memcpy(h.magic, magic, sizeof(magic)); h.version = DYNMI_VERSION;
  h.schema = DYNMI_SCHEMA; h.source_hash = value->source_hash;
  h.interface_hash = value->interface_hash; h.payload_length = value->length;
  h.target_length = (uint32_t)strlen(target); h.compiler_length = (uint32_t)strlen(compiler);
  h.digest = artifact_digest(h, target, compiler, value->data);
  FILE *f = fopen(temporary, "wb");
  bool ok = f && fwrite(&h, sizeof(h), 1, f) == 1 &&
            fwrite(target, 1, h.target_length, f) == h.target_length &&
            fwrite(compiler, 1, h.compiler_length, f) == h.compiler_length &&
            fwrite(value->data, 1, value->length, f) == value->length &&
            fflush(f) == 0 && fsync(fileno(f)) == 0;
  if (f && fclose(f)) ok = false;
  if (!ok || rename(temporary, path)) { remove(temporary); free(temporary); return 1; }
  free(temporary); return 0;
}
DynInterfaceStatus dyn_interface_load(const char *path, const char *target,
                                      const char *compiler, uint64_t source_hash,
                                      DynInterface *result) {
  memset(result, 0, sizeof(*result)); FILE *f = fopen(path, "rb"); Header h;
  if (!f) return errno == ENOENT ? DYN_INTERFACE_MISS : DYN_INTERFACE_ERROR;
  if (fread(&h, sizeof(h), 1, f) != 1 || memcmp(h.magic, magic, sizeof(magic)) ||
      h.version != DYNMI_VERSION || h.schema != DYNMI_SCHEMA ||
      h.source_hash != source_hash || h.target_length != strlen(target) ||
      h.compiler_length != strlen(compiler) || h.payload_length > DYNMI_MAX_SIZE) {
    fclose(f); return DYN_INTERFACE_MISS;
  }
  size_t meta = (size_t)h.target_length + h.compiler_length;
  char *bytes = malloc(meta + (size_t)h.payload_length + 1);
  if (!bytes) { fclose(f); return DYN_INTERFACE_ERROR; }
  bool ok = fread(bytes, 1, meta + (size_t)h.payload_length, f) ==
                meta + (size_t)h.payload_length && fgetc(f) == EOF &&
            !memcmp(bytes, target, h.target_length) &&
            !memcmp(bytes + h.target_length, compiler, h.compiler_length);
  char *payload = bytes + meta;
  if (ok) ok = h.interface_hash == interface_hash_bytes(hash_start(), payload, h.payload_length) &&
               h.digest == artifact_digest(h, bytes, bytes + h.target_length, payload);
  fclose(f);
  if (!ok) { free(bytes); return DYN_INTERFACE_MISS; }
  result->data = malloc((size_t)h.payload_length + 1);
  if (!result->data) { free(bytes); return DYN_INTERFACE_ERROR; }
  memcpy(result->data, payload, (size_t)h.payload_length);
  result->data[h.payload_length] = 0; result->length = (size_t)h.payload_length;
  result->source_hash = h.source_hash; result->interface_hash = h.interface_hash;
  free(bytes); return DYN_INTERFACE_HIT;
}
void dyn_interface_free(DynInterface *value) {
  free(value->data); memset(value, 0, sizeof(*value));
}

static size_t interface_directory_length(const char *path) {
  const char *slash = strrchr(path, '/');
  return slash ? (size_t)(slash - path) : 0;
}
static bool interface_same_directory(const char *a, const char *b) {
  size_t an = interface_directory_length(a), bn = interface_directory_length(b);
  return an == bn && !memcmp(a, b, an);
}
int dyn_interface_compose(const DynSources *sources, size_t owner_first,
                          size_t owner_count, const DynInterface *interfaces,
                          size_t interface_count, const char *path,
                          DynSource *out) {
  memset(out, 0, sizeof(*out)); size_t module = 0;
  for (size_t first = 0; first < sources->count;) {
    size_t end = first + 1;
    while (end < sources->count &&
           interface_same_directory(sources->items[first].path, sources->items[end].path)) ++end;
    if (module >= interface_count) return 1;
    ++module; first = end;
  }
  if (module != interface_count) return 1;
  DynSources selected = {0};
  bool reflection = false;
  for (size_t i = 0; i < sources->count; ++i)
    if (strstr(sources->items[i].text, "#typeof")) reflection = true;
  selected.items = calloc(owner_count + interface_count, sizeof(*selected.items));
  if (!selected.items) return 2;
  if (reflection)
    selected.items[selected.count++] = (DynSource){
        .path = "<reflection>", .text = "// #typeof\n", .length = 11};
  module = 0;
  for (size_t first = 0; first < sources->count;) {
    size_t end = first + 1;
    while (end < sources->count &&
           interface_same_directory(sources->items[first].path, sources->items[end].path)) ++end;
    if (first == owner_first && end - first == owner_count) {
      for (size_t i = first; i < end; ++i) {
        selected.items[selected.count++] = sources->items[i];
      }
    } else {
      selected.items[selected.count++] = (DynSource){
          .path = sources->items[first].path, .text = interfaces[module].data,
          .length = interfaces[module].length};
    }
    ++module; first = end;
  }
  int result = dyn_sources_merge(&selected, path, out);
  free(selected.items);
  return result;
}
