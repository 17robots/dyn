#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Bound compiler memory from accidental/generated hostile source inputs. */
#define DYN_MAX_SOURCE_BYTES (64u * 1024u * 1024u)
#define DYN_MAX_MODULE_BYTES (256u * 1024u * 1024u)
#define DYN_MAX_MODULE_SOURCES 4096u

char *dyn_path_join(const char *a, const char *b) {
  size_t an = strlen(a), bn = strlen(b);
  bool slash = an && a[an - 1] != '/';
  char *r = malloc(an + (size_t)slash + bn + 1);
  if (!r)
    return NULL;
  memcpy(r, a, an);
  if (slash)
    r[an++] = '/';
  memcpy(r + an, b, bn + 1);
  return r;
}
char *dyn_path_basename(const char *path) {
  char resolved[4096];
  if ((strcmp(path, ".") == 0 || strcmp(path, "..") == 0) &&
      getcwd(resolved, sizeof(resolved))) {
    if (strcmp(path, "..") == 0) {
      char *slash = strrchr(resolved, '/');
      if (slash && slash != resolved)
        *slash = 0;
    }
    path = resolved;
  }
  size_t n = strlen(path);
  while (n > 1 && path[n - 1] == '/')
    --n;
  size_t start = n;
  while (start && path[start - 1] != '/')
    --start;
  char *r = malloc(n - start + 1);
  if (!r)
    return NULL;
  memcpy(r, path + start, n - start);
  r[n - start] = 0;
  return r;
}
bool dyn_path_is_directory(const char *path) {
  struct stat st;
  return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}
static int source_compare(const void *a, const void *b) {
  return strcmp(((const DynSource *)a)->path, ((const DynSource *)b)->path);
}
int dyn_sources_load(const char *dir, DynSources *out) {
  memset(out, 0, sizeof(*out));
  DIR *d = opendir(dir);
  if (!d) {
    fprintf(stderr, "error: cannot open module directory '%s'\n", dir);
    return 1;
  }
  struct dirent *entry;
  while ((entry = readdir(d))) {
    size_t n = strlen(entry->d_name);
    if (n < 5 || strcmp(entry->d_name + n - 4, ".dyn") != 0)
      continue;
    if (out->count == DYN_MAX_MODULE_SOURCES) {
      fprintf(stderr, "error: module exceeds 4096 source-file limit\n");
      closedir(d);
      return 1;
    }
    DynSource *items = realloc(out->items, (out->count + 1) * sizeof(*items));
    if (!items) {
      closedir(d);
      return 2;
    }
    out->items = items;
    DynSource *s = &out->items[out->count++];
    memset(s, 0, sizeof(*s));
    s->path = dyn_path_join(dir, entry->d_name);
    FILE *f = fopen(s->path, "rb");
    if (!f) {
      fprintf(stderr, "error: cannot read '%s'\n", s->path);
      closedir(d);
      return 1;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    rewind(f);
    if (size < 0) {
      fclose(f);
      closedir(d);
      return 1;
    }
    if ((unsigned long)size > DYN_MAX_SOURCE_BYTES) {
      fprintf(stderr, "error: source '%s' exceeds 64 MiB limit\n", s->path);
      fclose(f);
      closedir(d);
      return 1;
    }
    s->text = malloc((size_t)size + 1);
    if (!s->text) {
      fclose(f);
      closedir(d);
      return 2;
    }
    s->length = fread(s->text, 1, (size_t)size, f);
    s->text[s->length] = 0;
    fclose(f);
  }
  closedir(d);
  qsort(out->items, out->count, sizeof(*out->items), source_compare);
  return 0;
}
void dyn_sources_free(DynSources *sources) {
  for (size_t i = 0; i < sources->count; ++i) {
    free(sources->items[i].path);
    free(sources->items[i].text);
  }
  free(sources->items);
  memset(sources, 0, sizeof(*sources));
}
int dyn_source_target_enabled(const DynSource *s) {
  const char *p = strstr(s->text, "#target");
  if (!p) return 1;
  p = strchr(p, '(');
  if (!p) return -1;
  ++p;
  while (*p && *p != ')') {
    while (isspace((unsigned char)*p) || *p == ',') ++p;
    char key[32] = {0}, value[32] = {0};
    size_t k = 0, v = 0;
    while ((*p == '_' || isalnum((unsigned char)*p)) && k + 1 < sizeof(key)) key[k++] = *p++;
    while (isspace((unsigned char)*p)) ++p;
    if (*p++ != ':') return -1;
    while (isspace((unsigned char)*p)) ++p;
    while ((*p == '_' || isalnum((unsigned char)*p)) && v + 1 < sizeof(value)) value[v++] = *p++;
    const char *want = dyn_target_property(dyn_target, key);
    if (!want) return -1;
    if (strcmp(value, want)) return 0;
  }
  return *p == ')' ? 1 : -1;
}
int dyn_sources_merge(const DynSources *sources, const char *module_name,
                      DynSource *out) {
  static const char reflection_prelude[] =
      "enum TypeKind { Invalid, Void, Bool, Integer, Float, Pointer, Array, "
      "Slice, Struct, Enum, Function }\n"
      "struct TypeMember { name: []const u8, type_id: u64 }\n"
      "struct TypeInfo { id: u64, kind: "
      "TypeKind, name: []const u8, size: usize, alignment: usize, "
      "element_id: u64, length: usize, member_count: usize, "
      "parameter_count: usize, result_id: u64, fields: []const TypeMember, "
      "variants: []const TypeMember, arguments: []const TypeMember }\n";
  memset(out, 0, sizeof(*out));
  size_t total = 0;
  bool reflection = false;
  for (size_t i = 0; i < sources->count; ++i) {
    int enabled = dyn_source_target_enabled(&sources->items[i]);
    if (enabled < 0) {
      fprintf(stderr, "%s: error: invalid or unknown #target condition\n",
              sources->items[i].path);
      return 1;
    }
    if (!enabled) continue;
    if (strstr(sources->items[i].text, "#typeof"))
      reflection = true;
    if (SIZE_MAX - total < sources->items[i].length + 1)
      return 2;
    total += sources->items[i].length + 1;
    if (total > DYN_MAX_MODULE_BYTES) {
      fprintf(stderr, "error: merged module exceeds 256 MiB limit\n");
      return 1;
    }
  }
  size_t prelude = reflection ? sizeof(reflection_prelude) - 1 : 0;
  if (SIZE_MAX - total < prelude)
    return 2;
  total += prelude;
  out->text = malloc(total + 1);
  out->path = strdup(module_name ? module_name : "<module>");
  if (!out->text || !out->path) {
    dyn_source_free(out);
    return 2;
  }
  size_t at = 0;
  if (prelude) {
    if (reflection) {
      memcpy(out->text + at, reflection_prelude, sizeof(reflection_prelude)-1);
      at += sizeof(reflection_prelude)-1;
    }
  }
  for (size_t i = 0; i < sources->count; ++i) {
    if (!dyn_source_target_enabled(&sources->items[i])) continue;
    memcpy(out->text + at, sources->items[i].text, sources->items[i].length);
    at += sources->items[i].length;
    out->text[at++] = '\n';
  }
  out->text[at] = 0;
  out->length = at;
  return 0;
}
void dyn_source_free(DynSource *s) {
  if (!s)
    return;
  free(s->path);
  free(s->text);
  memset(s, 0, sizeof(*s));
}
