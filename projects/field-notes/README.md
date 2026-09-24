# Field Notes

An idiomatic Dyn language and memory-management tour demonstrating:

- one OS-backed root arena with explicit `defer` cleanup;
- permanent, frame, and two ping-pong scratch sub-arenas;
- frame reset and nested scratch mark/rewind lifetimes;
- fallible and infallible allocation;
- globals, constants, distinct types, structs, and payload enums;
- exhaustive `case` matching and payload binding;
- arrays, slices, typed pointers, casts, and mutation;
- condition and collection loops;
- homogeneous and `any` variadics;
- caller-buffer formatting and procedural terminal output.

The root owns the mapping. Its sub-arenas borrow fixed partitions and must not be
released individually. Frame and scratch values become invalid on reset or rewind.

Run from the repository root:

```sh
build/dyn run projects/field-notes
```

Then try:

```text
list
add test interactive input
done 3
list
quit
```

Input storage belongs to the frame arena and is reset after every command.
Task records and copied titles belong to the permanent arena. Rendering uses
alternating scratch arenas and rewinds each temporary formatting allocation.
