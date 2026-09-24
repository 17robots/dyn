#ifndef DYN_LOCATION_H
#define DYN_LOCATION_H
#include "dyn.h"
#include <stdlib.h>
#include <string.h>

/* Immutable original-source line tables, owned by one code generation pass. */
typedef struct {
  const char *text;
  size_t *lines, count;
} DynLocationFile;
typedef struct { DynLocationFile *files; size_t count; } DynLocationIndex;
static inline void dyn_location_free(DynLocationIndex *index) {
  for (size_t i = 0; i < index->count; ++i) free(index->files[i].lines);
  free(index->files); memset(index, 0, sizeof(*index));
}
static inline bool dyn_location_build(DynLocationIndex *index, const DynSource *s) {
  index->files = calloc(s->map_count + 1, sizeof(*index->files));
  if (!index->files) return false;
  index->count = s->map_count + 1;
  for (size_t i = 0; i < index->count; ++i) {
    DynLocationFile *file = &index->files[i];
    file->text = i ? s->maps[i - 1].original_text : s->original_text ? s->original_text : s->text;
    size_t length = i ? s->maps[i - 1].original_length : s->original_text ? s->original_length : s->length;
    size_t count = 1;
    for (size_t j = 0; j < length; ++j) count += file->text[j] == '\n';
    if (count > SIZE_MAX / sizeof(*file->lines)) { dyn_location_free(index); return false; }
    file->lines = malloc(count * sizeof(*file->lines));
    if (!file->lines) { dyn_location_free(index); return false; }
    file->lines[file->count++] = 0;
    for (size_t j = 0; j < length; ++j)
      if (file->text[j] == '\n') file->lines[file->count++] = j + 1;
  }
  return true;
}
static inline void dyn_location_get(const DynLocationIndex *index, const DynSource *s,
                                    size_t byte, const char **path,
                                    unsigned *line, unsigned *column) {
  const char *text;
  size_t length, offset;
  dyn_source_position(s, byte, path, &text, &length, &offset);
  if (offset > length) offset = length;
  for (size_t i = 0; i < index->count; ++i) {
    const DynLocationFile *file = &index->files[i];
    if (file->text != text) continue;
    size_t first = 0, end = file->count;
    while (first < end) {
      size_t mid = first + (end - first) / 2;
      if (file->lines[mid] <= offset) first = mid + 1;
      else end = mid;
    }
    *line = (unsigned)first;
    *column = (unsigned)(offset - file->lines[first - 1] + 1);
    return;
  }
  dyn_source_location(s, byte, path, line, column);
}
#endif
