#ifndef DYN_AST_H
#define DYN_AST_H

#include "dyn.h"
#include <tree_sitter/api.h>

typedef uint32_t DynExprId;
#define DYN_NO_EXPR UINT32_MAX
typedef struct {
  uint32_t start_byte, end_byte;
} DynSpan;

typedef uint32_t DynType;
enum {
  DYN_TYPE_INFER,
  DYN_TYPE_ERROR,
  DYN_TYPE_VOID,
  DYN_TYPE_BOOL,
  DYN_TYPE_I8,
  DYN_TYPE_I16,
  DYN_TYPE_I32,
  DYN_TYPE_I64,
  DYN_TYPE_U8,
  DYN_TYPE_U16,
  DYN_TYPE_U32,
  DYN_TYPE_U64,
  DYN_TYPE_ISIZE,
  DYN_TYPE_USIZE,
  DYN_TYPE_F32,
  DYN_TYPE_F64,
  DYN_TYPE_STRING,
  DYN_TYPE_RAWPTR,
  DYN_TYPE_ANY,
  DYN_TYPE_STRUCT_BASE = 256,
  DYN_TYPE_ENUM_BASE = 32768,
  DYN_TYPE_POINTER_BASE = 65536,
  DYN_TYPE_ARRAY_BASE = 131072,
  DYN_TYPE_SLICE_BASE = 196608,
  DYN_TYPE_FN_BASE = 262144,
  DYN_TYPE_DISTINCT_BASE = 327680,
};

typedef enum {
  DYN_EXPR_INT,
  DYN_EXPR_FLOAT,
  DYN_EXPR_BOOL,
  DYN_EXPR_CHAR,
  DYN_EXPR_STRING,
  DYN_EXPR_NAME,
  DYN_EXPR_UNARY,
  DYN_EXPR_BINARY,
  DYN_EXPR_CONVERT,
  DYN_EXPR_STRUCT,
  DYN_EXPR_FIELD,
  DYN_EXPR_CALL,
  DYN_EXPR_NIL,
  DYN_EXPR_ARRAY,
  DYN_EXPR_INDEX,
  DYN_EXPR_SLICE,
  DYN_EXPR_LEN,
  DYN_EXPR_ENUM,
  DYN_EXPR_GLOBAL,
  DYN_EXPR_FUNCTION,
  DYN_EXPR_INDIRECT_CALL,
  DYN_EXPR_SIZE,
  DYN_EXPR_ALIGN,
  DYN_EXPR_TYPEOF,
  DYN_EXPR_VARIADIC,
  DYN_EXPR_CAST,
  DYN_EXPR_BITCAST,
  DYN_EXPR_SYSCALL
} DynExprKind;
typedef enum {
  DYN_OP_NONE,
  DYN_OP_NEG,
  DYN_OP_NOT,
  DYN_OP_BIT_NOT,
  DYN_OP_ADDRESS,
  DYN_OP_DEREF,
  DYN_OP_ADD,
  DYN_OP_SUB,
  DYN_OP_MUL,
  DYN_OP_DIV,
  DYN_OP_REM,
  DYN_OP_EQ,
  DYN_OP_NE,
  DYN_OP_LT,
  DYN_OP_LE,
  DYN_OP_GT,
  DYN_OP_GE,
  DYN_OP_LOGICAL_AND,
  DYN_OP_LOGICAL_OR,
  DYN_OP_BIT_AND,
  DYN_OP_BIT_OR,
  DYN_OP_BIT_XOR,
  DYN_OP_SHL,
  DYN_OP_SHR
} DynOperator;

typedef struct {
  DynExprKind kind;
  DynType type;
  DynSpan span;
  DynOperator op;
  DynExprId left, right;
  uint64_t integer;
  double floating;
  bool boolean;
  uint32_t item_start, item_count;
} DynAstExpr;
typedef struct {
  DynSpan name;
  DynExprId expression;
  uint32_t field_index;
} DynAstItem;
typedef struct {
  DynSpan name;
  DynType type;
  DynExprId default_expression;
} DynAstField;
typedef struct {
  DynSpan span, name;
  bool packed;
  uint32_t field_start, field_count;
  uint64_t size, alignment;
} DynAstStruct;
typedef struct {
  DynSpan name;
  DynType payload_type;
  uint32_t tag;
} DynAstVariant;
typedef struct {
  DynSpan span, name;
  DynType tag_type;
  uint32_t variant_start, variant_count;
  uint64_t size, alignment, payload_size, payload_alignment;
  bool has_payload;
} DynAstEnum;
typedef struct {
  DynSpan name;
  DynType type;
  uint32_t local_id;
} DynAstParam;
typedef struct {
  DynSpan name;
  DynType type;
  DynExprId initializer;
  bool is_const;
} DynAstGlobal;
typedef struct {
  DynType pointee;
  bool is_const;
} DynAstPointer;
typedef struct {
  DynType element;
  uint64_t length;
} DynAstArray;
typedef struct {
  DynType element;
  bool is_const;
} DynAstSlice;
typedef struct {
  DynType return_type;
  uint32_t param_start, param_count;
} DynAstFnType;
typedef struct {
  DynSpan name;
  DynType target;
  TSNode type_node;
  bool distinct;
  unsigned char state;
} DynAstAlias;
typedef struct {
  unsigned char *data;
  size_t length;
} DynAstString;
typedef struct {
  DynSpan span, name, link_name, variadic_name;
  DynType return_type;
  uint32_t param_start, param_count, body_start, body_count, local_start,
      local_count;
  bool is_main, foreign, variadic;
  DynType variadic_type;
  uint32_t variadic_local_id;
} DynAstFn;

typedef enum {
  DYN_STMT_INVALID,
  DYN_STMT_LOCAL,
  DYN_STMT_ASSIGN,
  DYN_STMT_RETURN,
  DYN_STMT_EXPR,
  DYN_STMT_IF,
  DYN_STMT_FOR,
  DYN_STMT_BREAK,
  DYN_STMT_CONTINUE,
  DYN_STMT_CASE,
  DYN_STMT_DEFER,
  DYN_STMT_PANIC
} DynStmtKind;
typedef struct {
  DynStmtKind kind;
  DynSpan span, name, label, control_label;
  DynType declared_type;
  DynExprId expression, target;
  DynOperator assignment_op;
  uint32_t local_id;
  uint32_t body_start, body_count, else_start, else_count, loop_depth, loop_id,
      target_loop_id, case_arm_start, case_arm_count;
  bool defer_block, for_pointer, for_const, is_const;
} DynAstStmt;
typedef struct {
  DynSpan name;
  DynType type;
  bool active, is_const;
  uint32_t owner_function;
} DynAstLocal;
typedef struct {
  DynSpan span;
  DynExprId first, last;
  DynType type;
  uint64_t first_value, last_value;
  uint32_t variant;
  bool range, inclusive, is_enum, is_signed, is_type;
} DynAstPattern;
typedef struct {
  DynSpan span, binding;
  uint32_t pattern_start, pattern_count, body_start, body_count, local_id;
  bool wildcard, pointer_binding;
} DynAstCaseArm;

typedef struct {
  DynSpan span, name;
  uint32_t parameter_count;
  bool has_return_type;
  uint32_t body_start, body_count;
  DynAstExpr *expressions;
  size_t expression_count, expression_capacity;
  DynAstItem *items;
  size_t item_count, item_capacity;
  DynAstField *fields;
  size_t field_count, field_capacity;
  DynAstStruct *structs;
  size_t struct_count, struct_capacity;
  DynAstEnum *enums;
  size_t enum_count, enum_capacity;
  DynAstVariant *variants;
  size_t variant_count, variant_capacity;
  DynAstParam *params;
  size_t param_count, param_capacity;
  DynAstFn *functions;
  size_t function_count, function_capacity;
  DynAstGlobal *globals;
  size_t global_count, global_capacity;
  uint32_t *global_init_order;
  size_t global_init_count;
  DynAstPointer *pointers;
  size_t pointer_count, pointer_capacity;
  DynAstArray *arrays;
  size_t array_count, array_capacity;
  DynAstSlice *slices;
  size_t slice_count, slice_capacity;
  DynAstFnType *fn_types;
  size_t fn_type_count, fn_type_capacity;
  DynType *fn_type_params;
  size_t fn_type_param_count, fn_type_param_capacity;
  DynAstAlias *aliases;
  size_t alias_count, alias_capacity;
  DynAstString *strings;
  size_t string_count, string_capacity;
  DynAstStmt *statements;
  size_t statement_count, statement_capacity;
  DynAstPattern *patterns;
  size_t pattern_count, pattern_capacity;
  DynAstCaseArm *case_arms;
  size_t case_arm_count, case_arm_capacity;
  uint32_t *children;
  size_t child_count, child_capacity;
  DynAstLocal *locals;
  size_t local_count, local_capacity;
  uint32_t loop_count;
} DynAstFunction;

bool dyn_ast_lower_main(TSNode function, const DynSource *source,
                        DynAstFunction *ast, unsigned *errors);
bool dyn_ast_parse_main_source(const DynSource *source, DynAstFunction *ast,
                               unsigned *errors);
void dyn_ast_function_free(DynAstFunction *ast);
bool dyn_span_text_equal(DynSpan a, DynSpan b, const DynSource *source);
const char *dyn_type_name(DynType type);
bool dyn_type_is_struct(DynType type);
bool dyn_type_is_enum(DynType type);
bool dyn_type_is_pointer(DynType type);
bool dyn_type_is_array(DynType type);
bool dyn_type_is_slice(DynType type);
bool dyn_type_is_function(DynType type);
bool dyn_type_is_distinct(DynType type);

#endif
