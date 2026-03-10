use super::*;

#[test]
fn builds_native_executable_with_runtime_vec_i32_intrinsics() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 4)\n  $vec_i32_push(vec, 9)\n  value := $vec_i32_get(vec, 1)\n  $vec_i32_deinit(vec)\n  return value\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_memory_intrinsics() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  p := $alloc_with(alloc, 4, 4)\n  q := $alloc_with(alloc, 4, 4)\n  $mem_set(p, 7, 4)\n  $mem_copy(q, p, 4)\n  eq := $mem_eq(p, q, 4)\n  $free_with(alloc, p, 4, 4)\n  $free_with(alloc, q, 4, 4)\n  return if eq == 1 23 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(23));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_failing_allocator_vec_behavior() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $test_failing_allocator()\n  $test_set_fail_after(1)\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 3)\n  $vec_i32_push(vec, 5)\n  $vec_i32_push(vec, 7)\n  $vec_i32_push(vec, 11)\n  fail := $vec_i32_push(vec, 13)\n  len := $vec_i32_len(vec)\n  last := $vec_i32_get(vec, 3)\n  $vec_i32_deinit(vec)\n  return if (fail == 0) && (len == 4) && (last == 11) 29 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(29));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_alias_paths() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 10)\n  $vec_i32_push(vec, 14)\n  out := $vec_i32_get(vec, 1)\n  $vec_i32_deinit(vec)\n  return out\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(14));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_cap_and_reserve() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_i32_init(alloc)\n  $vec_i32_reserve(vec, 9)\n  cap := $vec_i32_cap(vec)\n  $vec_i32_deinit(vec)\n  return if cap >= 9 9 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(9));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_i32_set_pop_and_clear() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_i32_init(alloc)\n  $vec_i32_push(vec, 4)\n  $vec_i32_push(vec, 6)\n  $vec_i32_set(vec, 1, 21)\n  popped := $vec_i32_pop(vec)\n  $vec_i32_clear(vec)\n  len := $vec_i32_len(vec)\n  $vec_i32_deinit(vec)\n  return if len == 0 popped else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(21));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_raw_vec_u64_intrinsics() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 5)\n  $vec_raw_push_u64(vec, 31)\n  out := $vec_raw_get_u64(vec, 1)\n  $vec_raw_deinit(vec)\n  return if out == 31 31 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(31));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_alias_paths() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 2)\n  $vec_raw_push_u64(vec, 37)\n  out := $vec_raw_get_u64(vec, 1)\n  $vec_raw_deinit(vec)\n  return if out == 37 37 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(37));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_cap_and_reserve() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_reserve(vec, 11)\n  cap := $vec_raw_cap(vec)\n  $vec_raw_deinit(vec)\n  return if cap >= 11 11 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(11));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_set_pop_and_clear() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_raw_init(alloc, 8, 8)\n  $vec_raw_push_u64(vec, 3)\n  $vec_raw_push_u64(vec, 8)\n  $vec_raw_set_u64(vec, 1, 42)\n  popped := $vec_raw_pop_u64(vec)\n  $vec_raw_clear(vec)\n  len := $vec_raw_len(vec)\n  $vec_raw_deinit(vec)\n  return if len == 0 && popped == 42 42 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(42));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_vec_raw_byte_pointer_ops() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  alloc := $c_allocator()\n  vec := $vec_raw_init(alloc, 4, 4)\n  src := $alloc_with(alloc, 4, 4)\n  dst := $alloc_with(alloc, 4, 4)\n  $mem_set(src, 7, 4)\n  ok_push := $vec_raw_push_bytes(vec, src, 4)\n  ptr := $vec_raw_ptr(vec, 0)\n  $mem_set(src, 9, 4)\n  ok_set := $vec_raw_set_bytes(vec, 0, src, 4)\n  ok_get := $vec_raw_get_bytes(vec, 0, dst, 4)\n  eq := $mem_eq(src, dst, 4)\n  ok_pop := $vec_raw_pop_bytes(vec, dst, 4)\n  eq_pop := $mem_eq(src, dst, 4)\n  $vec_raw_deinit(vec)\n  $free_with(alloc, src, 4, 4)\n  $free_with(alloc, dst, 4, 4)\n  return if ok_push == 1 && ptr != 0 && ok_set == 1 && ok_get == 1 && eq == 1 && ok_pop == 1 && eq_pop == 1 57 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(57));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_arena_allocator_intrinsics() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  base := $c_allocator()\n  arena := $arena_allocator(base)\n  p := $alloc_with(arena, 4, 4)\n  $mem_set(p, 7, 4)\n  $arena_reset(arena)\n  $arena_deinit(arena)\n  return 33\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(33));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_runtime_dollar_builtins() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nmain := () i32 {\n  value := $path_normalize(\"./a/../b//c\")\n  len := $bytes_len(value)\n  return if len == 3 77 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(77));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
