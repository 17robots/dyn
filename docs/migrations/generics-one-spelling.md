# Generics: one spelling

Preview 32 gives each kind of generic one way to be written. Run the tool first, then fix
what it reports:

```sh
python3 tools/migrate-generics.py path/to/project/**/*.dyn
dyn check path/to/project
```

## Types the caller passes

```dyn
// Before
fn zero($T: type) T { ... }

// After
fn zero(T: type) T { ... }
fn pair(K, V: type) Map(K, V) { ... }
```

Calls do not change: `zero(u32)`.

## Types an argument supplies

Write `$T` at every parameter that supplies `T`. The result type and the body use plain `T`.

```dyn
// Before
fn eql(a: $T, b: T) bool { ... }

// After
fn eql(a: $T, b: $T) bool { ... }
```

If a function took `T: type` and also a parameter whose type contains `T`, drop the type
parameter and let the argument supply it. You have to make this change by hand:

```dyn
// Before
fn first(T: type, items: []T) T { ... }
x := first(u32, items)

// After
fn first(items: []$T) T { ... }
x := first(items)
```

## Structs and enums

Their parentheses hold only types, so the names are bare:

```dyn
// Before
struct Map($K: type, $V: type) { ... }
enum(u8) Slot($T: type) { Empty, Full: T }

// After
struct Map(K, V) { ... }
enum(u8) Slot(T) { Empty, Full: T }
```

## Instances as function values

`f(T)` always calls `f`. To pass an instance as a value, name it with `#instance`, one type
per type parameter in declaration order. You have to make this change by hand:

```dyn
// Before
hash := key_hash(u32)

// After
hash := #instance(key_hash, u32)
```

## Float literals

A float literal with no float context is `f64`. If you relied on `x := 1.5` being `f32`,
write the type:

```dyn
x: f32 = 1.5
```
