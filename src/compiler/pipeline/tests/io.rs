use super::*;

#[test]
fn builds_native_executable_with_console_print_i32() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nos := use \"std/os\"\nmain := () i32 {\n  os.io_write_i32(12, 0)\n  os.io_write_i32(34, 1)\n  return 0\n}\n",
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
fn builds_native_executable_with_console_println_bytes() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nos := use \"std/os\"\nmain := () i32 {\n  os.io_write(\"Hello, world\", 1)\n  return 0\n}\n",
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
fn builds_native_executable_with_io_print_module_member_call() {
    let root = make_temp_dir();
    fs::write(
        root.join("a.dyn"),
        "module main\nmy_io := use \"my_io\"\nmain := () i32 {\n  my_io.print(12)\n  return 0\n}\n",
    )
    .expect("file should be written");
    fs::write(
        root.join("my_io.dyn"),
        "module my_io\nos := use \"std/os\"\npub print := (value: i32) u32 => os.io_write_i32(value, 0)\n",
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
    assert_eq!(stdout, "12");

    fs::remove_dir_all(root).expect("temp directory should be removed");
}

#[test]
fn builds_native_executable_with_user_defined_print_function() {
    let root = make_temp_dir();
    fs::write(
            root.join("a.dyn"),
            "module main\nprint := (value: i32) i32 => value + 1\nmain := () i32 {\n  return print(41)\n}\n",
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
