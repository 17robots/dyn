; tree-sitter-dyn — textobjects for Helix

; ---------------------------------------------------------------- functions

(function) @function.inside

(declaration
  (decl_lhs
    (identifier) @function.around)
  "="
  (function) @function.inside) @function.around

; ---------------------------------------------------------------- classes/types

(struct) @class.inside
(enum) @class.inside

(struct) @class.around
(enum) @class.around

; ---------------------------------------------------------------- blocks

(block) @block.inside
(block) @block.around

(case
  "{" (_) @_start
  (_) @_end "}") @block.inside

(case) @block.around

; ---------------------------------------------------------------- conditionals

(if) @conditional.around

(if
  (block) @conditional.inside)

(if
  (_) @conditional.inside)

; ---------------------------------------------------------------- loops

(for) @loop.around

(for
  (block) @loop.inside)

(for
  (statement) @loop.inside)

; ---------------------------------------------------------------- parameters

(function
  (identifier) @parameter.inside)

(call_arg) @parameter.inside

(call_arg) @parameter.around

(struct_init_member) @parameter.inside
(struct_init_member) @parameter.around

(struct_member) @parameter.inside
(struct_member) @parameter.around

(enum_member) @parameter.inside
(enum_member) @parameter.around

; ---------------------------------------------------------------- comments

(comment) @comment.inside
(comment) @comment.around

; ---------------------------------------------------------------- entries/items

(declaration) @entry.around
(statement) @entry.around

(struct_member) @entry.around
(enum_member) @entry.around
(struct_init_member) @entry.around

(array_literal
  (expression) @entry.inside)

(array_literal
  (expression) @entry.around)

; ---------------------------------------------------------------- fields

(field_postfix
  (identifier) @entry.inside)

(field_postfix) @entry.around
