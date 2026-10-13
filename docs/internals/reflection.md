# Reflection ABI

Reflection is opt-in per use: call `#typeof(type_or_value)`. No standard-library import is required.
Operand values are type-checked but never evaluated. Bare function names are also accepted.

Compiler provides `TypeKind` and concrete `TypeInfo` as part of builtin ABI. `std/reflect.Kind`
provides public broad categories through `reflect.kind(info)`. `TypeInfo` contains `id`, `kind`, immutable UTF-8
`name`, `size`, and `alignment`. Shape metadata adds `element_id` for pointers, arrays, and
slices; `length` for arrays; `member_count` for structs and enums; and
`parameter_count`/`result_id` for functions. Zero means not applicable (including a void
function result). `fields`, `variants`, and `arguments` expose immutable `TypeMember` slices;
each descriptor contains its source name and related type ID. Plain enum variants and
payload-free variants use type ID zero. Named function values retain argument names; anonymous
function types expose empty argument names. Recursive types are represented safely through IDs.
IDs use stable
FNV-1a hash of canonical type names. Function and void values report size `0`, alignment `1`.

Compiler emits immutable name and descriptor data only for types referenced by `#typeof`.
Metadata lives in read-only program storage: inspection performs no heap or arena allocation.
Related IDs compare directly with another `#typeof` result.

Exact compiler identity is implementation data, not a persistent application ID. Opaque `any`
values should normally be recovered with `case` type patterns; reflection exists for broad
inspection, not routine control flow.
