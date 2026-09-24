# std/reflect

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-tools/main.dyn](../../tests/sdk-tools/main.dyn)
- [tests/stdlib-reflect/main.dyn](../../tests/stdlib-reflect/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/reflect/reflect.dyn

[Source](../../compiler/std/reflect/reflect.dyn#L2)

Stable public categories. Compiler-private identity remains hidden.

```dyn
pub enum Kind {
  Invalid,
  None,
  Bool,
  Integer,
  Float,
  Pointer,
  Array,
  Slice,
  Struct,
  Enum,
  Function,
}
```

[Source](../../compiler/std/reflect/reflect.dyn#L20)

Bridge existing compiler metadata into public reflection vocabulary.

```dyn
pub fn category(info: TypeInfo) Kind
```

[Source](../../compiler/std/reflect/reflect.dyn#L36)

```dyn
pub fn same(left: TypeInfo, right: TypeInfo) bool
```

[Source](../../compiler/std/reflect/reflect.dyn#L37)

```dyn
pub fn is_number(info: TypeInfo) bool
```

[Source](../../compiler/std/reflect/reflect.dyn#L41)

```dyn
pub fn is_aggregate(info: TypeInfo) bool
```

[Source](../../compiler/std/reflect/reflect.dyn#L45)

```dyn
pub fn element_is(info: TypeInfo, element: TypeInfo) bool
```

[Source](../../compiler/std/reflect/reflect.dyn#L48)

```dyn
pub fn result_is(info: TypeInfo, result: TypeInfo) bool
```
