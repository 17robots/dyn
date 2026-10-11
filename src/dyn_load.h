#ifndef DYN_LOAD_H
#define DYN_LOAD_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* #load reads a file next to the source that names it. The path must be
   relative without `..` so a module cannot read outside its directory. */
#define DYN_MAX_LOAD_BYTES (64u * 1024u * 1024u)

static inline char *dyn_load_path(const char *source_path, const char *relative, size_t length) {
  if (!length || relative[0] == '/' || memchr(relative, '\\', length) ||
      memchr(relative, 0, length))
    return NULL;
  for (size_t i = 0; i < length;) {
    size_t end = i;
    while (end < length && relative[end] != '/')
      ++end;
    if (end - i == 2 && relative[i] == '.' && relative[i + 1] == '.')
      return NULL;
    i = end + 1;
  }
  const char *slash = strrchr(source_path, '/');
  size_t directory = slash ? (size_t)(slash - source_path) : 1;
  char *out = malloc(directory + 1 + length + 1);
  if (!out)
    return NULL;
  memcpy(out, slash ? source_path : ".", directory);
  out[directory] = '/';
  memcpy(out + directory + 1, relative, length);
  out[directory + 1 + length] = 0;
  return out;
}
static inline unsigned char *dyn_load_read(const char *path, size_t *length) {
  FILE *f = fopen(path, "rb");
  if (!f)
    return NULL;
  long size = fseek(f, 0, SEEK_END) ? -1 : ftell(f);
  unsigned char *data = NULL;
  if (size >= 0 && (unsigned long)size <= DYN_MAX_LOAD_BYTES &&
      !fseek(f, 0, SEEK_SET) && (data = malloc((size_t)size + 1))) {
    *length = fread(data, 1, (size_t)size, f);
    if (*length != (size_t)size || ferror(f)) {
      free(data);
      data = NULL;
    }
  }
  fclose(f);
  return data;
}
/* Folds the contents of every file a source #loads into hash, so caches
   keyed on source text also notice edits to loaded files. */
static inline uint64_t dyn_load_hash(uint64_t hash, const char *source_path,
                                     const char *text, size_t length) {
  static const char marker[] = "#load(\"";
  for (size_t i = 0; i + sizeof(marker) - 1 < length; ++i) {
    if (memcmp(text + i, marker, sizeof(marker) - 1))
      continue;
    size_t start = i + sizeof(marker) - 1, end = start;
    while (end < length && text[end] != '"' && text[end] != '\n')
      ++end;
    char *path = dyn_load_path(source_path, text + start, end - start);
    size_t size = 0;
    unsigned char *data = path ? dyn_load_read(path, &size) : NULL;
    for (size_t j = 0; data && j < size; ++j)
      hash = (hash ^ data[j]) * UINT64_C(1099511628211);
    hash = (hash ^ (data ? size : UINT64_MAX)) * UINT64_C(1099511628211);
    free(data);
    free(path);
    i = end;
  }
  return hash;
}
#endif
