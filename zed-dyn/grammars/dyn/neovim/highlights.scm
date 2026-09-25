; bool
(bool_) @boolean

; char
(char_) @character

; comment
(comment) @comment

; constant
(const_variable (variable (identifier) @constant))
(enum_member (identifier) @constant)
(field_access (identifier) @constant)
(target_condition (identifier) @variable.member (identifier) @constant)
(null_) @constant.builtin

; error
(ERROR) @error

; function
(fn (identifier) @function)
(extern_fn (identifier) @function)
[ "#alignof" "#bitcast" "#cast" "#len" "#panic" "#sizeof" "#syscall" "#typeof" ] @function.builtin
(call (primary (identifier) @function.call))
(call (primary (field_access (identifier) @function.method.call)))

; keyword
[ "defer" "enum" "fn" "pub" "struct" "type" "use" "extern" ] @keyword
[ "case" "else" "if" ] @keyword.conditional
[ "is" "in" ] @keyword.operator
"#target" @keyword.directive
[ "break" "continue" ] @keyword.control
"for" @keyword.repeat
"return" @keyword.return

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
(use (string_) @string.special.path)

; type
(enum (identifier) @type)
(struct (identifier) @type)
((identifier) @type (#match? @type "^[A-Z]"))
(type (field_type (identifier) @type))
(type_alias (identifier) @type)
(primitive) @type.builtin
"const" @type.qualifier
(struct "packed" @type.qualifier)

; variable
(variable (identifier) @variable)
(extern_variable (identifier) @variable)
"_" @variable.builtin
(field_access (identifier) @variable.member)
(struct_literal_member (identifier) @variable.member)
(struct_member (identifier) @variable.member)
(fn_param (identifier) @variable.parameter)
(variadic_param (identifier) @variable.parameter)
(type_pattern (identifier) @variable)
