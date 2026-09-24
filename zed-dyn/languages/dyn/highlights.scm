; bool
(bool_) @boolean

; char
(char_) @string

; comment
(comment) @comment

; constant
(const_variable (variable (identifier) @constant))
(enum_member (identifier) @constant)
(target_condition (identifier) @property (identifier) @constant)
(null_) @constant.builtin

; error
; Incomplete syntax is reported by diagnostics; do not recolor whole error subtrees.

; function
(fn name: (identifier) @function)
(extern_fn name: (identifier) @function)
[ "#alignof" "#bitcast" "#cast" "#len" "#panic" "#sizeof" "#syscall" "#typeof" ] @function.builtin
(call (primary (identifier) @function))
(call (primary (field_access (identifier) @function.method)))

; keyword
[ "const" "defer" "distinct" "enum" "extern" "fn" "packed" "pub" "struct" "type" "use" ] @keyword

[ "case" "else" "if" ] @keyword.conditional
"is" @keyword.operator
"#target" @keyword.directive
[ "break" "continue" ] @keyword.control
[ "for" "in" ] @keyword.repeat
"return" @keyword.return

(primitive) @type.builtin

; label
(break_ (identifier) @label)
(continue_ (identifier) @label)
(for_ (identifier) @label)

; operator
[
  "=" "+=" "-=" "*=" "/=" "%=" "&=" "|=" ">>=" "<<=" "^="
  "+" "-" "*" "/" "%"
  "==" "!=" "<" ">" "<=" ">="
  "&&" "||"
  "!" "~"
  "&" "|" "^"
  "<<" ">>"
  ".." "..=" "=>" ".*"
] @operator
(variadic) @operator

; punctuation
[ "(" ")" "[" "]" "{" "}" ] @punctuation.bracket
[ "," "." ":" ] @punctuation.delimiter

; number
(number_) @number

; string
(string_) @string
(escape_sequence) @string.escape
(use (string_) @string)
(use alias: (identifier) @namespace)

; type
(enum (identifier) @type)
(struct (identifier) @type)
(type (field_type (identifier) @type))
(type_alias (identifier) @type)

; variable
(declaration (variable (identifier) @variable))
(statement (variable (identifier) @variable))
"_" @variable.builtin
(field_access (identifier) @property)
(struct_literal_member (identifier) @property)
(struct_member (identifier) @property)
(fn_param (identifier) @variable.parameter)
(variadic_param (identifier) @variable.parameter)
(type_pattern (identifier) @variable)
