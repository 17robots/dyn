[
  (block)
  (struct)
  (enum)
  (case_)
  (struct_literal)
  (array_literal)
  (array_type)
  (call)
  (group)
  (fn)
] @indent.begin

[
  "}"
  "]"
  ")"
] @indent.end

(comment) @indent.ignore

[
  (binary)
  (assignment)
  (declaration)
  (struct_literal_member)
  (struct_member)
  (enum_member)
] @indent.align
