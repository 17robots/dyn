#ifndef DYN_LOAD_H
#define DYN_LOAD_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* #load reads a file next to the source that names it. The path must be relative without `..` so a module cannot read outside its directory. */
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
  char *out = (char*)malloc(directory + 1 + length + 1);
  if (!out) return NULL;
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
/* A load argument may contain lexer trivia between its tokens. Unknown or escaped spellings fail closed instead of trusting an incomplete dependency list; semantic analysis remains responsible for diagnostics. */
static inline size_t dyn_load_trivia(const char *text, size_t length, size_t at) {
  for (;;) {
    while (at < length && (text[at] == ' ' || text[at] == '\t' ||
           text[at] == '\r' || text[at] == '\n' || text[at] == '\f' || text[at] == '\v')) ++at;
    if (at + 1 >= length || text[at] != '/') return at;
    if (text[at + 1] == '/') {
      while (at < length && text[at] != '\n') ++at;
    } else if (text[at + 1] == '*') {
      at += 2;
      while (at + 1 < length && !(text[at] == '*' && text[at + 1] == '/')) ++at;
      if (at + 1 >= length) return length;
      at += 2;
    } else return at;
  }
}

/* Folds loaded-file contents into source keys. Failure must remain zero so
   unavailable dependencies cannot accidentally produce reusable artifacts. */
static inline uint64_t dyn_load_hash(uint64_t hash, const char *source_path, const char *text, size_t length) {
  if (!hash) return 0;
  static const char marker[] = "#load";
  for (size_t i = 0; i + sizeof(marker) - 1 <= length; ++i) {
    size_t token = dyn_load_trivia(text, length, i);
    if (token != i) {
      if (token >= length) break;
      i = token;
    }
    if (text[i] == '"' || text[i] == '\'') {
      char quote = text[i++];
      while (i < length && text[i] != quote) {
        if (text[i] == '\\' && i + 1 < length) ++i;
        ++i;
      }
      continue;
    }
    if (length - i < sizeof(marker) - 1 || memcmp(text + i, marker, sizeof(marker) - 1)) continue;
    size_t at = dyn_load_trivia(text, length, i + sizeof(marker) - 1);
    if (at >= length || text[at] != '(') return 0;
    at = dyn_load_trivia(text, length, at + 1);
    if (at >= length || text[at] != '"') return 0;
    size_t start = ++at;
    while (at < length && text[at] != '"' && text[at] != '\n') {
      if (text[at] == '\\') return 0;
      ++at;
    }
    if (at >= length || text[at] != '"') return 0;
    char *path = dyn_load_path(source_path, text + start, at - start);
    size_t size = 0;
    unsigned char *data = path ? dyn_load_read(path, &size) : NULL;
    free(path);
    if (!data) return 0;
    for (size_t j = 0; j < size; ++j)
      hash = (hash ^ data[j]) * UINT64_C(1099511628211);
    hash = (hash ^ size) * UINT64_C(1099511628211);
    free(data);
    i = at;
  }
  return hash;
}
#endif
