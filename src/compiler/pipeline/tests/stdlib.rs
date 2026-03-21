use super::*;
use crate::compiler::diagnostics::DiagnosticCode;
use crate::compiler::lexer::scanner::Lexer;
use crate::compiler::parser::parse_file;

fn contains_arrow_block_body(source: &str) -> bool {
    let bytes = source.as_bytes();
    let mut index = 0usize;
    while index + 1 < bytes.len() {
        if bytes[index] != b'=' || bytes[index + 1] != b'>' {
            index += 1;
            continue;
        }

        index += 2;
        loop {
            while index < bytes.len() && bytes[index].is_ascii_whitespace() {
                index += 1;
            }

            if index + 1 < bytes.len() && bytes[index] == b'/' && bytes[index + 1] == b'/' {
                index += 2;
                while index < bytes.len() && bytes[index] != b'\n' {
                    index += 1;
                }
                continue;
            }

            if index + 1 < bytes.len() && bytes[index] == b'/' && bytes[index + 1] == b'*' {
                index += 2;
                while index + 1 < bytes.len() && !(bytes[index] == b'*' && bytes[index + 1] == b'/')
                {
                    index += 1;
                }
                if index + 1 < bytes.len() {
                    index += 2;
                }
                continue;
            }

            break;
        }

        if index < bytes.len() && bytes[index] == b'{' {
            return true;
        }
    }
    false
}

#[test]
fn bundled_stdlib_avoids_arrow_block_function_bodies() {
    let std_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("std");
    let mut dyn_files = Vec::new();
    collect_files_with_extension(&std_root, "dyn", &mut dyn_files);

    let offenders = dyn_files
        .into_iter()
        .filter_map(|path| {
            let source = fs::read_to_string(&path).expect("stdlib source should be readable");
            if contains_arrow_block_body(&source) {
                Some(path)
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    assert!(
        offenders.is_empty(),
        "stdlib files use invalid `=> {{ ... }}` function bodies: {offenders:?}"
    );
}

#[test]
fn bundled_stdlib_avoids_single_expression_if_branch_blocks() {
    let std_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("std");
    let mut dyn_files = Vec::new();
    collect_files_with_extension(&std_root, "dyn", &mut dyn_files);

    let offenders = dyn_files
        .into_iter()
        .filter_map(|path| {
            let source = fs::read_to_string(&path).expect("stdlib source should be readable");
            let relative = path
                .strip_prefix(std::path::Path::new(env!("CARGO_MANIFEST_DIR")))
                .unwrap_or(path.as_path())
                .to_path_buf();
            let lex = Lexer::new(&source, relative.clone()).lex();
            let parsed = parse_file(relative, &lex.tokens);
            if parsed.diagnostics.iter().any(|diagnostic| {
                diagnostic.code == DiagnosticCode::E3001
                    && diagnostic
                        .message
                        .contains("single-expression if branch must not use block braces")
            }) {
                Some(path)
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    assert!(
        offenders.is_empty(),
        "stdlib files use single-expression if branch blocks: {offenders:?}"
    );
}

#[test]
fn builds_native_executable_with_std_heap_allocator_api() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n  ptr := alloc.alloc(i32, 2) or |err| return 0\n  ok_free := alloc.free(i32, ptr, 2)\n  return if ok_free == 1 35 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(35));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_heap_realloc_preserving_prefix() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n\n  p := alloc.alloc(u8, 16) or |err| return 1\n  mem.set(p, 90, 16)\n\n  q := alloc.realloc(u8, p, 16, 64) or |err| return 2\n\n  probe := alloc.alloc(u8, 16) or |err| return 3\n  mem.set(probe, 90, 16)\n\n  eq := mem.eq(q, probe, 16)\n  ok_free_probe := alloc.free(u8, probe, 16)\n  ok_free_q := alloc.free(u8, q, 64)\n\n  if eq != 1 return 4\n  if ok_free_probe != 1 return 5\n  if ok_free_q != 1 return 6\n  return 61\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(61));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_arena_allocator_reset_cycle() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\nmem := use \"std/mem\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  backing := c.allocator()\n\n  arena := heap.ArenaAllocator().new(backing)\n  alloc := arena.allocator()\n\n  p1 := alloc.alloc(u8, 32) or |err| return 1\n  mem.set(p1, 7, 32)\n  p2 := alloc.alloc(u8, 32) or |err| return 2\n  if p2 == 0 return 3\n\n  ok_reset := arena.reset()\n  p3 := alloc.alloc(u8, 32) or |err| return 4\n  ok_deinit := arena.deinit()\n\n  if ok_reset != 1 return 5\n  if p3 == 0 return 6\n  if ok_deinit != 1 return 7\n  return 62\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(62));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_vec_api() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n  mut vec := collections.Vec(i32).new(alloc)\n  a: i32 = 4\n  b: i32 = 9\n  vec = vec.push_bytes($as(usize, &a)) or |err| return 0\n  vec = vec.push_bytes($as(usize, &b)) or |err| return 0\n  out: i32 = 0\n  ok_get := vec.get_bytes(1, $as(usize, &out))\n  vec = vec.pop_bytes($as(usize, &out))\n  len := vec.items_len()\n  ok_free := vec.deinit()\n  return if ok_get == 1 && out == 9 && len == 1 && ok_free == 1 41 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(41));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_vec_failing_allocator() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  failing := heap.FailingAllocator().new()\n  failing.set_fail_after(0)\n  mut vec := collections.Vec(i32).new(failing.allocator())\n  value: i32 = 7\n  vec = vec.push_bytes($as(usize, &value)) or |err| {\n    if err == .OutOfMemory return 44\n    return 0\n  }\n  vec.deinit()\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(44));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_stack_and_queue() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n\n  mut stack := collections.Stack(i32).new(alloc)\n  s1: i32 = 3\n  s2: i32 = 8\n  stack = stack.push_bytes($as(usize, &s1)) or |err| return 0\n  stack = stack.push_bytes($as(usize, &s2)) or |err| return 0\n  out_stack: i32 = 0\n  ok_peek := stack.peek_bytes($as(usize, &out_stack))\n  stack = stack.pop_bytes($as(usize, &out_stack))\n  stack_len := stack.len()\n\n  mut queue := collections.Queue(i32).new(alloc)\n  q1: i32 = 5\n  q2: i32 = 7\n  q3: i32 = 11\n  queue = queue.enqueue_bytes($as(usize, &q1)) or |err| return 0\n  queue = queue.enqueue_bytes($as(usize, &q2)) or |err| return 0\n  queue = queue.enqueue_bytes($as(usize, &q3)) or |err| return 0\n  out_queue: i32 = 0\n  queue = queue.dequeue_bytes($as(usize, &out_queue))\n  first := out_queue\n  queue = queue.dequeue_bytes($as(usize, &out_queue))\n  second := out_queue\n  ok_q_peek := queue.peek_bytes($as(usize, &out_queue))\n  third := out_queue\n  queue_len := queue.len()\n\n  ok_stack_free := stack.deinit()\n  ok_queue_free := queue.deinit()\n\n  return if ok_peek == 1 && out_stack == 8 && stack_len == 1 && first == 5 && second == 7 && ok_q_peek == 1 && third == 11 && queue_len == 1 && ok_stack_free == 1 && ok_queue_free == 1 47 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(47));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_collections_queue_compact_preserves_order() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nheap := use \"std/heap\"\ncollections := use \"std/collections\"\nmain := () i32 {\n  c := heap.CAllocator().new()\n  alloc := c.allocator()\n\n  mut queue := collections.Queue(i32).new(alloc)\n  v1: i32 = 1\n  v2: i32 = 2\n  v3: i32 = 3\n  v4: i32 = 4\n  v5: i32 = 5\n  out: i32 = 0\n\n  queue = queue.enqueue_bytes($as(usize, &v1)) or |err| return 1\n  queue = queue.enqueue_bytes($as(usize, &v2)) or |err| return 2\n  queue = queue.enqueue_bytes($as(usize, &v3)) or |err| return 3\n  queue = queue.enqueue_bytes($as(usize, &v4)) or |err| return 4\n\n  queue = queue.dequeue_bytes($as(usize, &out))\n  first := out\n  queue = queue.dequeue_bytes($as(usize, &out))\n  second := out\n\n  queue = queue.enqueue_bytes($as(usize, &v5)) or |err| return 5\n\n  ok_peek := queue.peek_bytes($as(usize, &out))\n  third := out\n\n  queue = queue.dequeue_bytes($as(usize, &out))\n  fourth := out\n  queue = queue.dequeue_bytes($as(usize, &out))\n  fifth := out\n  queue = queue.dequeue_bytes($as(usize, &out))\n  sixth := out\n\n  len := queue.len()\n  ok_deinit := queue.deinit()\n\n  return if first == 1 && second == 2 && ok_peek == 1 && third == 3 && fourth == 3 && fifth == 4 && sixth == 5 && len == 0 && ok_deinit == 1 63 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(63));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_diag_severity_text() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\ndiag := use \"std/diag\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  warning := diag.severity_text(.Warning)\n  note := diag.severity_text(.Note)\n  ok_warning := bytes_mod.eq(warning, \"warning\")\n  ok_note := bytes_mod.eq(note, \"note\")\n  return if ok_warning == 1 && ok_note == 1 59 else 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(59));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_bool_placeholder_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  value: u1 = true\n  io.println(\"Value is: {}\", { value }) or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Value is: true\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_i32_placeholder_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"n={}\", { 42 }) or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "n=42\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_escape_sequences_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"line1\\nvalue={}\\t!\", { 42 }) or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "line1\nvalue=42\t!\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_plain_one_argument_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"plain output\") or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "plain output\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_println_multi_placeholder_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  a := 1\n  b: i32 = 2\n  c: i32 = 3\n  io.println(\"vals: \\\"{}\\\", \\\"{}\\\", \\\"{}\\\"\", { a, b, c }) or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "vals: \"1\", \"2\", \"3\"\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_io_print_tuple_placeholder_from_std() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  vals := { 4, 9 }\n  io.print(\"vals: {} and {}\", vals) or 0\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "vals: 4 and 9");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_defined_io_print_type_dispatch() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "my_io.dyn",
        "module my_io\nos := use \"std/os\"\npub print := (T: type, value: T) u32 => if T == i32 os.io_write_i32($as(i32, value), 0) else os.io_write_i32(0, 0)\npub println := (T: type, value: T) u32 => if T == i32 os.io_write_i32($as(i32, value), 1) else os.io_write_i32(0, 1)\n",
    );
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"my_io\"\nmain := () i32 {\n  io.print(i32, 12)\n  io.println(i32, 34)\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "1234\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_subdir_io_hello_world_import() {
    let root = make_temp_dir();
    fs::create_dir_all(root.join("std")).expect("std directory should be created");
    write_dyn_file(
        &root,
        "std/io.dyn",
        "module io\nos := use \"std/os\"\npub println := (text: []u8) u32 => os.io_write(text, 1)\n",
    );
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"Hello, world\")\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello, world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_bundled_stdlib_io_without_project_copy() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.println(\"Hello, world\") or return 1\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello, world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn decodes_escaped_newline_in_string_literal_for_stdlib_io_print() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nio := use \"std/io\"\nmain := () i32 {\n  io.print(\"Hello world\\n\") or return 1\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output(&artifact.executable_path);
    assert_eq!(output.status.code(), Some(0));
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert_eq!(stdout, "Hello world\n");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_path_normalize() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\npath := use \"std/path\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  n1 := path.normalize(\"./a/../b//c\")\n  if bytes_mod.eq(n1, \"b/c\") == 0 return 1\n  n2 := path.normalize(\"/x/./y/../z\")\n  if bytes_mod.eq(n2, \"/x/z\") == 0 return 2\n  n3 := path.normalize(\"../../a\")\n  if bytes_mod.eq(n3, \"../../a\") == 0 return 3\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_fs_list_dir() {
    let root = make_temp_dir();
    fs::create_dir_all(root.join("items").join("nested"))
        .expect("items directory should be created");
    fs::write(root.join("items").join("one.txt"), "1").expect("file should be written");
    fs::write(root.join("items").join("two.txt"), "2").expect("file should be written");
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nfs := use \"std/fs\"\nstr := use \"std/str\"\nmain := () i32 {\n  listing := fs.list_dir(\"items\") or return 1\n  if str.contains(listing, \"one.txt\") == false return 2\n  if str.contains(listing, \"two.txt\") == false return 3\n  if str.contains(listing, \"nested/\") == false return 4\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output_in_dir(&artifact.executable_path, &root);
    assert_eq!(output.status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_path_edge_cases() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\npath := use \"std/path\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  d1 := path.dirname(\"\")\n  if bytes_mod.eq(d1, \".\") == 0 return 1\n  b1 := path.basename(\"/\")\n  if bytes_mod.eq(b1, \"/\") == 0 return 2\n  e1 := path.extension(\"archive.tar.gz\")\n  if bytes_mod.eq(e1, \"gz\") == 0 return 3\n  e2 := path.extension(\".gitignore\")\n  if bytes_mod.eq(e2, \"\") == 0 return 4\n  n1 := path.normalize(\"////\")\n  if bytes_mod.eq(n1, \"/\") == 0 return 5\n  n2 := path.normalize(\"\")\n  if bytes_mod.eq(n2, \".\") == 0 return 6\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_fs_mkdir_write_read_and_empty_list() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        "module main\nfs := use \"std/fs\"\nbytes_mod := use \"std/bytes\"\nmain := () i32 {\n  fs.mkdir_all(\"tmp/a/b\") or return 1\n  fs.mkdir_all(\"tmp/a/b\") or return 2\n  if fs.is_dir(\"tmp/a/b\") == 0 return 3\n  fs.write_all(\"tmp/a/b/file.txt\", \"abc\") or return 4\n  content := fs.read_all(\"tmp/a/b/file.txt\") or return 5\n  if bytes_mod.eq(content, \"abc\") == 0 return 6\n  fs.mkdir_all(\"tmp/empty\") or return 7\n  listing := fs.list_dir(\"tmp/empty\") or return 8\n  if bytes_mod.len(listing) != 0 return 9\n  return 0\n}\n",
    );

    let artifact = build_clean_project(&root);
    let output = run_output_in_dir(&artifact.executable_path, &root);
    assert_eq!(output.status.code(), Some(0));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_strconv_parse_and_format() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        r#"module main
strconv := use "std/strconv"
bytes_mod := use "std/bytes"
main := () i32 {
  a := strconv.parse_i32(" -2147483648 ") or |err| return 1
  if a != -2147483648 return 2

  b := strconv.parse_u64("18446744073709551615") or |err| return 3
  if bytes_mod.eq(strconv.format_u64(b), "18446744073709551615") == 0 return 4

  c := strconv.parse_bool("TrUe") or |err| return 5
  if c == false return 6

  i32_overflow := strconv.parse_i32("2147483648") or |err| 1
  if i32_overflow != 1 return 7

  bool_invalid := strconv.parse_bool("maybe") or |err| 1
  if bool_invalid != 1 return 8

  u64_empty := strconv.parse_u64("   ") or |err| 1
  if u64_empty != 1 return 9

  if bytes_mod.eq(strconv.format_i32(-42), "-42") == 0 return 10
  if bytes_mod.eq(strconv.format_u64(99), "99") == 0 return 11
  if bytes_mod.eq(strconv.format_bool(false), "false") == 0 return 12

  return 72
}
"#,
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(72));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_unicode_utf8_utilities() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        r#"module main
unicode := use "std/unicode"
main := () i32 {
  if unicode.is_valid_utf8("hello") == 0 return 1

  scalar_count := unicode.scalar_count("hello") or |err| return 2
  if scalar_count != 5 return 3

  if unicode.next_scalar_len("hello", 0) != 1 return 4
  if unicode.next_scalar_len("hello", 5) != 0 return 5

  bad_arr: [1]u8 = [128]
  bad := bad_arr[..]

  if unicode.is_valid_utf8(bad) != 0 return 6

  if unicode.next_scalar_len(bad, 0) != 0 return 7

  return 73
}
"#,
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(73));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_mem_copy_set_and_eq() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        r#"module main
mem_mod := use "std/mem"
main := () i32 {
  src: [8]u8 = [0, 0, 0, 0, 0, 0, 0, 0]
  dst: [8]u8 = [0, 0, 0, 0, 0, 0, 0, 0]
  src_ptr := $as(usize, &src)
  dst_ptr := $as(usize, &dst)
  ok_set := mem_mod.set(src_ptr, 65, 8)
  ok_copy := mem_mod.copy(dst_ptr, src_ptr, 8)
  ok_eq := mem_mod.eq(src_ptr, dst_ptr, 8)
  if ok_set == 0 return 31
  if ok_copy == 0 return 32
  if ok_eq == 0 return 33
  return 74
}
"#,
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(74));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_fmt_number_formatting() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        r#"module main
fmt := use "std/fmt"
bytes_mod := use "std/bytes"
main := () i32 {
  if bytes_mod.eq(fmt.i32(-42), "-42") == 0 return 1
  if bytes_mod.eq(fmt.u64(42), "42") == 0 return 2
  if bytes_mod.eq(fmt.usize(123), "123") == 0 return 3
  joined := fmt.join3("a", "b", "c")
  if bytes_mod.eq(joined, "abc") == 0 return 4
  return 75
}
"#,
    );

    let artifact = build_clean_project(&root);
    assert_eq!(run_exit_code(&artifact.executable_path), Some(75));

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_std_env_accessors() {
    let root = make_temp_dir();
    write_dyn_file(
        &root,
        "a.dyn",
        r#"module main
env := use "std/env"
bytes_mod := use "std/bytes"
main := () i32 {
  cwd := env.cwd() or return 1
  if bytes_mod.len(cwd) == 0 return 2
  return 76
}
"#,
    );

    let artifact = build_clean_project(&root);
    assert_eq!(
        run_exit_code_with_env(
            &artifact.executable_path,
            "DYN_ENV_TEST_KEY",
            "dyn_env_test_value",
        ),
        Some(76)
    );

    fs::remove_dir_all(root).expect("temp directory should be removed");
}
