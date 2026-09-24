; tree-sitter-dyn — highlights for Helix

; Keywords
["struct" "enum"] @keyword.storage.type
["mut"] @keyword.storage.modifier
["use" "pub"] @keyword.control.import

["if" "else" "case"] @keyword.control.conditional
"for" @keyword.control.repeat
"return" @keyword.control.return
["break" "continue"] @keyword.control

; Operators
[
  "=" "+" "-" "*" "/" "%" "=="
  "!==" "<" ">" "<=" ">=" "&&" "||" "!" "&" "|" "^"
  "~" "<<" ">>" "+=" "-=" "*=" "/=" "%=" "&=" "|=" "^="
  "<<=" ">>=" ".." "=>" ".*"
] @operator

; Literals
(int_literal) @constant.numeric.integer
(float_literal) @constant.numeric.float
(string_literal) @string
(char_literal) @constant.character
(boolean_literal) @constant.builtin.boolean
"null" @constant.builtin
"_" @variable.builtin

; Types
(builtin) @type.builtin

(pointer_type
  "mut" @keyword.storage.modifier)

(array_type
  "mut" @keyword.storage.modifier)

((identifier) @type
  (#match? @type "^[A-Z]"))

; Variables / declarations
(declaration
  (decl_lhs
    (identifier) @variable))

; Function declarations
(declaration
  (decl_lhs
    (identifier) @function)
  "="
  (function))

; Parameters
(function
  (identifier) @variable.parameter)

; Function / method calls
(postfix
  (identifier) @function
  (call_postfix))

(postfix
  (postfix
    (field_postfix
      (identifier) @function.method))
  (call_postfix))

(call_arg
  (identifier) @variable.parameter)

; Members
(field_postfix
  (identifier) @variable.other.member)

(struct_member
  (identifier) @variable.other.member)

(struct_init_member
  (identifier) @variable.other.member)

(enum_member
  (identifier) @type.enum.variant)

(enum_literal
  (identifier) @type.enum.variant)

; Labels
(break
  (identifier) @label)

(continue
  (identifier) @label)

; Imports
(use
  (string_literal) @string.special.path)

; Misc
(comment) @comment
(ERROR) @error
