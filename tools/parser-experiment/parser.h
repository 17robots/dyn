#ifndef DYN_EXPERIMENT_PARSER_H
#define DYN_EXPERIMENT_PARSER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Experimental expression and source parser. Source bytes are borrowed; the caller
   owns the flat tree and releases it with exp_free, including on failure. */
typedef enum {
  EXP_NAME, EXP_NUMBER, EXP_BOOL, EXP_NIL, EXP_STRING, EXP_CHAR,
  EXP_GROUP, EXP_PREFIX, EXP_BINARY, EXP_DEREF, EXP_FIELD, EXP_CALL,
  EXP_INDEX, EXP_SLICE, EXP_WRAP, EXP_LEN,
  EXP_TYPE, EXP_TYPE_ARGUMENT, EXP_PRIMITIVE, EXP_TYPE_PARAMETER,
  EXP_FIELD_TYPE, EXP_POINTER_TYPE, EXP_ARRAY_TYPE, EXP_FN_TYPE,
  EXP_CAST, EXP_SIZE, EXP_ALIGN, EXP_OFFSET, EXP_TYPEOF, EXP_LOAD,
  EXP_SYSCALL, EXP_STRUCT, EXP_MEMBER, EXP_ARRAY
} ExpKind;
typedef enum {
  SRC_FILE = 1000, SRC_DECLARATION, SRC_TARGET, SRC_TARGET_CONDITION, SRC_LINK,
  SRC_USE, SRC_IMPORT, SRC_VARIABLE, SRC_CONST, SRC_ALIAS, SRC_STRUCT,
  SRC_STRUCT_MEMBER, SRC_ENUM, SRC_ENUM_MEMBER, SRC_FN, SRC_EXTERN_FN,
  SRC_EXTERN_VARIABLE, SRC_FN_PARAM, SRC_VARIADIC_PARAM, SRC_VARIADIC,
  SRC_BLOCK, SRC_RETURN, SRC_CONTINUE, SRC_BREAK, SRC_IF, SRC_ELSE,
  SRC_CASE, SRC_CASE_ARM, SRC_CASE_PATTERN, SRC_TYPE_PATTERN, SRC_FOR,
  SRC_FOR_CONDITION, SRC_DEFER, SRC_ASSIGNMENT, SRC_ASSERT, SRC_PANIC,
  SRC_RANGE, SRC_QUALIFIER, SRC_REVERSE
} ExpSourceKind;

typedef enum {
  EXP_CONST = 1, EXP_PUBLIC = 2, EXP_PACKED = 4, EXP_DISTINCT = 8,
  EXP_POINTER_BINDING = 16, EXP_INCLUSIVE = 32, EXP_ITERATION = 64,
  EXP_PRIMARY = 128, EXP_BITCAST = 256, EXP_WILDCARD = 512
} ExpFlag;
typedef enum {
  EXP_ROLE_NONE, EXP_ROLE_NAME, EXP_ROLE_LINK_NAME, EXP_ROLE_PATH,
  EXP_ROLE_ALIAS, EXP_ROLE_LIBRARY, EXP_ROLE_LENGTH, EXP_ROLE_CALL_ARGS,
  EXP_ROLE_TYPE, EXP_ROLE_RETURN
} ExpField;
typedef struct {
  uint32_t start, end, first, next, operator_start, parent;
  uint16_t kind, operator_length, flags, field;
} ExpNode;
typedef enum {
  EXP_OK, EXP_SYNTAX_ERROR, EXP_ALLOCATION_ERROR, EXP_LIMIT_ERROR, EXP_CANCELLED
} ExpError;
typedef struct {
  /* Zero selects the default limits. max_depth can lower the hard cap of 256.
     The callback is
     borrowed only for this invocation; false stops parsing immediately. */
  uint64_t max_work;
  uint32_t max_depth;
  bool (*work)(void *data, uint64_t units);
  void *data;
} ExpOptions;
typedef struct {
  ExpNode *nodes;
  uint32_t count, capacity, root, error_offset;
  const char *error;
  ExpError error_kind;
} ExpTree;
/* No recovery or partial success. Error offsets are byte offsets in source.
   Trees must be zero-initialized. Repeated parses reuse storage. */
bool exp_parse(const char *source, size_t length, ExpTree *tree);
bool exp_parse_source(const char *source, size_t length, ExpTree *tree);
bool exp_parse_with_options(const char *source, size_t length, ExpTree *tree,
                            const ExpOptions *options);
bool exp_parse_source_with_options(const char *source, size_t length, ExpTree *tree,
                                   const ExpOptions *options);
const char *exp_source_kind(unsigned kind);
void exp_free(ExpTree *tree);
#endif
