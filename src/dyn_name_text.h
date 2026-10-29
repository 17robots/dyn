#ifndef DYN_NAME_TEXT_H
#define DYN_NAME_TEXT_H
#include <stdlib.h>
#include <string.h>
/* A NUL-terminated copy of a short source name, kept inline so lookups by
   name need no allocation. Longer names fall back to the heap. */
typedef struct {
  char *text;
  char local[64];
} DynNameText;
static inline char *dyn_name_text(DynNameText *t, const char *start, size_t length) {
  t->text = length < sizeof(t->local) ? t->local : (char *)malloc(length + 1);
  if (t->text) {
    memcpy(t->text, start, length);
    t->text[length] = 0;
  }
  return t->text;
}
static inline void dyn_name_text_free(DynNameText *t) {
  if (t->text != t->local) free(t->text);
  t->text = NULL;
}
#endif
