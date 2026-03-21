use super::*;

#[test]
fn builds_native_executable_with_runtime_vec_i32_intrinsics() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 4)\n  $vec_i32_push(vec, 9)\n  value := $vec_i32_get(vec, 1)\n  $vec_i32_deinit(vec)\n  return value\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_memory_intrinsics() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n  p := alloc.alloc(u8, 4) or return 0\n  q := alloc.alloc(u8, 4) or return 0\n  ok_set := mem.set(p, 7, 4)\n  ok_copy := mem.copy(q, p, 4)\n  eq := mem.eq(p, q, 4)\n  ok_free_p := alloc.free(u8, p, 4)\n  ok_free_q := alloc.free(u8, q, 4)\n  return if ok_set == 1 && ok_copy == 1 && eq == 1 && ok_free_p == 1 && ok_free_q == 1 23 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(23));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_address_taken_array_index_reads_mutated_memory() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nmem := use \"std/mem\"\nmain := () i32 {\n  dst: [8]u8 = [0, 0, 0, 0, 0, 0, 0, 0]\n  dst_ptr := $as(usize, &dst)\n  ok_set := mem.set(dst_ptr, 1, 4)\n  first := dst[0]\n  return if ok_set == 1 && first != 0 24 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(24));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_failing_allocator_vec_behavior() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  failing := heap.FailingAllocator().new()\n  failing.set_fail_after(1)\n  alloc := failing.allocator().ctx\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 3)\n  $vec_i32_push(vec, 5)\n  $vec_i32_push(vec, 7)\n  $vec_i32_push(vec, 11)\n  fail := $vec_i32_push(vec, 13)\n  len := $vec_i32_len(vec)\n  last := $vec_i32_get(vec, 3)\n  $vec_i32_deinit(vec)\n  return if (fail == 0) && (len == 4) && (last == 11) 29 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(29));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_alias_paths() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 10)\n  $vec_i32_push(vec, 14)\n  out := $vec_i32_get(vec, 1)\n  $vec_i32_deinit(vec)\n  return out\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(14));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_cap_and_reserve() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_i32_init(alloc)\n  $vec_i32_reserve(vec, 9)\n  cap := $vec_i32_cap(vec)\n  $vec_i32_deinit(vec)\n  return if cap >= 9 9 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_set_pop_and_clear() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 4)\n  $vec_i32_push(vec, 6)\n  $vec_i32_set(vec, 1, 21)\n  popped := $vec_i32_pop(vec)\n  $vec_i32_clear(vec)\n  len := $vec_i32_len(vec)\n  $vec_i32_deinit(vec)\n  return if len == 0 popped else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(21));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_raw_vec_u64_intrinsics() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 5)\n  $vec_raw_push_u64(vec, 31)\n  out := $vec_raw_get_u64(vec, 1)\n  $vec_raw_deinit(vec)\n  return if out == 31 31 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(31));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_alias_paths() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 2)\n  $vec_raw_push_u64(vec, 37)\n  out := $vec_raw_get_u64(vec, 1)\n  $vec_raw_deinit(vec)\n  return if out == 37 37 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(37));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_cap_and_reserve() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_reserve(vec, 11)\n  cap := $vec_raw_cap(vec)\n  $vec_raw_deinit(vec)\n  return if cap >= 11 11 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(11));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_set_pop_and_clear() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator().ctx\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 3)\n  $vec_raw_push_u64(vec, 8)\n  $vec_raw_set_u64(vec, 1, 42)\n  popped := $vec_raw_pop_u64(vec)\n  $vec_raw_clear(vec)\n  len := $vec_raw_len(vec)\n  $vec_raw_deinit(vec)\n  return if len == 0 && popped == 42 42 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_byte_pointer_ops() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc_obj := c.allocator()\n  alloc := alloc_obj.ctx\n  vec := $vec_raw_init(alloc, 4, 4)\n  src := alloc_obj.alloc(u8, 4) or return 0\n  dst := alloc_obj.alloc(u8, 4) or return 0\n  ok_src_set := mem.set(src, 7, 4)\n  ok_push := $vec_raw_push_bytes(vec, src, 4)\n  ptr := $vec_raw_ptr(vec, 0)\n  mem.set(src, 9, 4)\n  ok_set := $vec_raw_set_bytes(vec, 0, src, 4)\n  ok_get := $vec_raw_get_bytes(vec, 0, dst, 4)\n  eq := mem.eq(src, dst, 4)\n  ok_dst_clear := mem.set(dst, 0, 4)\n  ok_pop := $vec_raw_pop_bytes(vec, dst, 4)\n  eq_pop := mem.eq(src, dst, 4)\n  ok_vec_free := $vec_raw_deinit(vec)\n  ok_src_free := alloc_obj.free(u8, src, 4)\n  ok_dst_free := alloc_obj.free(u8, dst, 4)\n  return if ok_src_set == 1 && ok_push == 1 && ptr != 0 && ok_set == 1 && ok_get == 1 && eq == 1 && ok_dst_clear == 1 && ok_pop == 1 && eq_pop == 1 && ok_vec_free == 1 && ok_src_free == 1 && ok_dst_free == 1 57 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(57));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_arena_allocator_intrinsics() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  base := c.allocator()\n  arena := heap.ArenaAllocator().new(base)\n  alloc := arena.allocator()\n  p := alloc.alloc(u8, 4) or return 1\n  mem.set(p, 7, 4)\n  ok_reset := arena.reset()\n  ok_deinit := arena.deinit()\n  return if ok_reset == 1 && ok_deinit == 1 33 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(33));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_dollar_builtins() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\npath := use \"std/path\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  value := path.normalize(\"./a/../b//c\")\n  len := bytes_mod.len(value)\n  return if len == 3 77 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(77));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
