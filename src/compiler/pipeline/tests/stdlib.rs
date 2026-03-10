use super::*;

#[test]
fn builds_native_executable_with_std_heap_allocator_api() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n  ptr := alloc.alloc(i32, 2) or |err| return 0\n  ok_free := alloc.free(i32, ptr, 2)\n  return if ok_free == 1 35 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(35));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_vec_api() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n  mut vec := collections.Vec(i32).new(alloc)\n  a: i32 = 4\n  b: i32 = 9\n  vec = vec.push_bytes($as(usize, &a)) or |err| return 0\n  vec = vec.push_bytes($as(usize, &b)) or |err| return 0\n  out: i32 = 0\n  ok_get := vec.get_bytes(1, $as(usize, &out))\n  vec = vec.pop_bytes($as(usize, &out))\n  len := vec.items_len()\n  ok_free := vec.deinit()\n  return if ok_get == 1 && out == 9 && len == 1 && ok_free == 1 41 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(41));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_vec_failing_allocator() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  failing := heap.FailingAllocator().new()\n  failing.set_fail_after(0)\n  mut vec := collections.Vec(i32).new(failing.allocator())\n  value: i32 = 7\n  vec = vec.push_bytes($as(usize, &value)) or |err| {\n    if err == .OutOfMemory return 44\n    return 0\n  }\n  vec.deinit()\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(44));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_stack_and_queue() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n\n  mut stack := collections.Stack(i32).new(alloc)\n  s1: i32 = 3\n  s2: i32 = 8\n  stack = stack.push_bytes($as(usize, &s1)) or |err| return 0\n  stack = stack.push_bytes($as(usize, &s2)) or |err| return 0\n  out_stack: i32 = 0\n  ok_peek := stack.peek_bytes($as(usize, &out_stack))\n  stack = stack.pop_bytes($as(usize, &out_stack))\n  stack_len := stack.len()\n\n  mut queue := collections.Queue(i32).new(alloc)\n  q1: i32 = 5\n  q2: i32 = 7\n  q3: i32 = 11\n  queue = queue.enqueue_bytes($as(usize, &q1)) or |err| return 0\n  queue = queue.enqueue_bytes($as(usize, &q2)) or |err| return 0\n  queue = queue.enqueue_bytes($as(usize, &q3)) or |err| return 0\n  out_queue: i32 = 0\n  queue = queue.dequeue_bytes($as(usize, &out_queue))\n  first := out_queue\n  queue = queue.dequeue_bytes($as(usize, &out_queue))\n  second := out_queue\n  ok_q_peek := queue.peek_bytes($as(usize, &out_queue))\n  third := out_queue\n  queue_len := queue.len()\n\n  ok_stack_free := stack.deinit()\n  ok_queue_free := queue.deinit()\n\n  return if ok_peek == 1 && out_stack == 8 && stack_len == 1 && first == 5 && second == 7 && ok_q_peek == 1 && third == 11 && queue_len == 1 && ok_stack_free == 1 && ok_queue_free == 1 47 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(47));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_diag_severity_text() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\ndiag := use \"std/diag\"\nmain := () i32 {\n  warning := diag.severity_text(.Warning)\n  note := diag.severity_text(.Note)\n  ok_warning := $bytes_eq(warning, \"warning\")\n  ok_note := $bytes_eq(note, \"note\")\n  return if ok_warning == 1 && ok_note == 1 59 else 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(59));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_bool_placeholder_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  value: u1 = true\n  io.println(\"Value is: {}\", { value }) or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Value is: true\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_i32_placeholder_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"n={}\", { 42 }) or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "n=42\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_escape_sequences_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"line1\\nvalue={}\\t!\", { 42 }) or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "line1\nvalue=42\t!\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_plain_one_argument_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"plain output\") or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "plain output\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_multi_placeholder_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  a := 1\n  b: i32 = 2\n  c: i32 = 3\n  io.println(\"vals: \\\"{}\\\", \\\"{}\\\", \\\"{}\\\"\", { a, b, c }) or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "vals: \"1\", \"2\", \"3\"\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_print_tuple_placeholder_from_std() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  vals := { 4, 9 }\n  io.print(\"vals: {} and {}\", vals) or 0\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "{diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "vals: 4 and 9");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_defined_io_print_type_dispatch() {
    let root = make_temp_dir();
    fs::write(
            root.join("my_io.dyn"),
            "module my_io\npub print := (T: type, value: T) u32 => if T == i32 $io_write_i32($as(i32, value), 0) else $io_write_i32(0, 0)\npub println := (T: type, value: T) u32 => if T == i32 $io_write_i32($as(i32, value), 1) else $io_write_i32(0, 1)\n",
        )
        .expect("file should be written");
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"my_io\"\nmain := () i32 {\n  io.print(i32, 12)\n  io.println(i32, 34)\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "1234\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_subdir_io_hello_world_import() {
    let root = make_temp_dir();
    fs::create_dir_all(root.join("std")).expect("std directory should be created");
    fs::write(
        root.join("std").join("io.dyn"),
        "module io\npub println := (text: []u8) u32 => $io_write(text, 1)\n",
    )
    .expect("file should be written");
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"Hello, world\")\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty());
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello, world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_bundled_stdlib_io_without_project_copy() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"Hello, world\") or return 1\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello, world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn decodes_escaped_newline_in_string_literal_for_stdlib_io_print() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.print(\"Hello world\\n\") or return 1\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_path_normalize() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\npath := use \"std/path\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  n1 := path.normalize(\"./a/../b//c\")\n  if bytes_mod.eq(n1, \"b/c\") == 0 return 1\n  n2 := path.normalize(\"/x/./y/../z\")\n  if bytes_mod.eq(n2, \"/x/z\") == 0 return 2\n  n3 := path.normalize(\"../../a\")\n  if bytes_mod.eq(n3, \"../../a\") == 0 return 3\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_fs_list_dir() {
    let root = make_temp_dir();
    fs::create_dir_all(root.join("items").join("nested"))
        .expect("items directory should be created");
    fs::write(root.join("items").join("one.txt"), "1").expect("file should be written");
    fs::write(root.join("items").join("two.txt"), "2").expect("file should be written");
    fs::write(
            root.join("a.dyn"),
            "module main\nfs := use \"std/fs\"\nstr := use \"std/str\"\nmain := () i32 {\n  listing := fs.list_dir(\"items\") or return 1\n  if str.contains(listing, \"one.txt\") == false return 2\n  if str.contains(listing, \"two.txt\") == false return 3\n  if str.contains(listing, \"nested/\") == false return 4\n  return 0\n}\n",
        )
        .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .current_dir(&root)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_path_edge_cases() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\npath := use \"std/path\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  d1 := path.dirname(\"\")\n  if bytes_mod.eq(d1, \".\") == 0 return 1\n  b1 := path.basename(\"/\")\n  if bytes_mod.eq(b1, \"/\") == 0 return 2\n  e1 := path.extension(\"archive.tar.gz\")\n  if bytes_mod.eq(e1, \"gz\") == 0 return 3\n  e2 := path.extension(\".gitignore\")\n  if bytes_mod.eq(e2, \"\") == 0 return 4\n  n1 := path.normalize(\"////\")\n  if bytes_mod.eq(n1, \"/\") == 0 return 5\n  n2 := path.normalize(\"\")\n  if bytes_mod.eq(n2, \".\") == 0 return 6\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let status = Command::new(&artifact.executable_path)
        .status()
        .expect("executable should run");
    assert_eq!(status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_fs_mkdir_write_read_and_empty_list() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nfs := use \"std/fs\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  fs.mkdir_all(\"tmp/a/b\") or return 1\n  fs.mkdir_all(\"tmp/a/b\") or return 2\n  if fs.is_dir(\"tmp/a/b\") == 0 return 3\n  fs.write_all(\"tmp/a/b/file.txt\", \"abc\") or return 4\n  content := fs.read_all(\"tmp/a/b/file.txt\") or return 5\n  if bytes_mod.eq(content, \"abc\") == 0 return 6\n  fs.mkdir_all(\"tmp/empty\") or return 7\n  listing := fs.list_dir(\"tmp/empty\") or return 8\n  if bytes_mod.len(listing) != 0 return 9\n  return 0\n}\n",
    )
    .expect("file should be written");

    let (artifact, diagnostics) = build_project(&root, None).expect("build pipeline should run");
    assert!(diagnostics.is_empty(), "diagnostics: {diagnostics:#?}");
    assert!(artifact.executable_path.exists());

    let output = Command::new(&artifact.executable_path)
        .current_dir(&root)
        .output()
        .expect("executable should run");
    assert_eq!(output.status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
