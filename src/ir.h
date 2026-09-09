#ifndef DYN_IR_H
#define DYN_IR_H

#include "dyn_ast.h"

typedef struct {
  DynExprKind kind;
  DynType type;
  DynOperator op;
  DynExprId left, right;
  uint64_t integer;
  double floating;
  bool boolean;
  uint32_t item_start, item_count;
  DynSpan span;
} DynIrExpr;

typedef struct {
  DynExprId expression;
  uint32_t field_index;
} DynIrItem;
typedef struct {
  char *name;
  DynType type;
  DynExprId default_expression;
} DynIrField;
typedef struct {
  char *name;
  DynSpan span;
  bool packed;
  bool is_public;
  uint64_t module_owner;
  uint32_t field_start, field_count;
  uint64_t size, alignment;
} DynIrStruct;
typedef struct {
  char *name;
  DynType payload_type;
  uint32_t tag;
} DynIrVariant;
typedef struct {
  char *name;
  DynSpan span;
  DynType tag_type;
  uint32_t variant_start, variant_count;
  uint64_t size, alignment, payload_size, payload_alignment;
  bool has_payload;
  bool is_public;
  uint64_t module_owner;
} DynIrEnum;
typedef struct {
  char *name;
  DynType type;
  uint32_t local_id;
} DynIrParam;
typedef struct {
  char *name, *link_name;
  DynSpan span;
  DynType type;
  DynExprId initializer;
  bool is_const, foreign, is_public;
  uint64_t module_owner;
} DynIrGlobal;
typedef struct {
  DynType pointee;
  bool is_const;
} DynIrPointer;
typedef struct {
  DynType element;
  uint64_t length;
} DynIrArray;
typedef struct {
  DynType element;
  bool is_const;
} DynIrSlice;
typedef struct {
  DynType return_type;
  uint32_t param_start, param_count;
} DynIrFnType;
typedef struct {
  unsigned char *data;
  size_t length;
} DynIrString;
typedef struct {
  char *name, *link_name;
  DynType return_type;
  uint32_t param_start, param_count, body_start, body_count, local_start,
      local_count, variadic_local_id, source_line;
  bool is_main, foreign, variadic, is_public;
  uint64_t module_owner;
  DynType variadic_type;
} DynIrFunction;
typedef struct {
  DynStmtKind kind;
  DynExprId expression, target;
  DynOperator assignment_op;
  uint32_t local_id, body_start, body_count, else_start, else_count, loop_id,
      target_loop_id, case_arm_start, case_arm_count;
  bool defer_block, for_pointer, for_const;
  DynSpan span;
} DynIrStmt;
typedef struct {
  char *name;
  DynType type;
} DynIrLocal;
typedef struct {
  uint64_t first, last;
  DynType type;
  uint32_t variant;
  bool is_enum, is_signed, is_type;
} DynIrPattern;
typedef struct {
  uint32_t pattern_start, pattern_count, body_start, body_count, local_id;
  bool wildcard, pointer_binding;
} DynIrCaseArm;

typedef struct {
  DynIrExpr *expressions;
  size_t expression_count, expression_capacity;
  DynIrItem *items;
  size_t item_count;
  DynIrField *fields;
  size_t field_count;
  DynIrStruct *structs;
  size_t struct_count;
  DynIrEnum *enums;
  size_t enum_count;
  DynIrVariant *variants;
  size_t variant_count;
  DynIrParam *params;
  size_t param_count;
  DynIrFunction *functions;
  size_t function_count;
  DynIrGlobal *globals;
  size_t global_count;
  uint32_t *global_init_order;
  size_t global_init_count;
  DynIrPointer *pointers;
  size_t pointer_count;
  DynIrArray *arrays;
  size_t array_count;
  DynIrSlice *slices;
  size_t slice_count;
  DynIrFnType *fn_types;
  size_t fn_type_count;
  DynType *fn_type_params;
  size_t fn_type_param_count;
  DynIrString *strings;
  size_t string_count;
  DynIrStmt *statements;
  size_t statement_count;
  DynIrPattern *patterns;
  size_t pattern_count;
  DynIrCaseArm *case_arms;
  size_t case_arm_count;
  uint32_t *children;
  size_t child_count;
  DynIrLocal *locals;
  size_t local_count;
} DynIrProgram;

bool dyn_ir_lower(const DynAstFunction *ast, const DynSource *source,
                  DynIrProgram *ir);
void dyn_ir_free(DynIrProgram *ir);

#endif
