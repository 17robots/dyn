#ifndef DYN_EXPERIMENT_PARSER_H
#define DYN_EXPERIMENT_PARSER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Experimental scalar-expression parser. Source bytes are borrowed; the caller
   owns the flat tree and releases it with exp_free, including on failure. */
typedef enum {
  EXP_NAME, EXP_NUMBER, EXP_BOOL, EXP_NIL, EXP_STRING, EXP_CHAR,
  EXP_GROUP, EXP_PREFIX, EXP_BINARY, EXP_DEREF, EXP_FIELD, EXP_CALL,
  EXP_INDEX, EXP_SLICE, EXP_WRAP, EXP_LEN
} ExpKind;
typedef struct {
  uint32_t start, end, first, next, operator_start;
  uint16_t kind, operator_length;
} ExpNode;
typedef struct {
  ExpNode *nodes;
  uint32_t count, capacity, root, error_offset;
  const char *error;
} ExpTree;
/* No recovery or partial success. Error offsets are byte offsets in source.
   Trees must be zero-initialized. Repeated parses reuse storage. */
bool exp_parse(const char *source, size_t length, ExpTree *tree);
void exp_free(ExpTree *tree);
#endif
