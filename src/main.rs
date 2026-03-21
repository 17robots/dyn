use std::env;
use std::fs;
use std::process::{self, Command};

use dyn_compiler::compiler::backend::BuildOptLevel;
use dyn_compiler::compiler::diagnostics::Diagnostic;
use dyn_compiler::compiler::module_resolver::resolve_module_graph;
use dyn_compiler::compiler::pipeline::{
    analyze_project, build_project_with_opt_level, lex_project, lower_project_hir,
    lower_project_mir, parse_project,
};

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if matches!(args.first().map(String::as_str), Some("build")) {
        run_build_command(&args[1..]);
        return;
    }

    if matches!(args.first().map(String::as_str), Some("run")) {
        run_run_command(&args[1..]);
        return;
    }

    if matches!(args.first().map(String::as_str), Some("init")) {
        run_init_command(&args[1..]);
        return;
    }

    if matches!(args.first().map(String::as_str), Some("new")) {
        run_new_command(&args[1..]);
        return;
    }

    if matches!(args.first().map(String::as_str), Some("fmt")) {
        run_fmt_command(&args[1..]);
        return;
    }

    match args.as_slice() {
        [] => run_resolver("."),
        [cmd] if cmd == "resolve" => run_resolver("."),
        [cmd, flag] if cmd == "resolve" && flag == "--json" => run_resolver_json("."),
        [cmd, flag, dir] if cmd == "resolve" && flag == "--json" => run_resolver_json(dir),
        [cmd, dir] if cmd == "resolve" => run_resolver(dir),
        [cmd, dir, flag] if cmd == "resolve" && flag == "--json" => run_resolver_json(dir),
        [cmd] if cmd == "lex" => run_lexer(".", false),
        [cmd, flag] if cmd == "lex" && flag == "--json" => run_lexer(".", true),
        [cmd, flag, dir] if cmd == "lex" && flag == "--json" => run_lexer(dir, true),
        [cmd, dir] if cmd == "lex" => run_lexer(dir, false),
        [cmd, dir, flag] if cmd == "lex" && flag == "--json" => run_lexer(dir, true),
        [cmd] if cmd == "parse" => run_parser("."),
        [cmd, flag] if cmd == "parse" && flag == "--json" => run_parser_json("."),
        [cmd, flag, dir] if cmd == "parse" && flag == "--json" => run_parser_json(dir),
        [cmd, dir] if cmd == "parse" => run_parser(dir),
        [cmd, dir, flag] if cmd == "parse" && flag == "--json" => run_parser_json(dir),
        [cmd, flag] if cmd == "parse" && flag == "--ast" => run_parser_with_ast("."),
        [cmd, dir, flag] if cmd == "parse" && flag == "--ast" => run_parser_with_ast(dir),
        [cmd] if cmd == "analyze" => run_analyzer("."),
        [cmd, flag] if cmd == "analyze" && flag == "--json" => run_analyzer_json("."),
        [cmd, flag, dir] if cmd == "analyze" && flag == "--json" => run_analyzer_json(dir),
        [cmd, dir] if cmd == "analyze" => run_analyzer(dir),
        [cmd, dir, flag] if cmd == "analyze" && flag == "--json" => run_analyzer_json(dir),
        [cmd] if cmd == "hir" => run_hir("."),
        [cmd, flag] if cmd == "hir" && flag == "--json" => run_hir_json("."),
        [cmd, flag, dir] if cmd == "hir" && flag == "--json" => run_hir_json(dir),
        [cmd, dir] if cmd == "hir" => run_hir(dir),
        [cmd, dir, flag] if cmd == "hir" && flag == "--json" => run_hir_json(dir),
        [cmd] if cmd == "mir" => run_mir("."),
        [cmd, flag] if cmd == "mir" && flag == "--json" => run_mir_json("."),
        [cmd, flag, dir] if cmd == "mir" && flag == "--json" => run_mir_json(dir),
        [cmd, dir] if cmd == "mir" => run_mir(dir),
        [cmd, dir, flag] if cmd == "mir" && flag == "--json" => run_mir_json(dir),
        [dir] => run_resolver(dir),
        _ => {
            eprintln!(
                "usage: cargo run -- [resolve|lex|parse|analyze|hir|mir|init|new|fmt|build|run] [start_directory] [--json|--ast|--force|--check|-o output|--all-opt-levels|-O0|-O1|-O2|-O3|-Os|-Oz|-o:none|-o:speed|-o:size|-o:aggressive|--opt-level 0|1|2|3|s|z|none|speed|size|aggressive|-- <program args>]"
            );
            process::exit(2);
        }
    }
}

fn run_resolver(start_dir: &str) {
    match resolve_module_graph(start_dir) {
        Ok(graph) => {
            for module in graph.modules {
                println!(
                    "[#{} {} :: {}]",
                    module.id.0,
                    module.key.directory.display(),
                    module.key.module_name
                );
                for file in module.files {
                    println!("  - {}", file.display());
                }
            }

            if !graph.diagnostics.is_empty() {
                print_diagnostics_text(&graph.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_resolver_json(start_dir: &str) {
    match resolve_module_graph(start_dir) {
        Ok(graph) => {
            println!("{{");
            println!("  \"modules\": [");
            for (idx, module) in graph.modules.iter().enumerate() {
                println!("    {{");
                println!("      \"module_id\": {},", module.id.0);
                println!(
                    "      \"directory\": \"{}\",",
                    json_escape(&module.key.directory.display().to_string())
                );
                println!(
                    "      \"module\": \"{}\",",
                    json_escape(&module.key.module_name)
                );
                println!("      \"files\": [");
                for (file_idx, file) in module.files.iter().enumerate() {
                    print!("        \"{}\"", json_escape(&file.display().to_string()));
                    if file_idx + 1 != module.files.len() {
                        println!(",");
                    } else {
                        println!();
                    }
                }
                println!("      ]");
                print!("    }}");
                if idx + 1 != graph.modules.len() {
                    println!(",");
                } else {
                    println!();
                }
            }
            println!("  ],");
            print_diagnostics_json(&graph.diagnostics);
            println!("}}");
            if !graph.diagnostics.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_lexer(start_dir: &str, json: bool) {
    match lex_project(start_dir) {
        Ok(session) => {
            if json {
                print_lex_session_json(&session.files, &session.diagnostics);
                if !session.diagnostics.is_empty() {
                    process::exit(1);
                }
                return;
            }

            for file in session.files {
                println!("[#{} {}]", file.module_id.0, file.file_path.display());
                for token in file.tokens {
                    println!(
                        "  - {:?} {:?} @{}:{}",
                        token.kind, token.lexeme, token.span.start_line, token.span.start_col
                    );
                }
            }

            if !session.diagnostics.is_empty() {
                print_diagnostics_text(&session.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_parser(start_dir: &str) {
    match parse_project(start_dir) {
        Ok(session) => {
            for file in session.files {
                println!("[#{} {}]", file.module_id.0, file.file_path.display());
                match file.ast {
                    Some(ast) => {
                        println!("  - module: {}", ast.module_decl.name.text);
                        println!("  - items: {}", ast.items.len());
                    }
                    None => {
                        println!("  - parse failed for file");
                    }
                }
            }

            if !session.diagnostics.is_empty() {
                print_diagnostics_text(&session.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_parser_with_ast(start_dir: &str) {
    match parse_project(start_dir) {
        Ok(session) => {
            for file in session.files {
                println!("[#{} {}]", file.module_id.0, file.file_path.display());
                match file.ast {
                    Some(ast) => {
                        println!("{:#?}", ast);
                    }
                    None => {
                        println!("  - parse failed for file");
                    }
                }
            }

            if !session.diagnostics.is_empty() {
                print_diagnostics_text(&session.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_parser_json(start_dir: &str) {
    match parse_project(start_dir) {
        Ok(session) => {
            println!("{{");
            println!("  \"files\": [");
            for (idx, file) in session.files.iter().enumerate() {
                println!("    {{");
                println!("      \"module_id\": {},", file.module_id.0);
                println!(
                    "      \"file\": \"{}\",",
                    json_escape(&file.file_path.display().to_string())
                );
                if let Some(ast) = &file.ast {
                    println!(
                        "      \"module\": \"{}\",",
                        json_escape(&ast.module_decl.name.text)
                    );
                    println!("      \"items\": {},", ast.items.len());
                    println!("      \"parsed\": true");
                } else {
                    println!("      \"module\": null,");
                    println!("      \"items\": 0,");
                    println!("      \"parsed\": false");
                }
                print!("    }}");
                if idx + 1 != session.files.len() {
                    println!(",");
                } else {
                    println!();
                }
            }
            println!("  ],");
            print_diagnostics_json(&session.diagnostics);
            println!("}}");

            if !session.diagnostics.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_analyzer(start_dir: &str) {
    match analyze_project(start_dir) {
        Ok((_parsed, units, sema)) => {
            for unit in units {
                let import_count = sema
                    .modules
                    .iter()
                    .find(|module| module.module_id == unit.module_id)
                    .map(|module| module.imports.len())
                    .unwrap_or(0);

                println!(
                    "[#{} {} :: {}] decls={} imports={}",
                    unit.module_id.0,
                    unit.key.directory.display(),
                    unit.key.module_name,
                    unit.declarations.len(),
                    import_count
                );
            }

            if !sema.diagnostics.is_empty() {
                print_diagnostics_text(&sema.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_analyzer_json(start_dir: &str) {
    match analyze_project(start_dir) {
        Ok((_parsed, units, sema)) => {
            println!("{{");
            println!("  \"modules\": [");
            for (idx, unit) in units.iter().enumerate() {
                println!("    {{");
                println!("      \"module_id\": {},", unit.module_id.0);
                println!(
                    "      \"directory\": \"{}\",",
                    json_escape(&unit.key.directory.display().to_string())
                );
                println!(
                    "      \"module\": \"{}\",",
                    json_escape(&unit.key.module_name)
                );
                println!("      \"decls\": {}", unit.declarations.len());
                print!("    }}");
                if idx + 1 != units.len() {
                    println!(",");
                } else {
                    println!();
                }
            }
            println!("  ],");
            print_diagnostics_json(&sema.diagnostics);
            println!("}}");
            if !sema.diagnostics.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_hir(start_dir: &str) {
    match lower_project_hir(start_dir) {
        Ok((_parsed, _units, sema, hir)) => {
            for module in hir.modules {
                let typed_items = module
                    .items
                    .iter()
                    .filter(|item| item.inferred_type.is_some())
                    .count();
                println!(
                    "[#{} {} :: {}] hir_items={} typed_items={}",
                    module.module_id.0,
                    module.key.directory.display(),
                    module.key.module_name,
                    module.items.len(),
                    typed_items
                );
            }

            if !sema.diagnostics.is_empty() {
                print_diagnostics_text(&sema.diagnostics);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_hir_json(start_dir: &str) {
    match lower_project_hir(start_dir) {
        Ok((_parsed, _units, sema, hir)) => {
            println!("{{");
            println!("  \"modules\": [");
            for (idx, module) in hir.modules.iter().enumerate() {
                let typed_items = module
                    .items
                    .iter()
                    .filter(|item| item.inferred_type.is_some())
                    .count();
                println!("    {{");
                println!("      \"module_id\": {},", module.module_id.0);
                println!(
                    "      \"directory\": \"{}\",",
                    json_escape(&module.key.directory.display().to_string())
                );
                println!(
                    "      \"module\": \"{}\",",
                    json_escape(&module.key.module_name)
                );
                println!("      \"hir_items\": {},", module.items.len());
                println!("      \"typed_items\": {}", typed_items);
                print!("    }}");
                if idx + 1 != hir.modules.len() {
                    println!(",");
                } else {
                    println!();
                }
            }
            println!("  ],");
            print_diagnostics_json(&sema.diagnostics);
            println!("}}");
            if !sema.diagnostics.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_mir(start_dir: &str) {
    match lower_project_mir(start_dir) {
        Ok((_parsed, _units, sema, _hir, mir, mir_diagnostics)) => {
            for module in mir.modules {
                let block_count = module
                    .functions
                    .iter()
                    .map(|function| function.blocks.len())
                    .sum::<usize>();
                println!(
                    "[#{} {} :: {}] mir_functions={} blocks={}",
                    module.module_id.0,
                    module.key.directory.display(),
                    module.key.module_name,
                    module.functions.len(),
                    block_count,
                );
            }

            if !sema.diagnostics.is_empty() || !mir_diagnostics.is_empty() {
                let mut all = sema.diagnostics;
                all.extend(mir_diagnostics);
                print_diagnostics_text(&all);
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_mir_json(start_dir: &str) {
    match lower_project_mir(start_dir) {
        Ok((_parsed, _units, sema, _hir, mir, mir_diagnostics)) => {
            println!("{{");
            println!("  \"modules\": [");
            for (idx, module) in mir.modules.iter().enumerate() {
                let block_count = module
                    .functions
                    .iter()
                    .map(|function| function.blocks.len())
                    .sum::<usize>();
                println!("    {{");
                println!("      \"module_id\": {},", module.module_id.0);
                println!(
                    "      \"directory\": \"{}\",",
                    json_escape(&module.key.directory.display().to_string())
                );
                println!(
                    "      \"module\": \"{}\",",
                    json_escape(&module.key.module_name)
                );
                println!("      \"functions\": {},", module.functions.len());
                println!("      \"blocks\": {}", block_count);
                print!("    }}");
                if idx + 1 != mir.modules.len() {
                    println!(",");
                } else {
                    println!();
                }
            }
            println!("  ],");
            let mut all = sema.diagnostics;
            all.extend(mir_diagnostics);
            print_diagnostics_json(&all);
            println!("}}");
            if !all.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_build_command(args: &[String]) {
    let mut start_dir: Option<&str> = None;
    let mut output: Option<&str> = None;
    let mut json = false;
    let mut opt_level = BuildOptLevel::Default;
    let mut opt_level_explicit = false;
    let mut all_opt_levels = false;
    let mut index = 0usize;

    while index < args.len() {
        match parse_opt_level_cli_arg(args, index) {
            Ok(Some((level, consumed))) => {
                opt_level = level;
                opt_level_explicit = true;
                index += consumed;
                continue;
            }
            Ok(None) => {}
            Err(message) => {
                eprintln!("{message}");
                process::exit(2);
            }
        }

        let arg = args[index].as_str();
        match arg {
            "--json" => {
                json = true;
                index += 1;
            }
            "--all-opt-levels" => {
                all_opt_levels = true;
                index += 1;
            }
            "-o" => {
                if index + 1 >= args.len() {
                    eprintln!("missing output path after -o");
                    process::exit(2);
                }
                output = Some(args[index + 1].as_str());
                index += 2;
            }
            _ => {
                if start_dir.is_none() {
                    start_dir = Some(arg);
                    index += 1;
                } else {
                    eprintln!("unexpected build argument '{arg}'");
                    process::exit(2);
                }
            }
        }
    }

    let dir = start_dir.unwrap_or(".");
    if all_opt_levels {
        if opt_level_explicit {
            eprintln!("cannot combine --all-opt-levels with explicit optimization flags");
            process::exit(2);
        }
        let Some(output_base) = output else {
            eprintln!("--all-opt-levels requires -o <output_base>");
            process::exit(2);
        };
        if json {
            run_build_all_json(dir, output_base);
        } else {
            run_build_all(dir, output_base);
        }
        return;
    }

    if json {
        run_build_json(dir, output, opt_level);
    } else {
        run_build(dir, output, opt_level);
    }
}

fn run_run_command(args: &[String]) {
    let mut start_dir: Option<&str> = None;
    let mut opt_level = BuildOptLevel::Default;
    let mut program_args = Vec::<String>::new();
    let mut passthrough = false;
    let mut index = 0usize;

    while index < args.len() {
        let arg = args[index].as_str();
        if passthrough {
            program_args.push(args[index].clone());
            index += 1;
            continue;
        }

        match parse_opt_level_cli_arg(args, index) {
            Ok(Some((level, consumed))) => {
                opt_level = level;
                index += consumed;
                continue;
            }
            Ok(None) => {}
            Err(message) => {
                eprintln!("{message}");
                process::exit(2);
            }
        }

        match arg {
            "--" => {
                passthrough = true;
                index += 1;
            }
            _ => {
                if start_dir.is_none() {
                    start_dir = Some(arg);
                    index += 1;
                } else {
                    eprintln!("unexpected run argument '{arg}'");
                    process::exit(2);
                }
            }
        }
    }

    let dir = start_dir.unwrap_or(".");
    run_project(dir, opt_level, &program_args);
}

const INIT_MAIN_TEMPLATE: &str = "module main\n\nmain := () i32 => 0\n";
const FMT_SKIPPED_DIRS: &[&str] = &[".git", "target", ".dyn_build", "node_modules"];

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
struct InitCommandArgs<'a> {
    target_dir: &'a str,
    force: bool,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
struct NewCommandArgs<'a> {
    target_dir: &'a str,
    force: bool,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
struct FmtCommandArgs<'a> {
    target_dir: &'a str,
    check: bool,
}

enum ScaffoldError {
    Usage(String),
    Io(String),
}

fn parse_init_command_args(args: &[String]) -> Result<InitCommandArgs<'_>, String> {
    let mut target_dir: Option<&str> = None;
    let mut force = false;

    for arg in args {
        match arg.as_str() {
            "--force" => {
                force = true;
            }
            flag if flag.starts_with('-') => {
                return Err(format!("unexpected init flag '{flag}'"));
            }
            path => {
                if target_dir.is_some() {
                    return Err(format!("unexpected init argument '{path}'"));
                }
                target_dir = Some(path);
            }
        }
    }

    Ok(InitCommandArgs {
        target_dir: target_dir.unwrap_or("."),
        force,
    })
}

fn parse_new_command_args(args: &[String]) -> Result<NewCommandArgs<'_>, String> {
    let mut target_dir: Option<&str> = None;
    let mut force = false;

    for arg in args {
        match arg.as_str() {
            "--force" => {
                force = true;
            }
            flag if flag.starts_with('-') => {
                return Err(format!("unexpected new flag '{flag}'"));
            }
            path => {
                if target_dir.is_some() {
                    return Err(format!("unexpected new argument '{path}'"));
                }
                target_dir = Some(path);
            }
        }
    }

    let Some(target_dir) = target_dir else {
        return Err("missing project directory for new command".to_string());
    };

    Ok(NewCommandArgs { target_dir, force })
}

fn parse_fmt_command_args(args: &[String]) -> Result<FmtCommandArgs<'_>, String> {
    let mut target_dir: Option<&str> = None;
    let mut check = false;

    for arg in args {
        match arg.as_str() {
            "--check" => {
                check = true;
            }
            flag if flag.starts_with('-') => {
                return Err(format!("unexpected fmt flag '{flag}'"));
            }
            path => {
                if target_dir.is_some() {
                    return Err(format!("unexpected fmt argument '{path}'"));
                }
                target_dir = Some(path);
            }
        }
    }

    Ok(FmtCommandArgs {
        target_dir: target_dir.unwrap_or("."),
        check,
    })
}

fn initialize_project_scaffold(
    target_dir: &std::path::Path,
    force: bool,
) -> Result<std::path::PathBuf, ScaffoldError> {
    if target_dir.exists() {
        if !target_dir.is_dir() {
            return Err(ScaffoldError::Usage(format!(
                "target '{}' exists and is not a directory",
                target_dir.display()
            )));
        }
    } else {
        fs::create_dir_all(target_dir).map_err(|error| {
            ScaffoldError::Io(format!(
                "failed to create target directory '{}': {error}",
                target_dir.display()
            ))
        })?;
    }

    let main_file = target_dir.join("main.dyn");
    if main_file.exists() && !force {
        return Err(ScaffoldError::Usage(format!(
            "refusing to overwrite '{}'; use --force to replace it",
            main_file.display()
        )));
    }

    fs::write(&main_file, INIT_MAIN_TEMPLATE).map_err(|error| {
        ScaffoldError::Io(format!(
            "failed to write '{}': {error}",
            main_file.display()
        ))
    })?;
    Ok(main_file)
}

fn run_init_command(args: &[String]) {
    let parsed = match parse_init_command_args(args) {
        Ok(parsed) => parsed,
        Err(message) => {
            eprintln!("{message}");
            process::exit(2);
        }
    };

    let target_dir = std::path::Path::new(parsed.target_dir);
    let main_file = match initialize_project_scaffold(target_dir, parsed.force) {
        Ok(path) => path,
        Err(ScaffoldError::Usage(message)) => {
            eprintln!("{message}");
            process::exit(2);
        }
        Err(ScaffoldError::Io(message)) => {
            eprintln!("{message}");
            process::exit(1);
        }
    };

    println!("initialized dyn project at {}", target_dir.display());
    println!("created {}", main_file.display());
    println!("next: cargo run -- run {}", target_dir.display());
}

fn run_new_command(args: &[String]) {
    let parsed = match parse_new_command_args(args) {
        Ok(parsed) => parsed,
        Err(message) => {
            eprintln!("{message}");
            process::exit(2);
        }
    };

    let target_dir = std::path::Path::new(parsed.target_dir);
    if target_dir.exists() && !parsed.force {
        eprintln!(
            "new target '{}' already exists; use --force or run init there",
            target_dir.display()
        );
        process::exit(2);
    }

    let main_file = match initialize_project_scaffold(target_dir, parsed.force) {
        Ok(path) => path,
        Err(ScaffoldError::Usage(message)) => {
            eprintln!("{message}");
            process::exit(2);
        }
        Err(ScaffoldError::Io(message)) => {
            eprintln!("{message}");
            process::exit(1);
        }
    };

    println!("created dyn project at {}", target_dir.display());
    println!("created {}", main_file.display());
    println!("next: cargo run -- run {}", target_dir.display());
}

fn run_fmt_command(args: &[String]) {
    let parsed = match parse_fmt_command_args(args) {
        Ok(parsed) => parsed,
        Err(message) => {
            eprintln!("{message}");
            process::exit(2);
        }
    };

    let target_dir = std::path::Path::new(parsed.target_dir);
    if !target_dir.exists() {
        eprintln!("fmt target '{}' does not exist", target_dir.display());
        process::exit(2);
    }
    if !target_dir.is_dir() {
        eprintln!("fmt target '{}' is not a directory", target_dir.display());
        process::exit(2);
    }

    let mut dyn_files = Vec::new();
    if let Err(message) = collect_dyn_files(target_dir, &mut dyn_files) {
        eprintln!("{message}");
        process::exit(1);
    }
    dyn_files.sort();
    let checked_count = dyn_files.len();

    let mut changed_paths = Vec::new();
    for path in dyn_files {
        let original = match fs::read_to_string(&path) {
            Ok(contents) => contents,
            Err(error) => {
                eprintln!("failed to read '{}': {error}", path.display());
                process::exit(1);
            }
        };
        let formatted = normalize_dyn_text(&original);
        if formatted == original {
            continue;
        }
        if parsed.check {
            changed_paths.push(path);
            continue;
        }
        if let Err(error) = fs::write(&path, formatted) {
            eprintln!("failed to write '{}': {error}", path.display());
            process::exit(1);
        }
        changed_paths.push(path);
    }

    if parsed.check {
        if changed_paths.is_empty() {
            println!("fmt check passed ({checked_count} .dyn file(s) checked)");
            return;
        }

        eprintln!(
            "fmt check failed; {} .dyn file(s) need formatting:",
            changed_paths.len()
        );
        for path in &changed_paths {
            eprintln!("  - {}", path.display());
        }
        process::exit(1);
    }

    println!(
        "formatted {} .dyn file(s) (checked {checked_count})",
        changed_paths.len()
    );
}

fn collect_dyn_files(
    dir: &std::path::Path,
    out: &mut Vec<std::path::PathBuf>,
) -> Result<(), String> {
    let entries = fs::read_dir(dir)
        .map_err(|error| format!("failed to read directory '{}': {error}", dir.display()))?;

    for entry in entries {
        let entry = entry.map_err(|error| {
            format!(
                "failed to read directory entry '{}': {error}",
                dir.display()
            )
        })?;
        let path = entry.path();
        let file_type = entry
            .file_type()
            .map_err(|error| format!("failed to inspect '{}': {error}", path.display()))?;

        if file_type.is_dir() {
            if should_skip_fmt_dir(&path) {
                continue;
            }
            collect_dyn_files(&path, out)?;
            continue;
        }

        let is_dyn = file_type.is_file()
            && path
                .extension()
                .and_then(std::ffi::OsStr::to_str)
                .is_some_and(|ext| ext == "dyn");
        if is_dyn {
            out.push(path);
        }
    }

    Ok(())
}

fn should_skip_fmt_dir(path: &std::path::Path) -> bool {
    path.file_name()
        .and_then(std::ffi::OsStr::to_str)
        .is_some_and(|name| FMT_SKIPPED_DIRS.contains(&name))
}

fn normalize_dyn_text(input: &str) -> String {
    let mut normalized = input.replace("\r\n", "\n").replace('\r', "\n");
    while normalized.ends_with('\n') {
        normalized.pop();
    }
    normalized.push('\n');
    normalized
}

fn parse_opt_level_flag(value: &str) -> Option<BuildOptLevel> {
    match value.trim().to_ascii_lowercase().as_str() {
        "0" | "o0" | "none" | "debug" => Some(BuildOptLevel::O0),
        "1" | "o1" => Some(BuildOptLevel::O1),
        "2" | "o2" | "speed" => Some(BuildOptLevel::O2),
        "3" | "o3" | "aggressive" => Some(BuildOptLevel::O3),
        "s" | "os" | "size" => Some(BuildOptLevel::Os),
        "z" | "oz" | "minsize" | "min-size" => Some(BuildOptLevel::Oz),
        _ => None,
    }
}

fn parse_opt_level_cli_arg(
    args: &[String],
    index: usize,
) -> Result<Option<(BuildOptLevel, usize)>, String> {
    let arg = args[index].as_str();
    if arg == "--opt-level" {
        if index + 1 >= args.len() {
            return Err("missing optimization level after --opt-level".to_string());
        }
        let value = args[index + 1].as_str();
        let Some(level) = parse_opt_level_flag(value) else {
            return Err(format!(
                "invalid optimization level '{}': expected 0,1,2,3,s,z,none,speed,size,aggressive",
                value
            ));
        };
        return Ok(Some((level, 2)));
    }

    if let Some(value) = arg.strip_prefix("-O") {
        let Some(level) = parse_opt_level_flag(value) else {
            return Err(format!(
                "invalid optimization flag '{arg}': expected -O0, -O1, -O2, -O3, -Os, or -Oz"
            ));
        };
        return Ok(Some((level, 1)));
    }

    if let Some(value) = arg.strip_prefix("-o:") {
        let Some(level) = parse_opt_level_flag(value) else {
            return Err(format!(
                "invalid optimization flag '{arg}': expected -o:none, -o:speed, -o:size, or -o:aggressive"
            ));
        };
        return Ok(Some((level, 1)));
    }

    Ok(None)
}

fn run_build(start_dir: &str, output: Option<&str>, opt_level: BuildOptLevel) {
    let output_path = output.map(std::path::Path::new);
    match build_project_with_opt_level(start_dir, output_path, opt_level) {
        Ok((artifact, diagnostics)) => {
            if !diagnostics.is_empty() {
                print_diagnostics_text(&diagnostics);
                process::exit(1);
            }

            println!("built executable: {}", artifact.executable_path.display());
            println!("object file: {}", artifact.object_path.display());
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_build_all(start_dir: &str, output_base: &str) {
    let base = std::path::Path::new(output_base);
    let mut built = Vec::new();
    for (level, suffix) in build_matrix_levels() {
        let output_path = derived_opt_output_path(base, suffix);
        match build_project_with_opt_level(start_dir, Some(output_path.as_path()), *level) {
            Ok((artifact, diagnostics)) => {
                if !diagnostics.is_empty() {
                    print_diagnostics_text(&diagnostics);
                    process::exit(1);
                }
                built.push((suffix, artifact));
            }
            Err(error) => {
                eprintln!("build failed for -{suffix}: {error}");
                process::exit(1);
            }
        }
    }

    for (suffix, artifact) in built {
        println!(
            "built [-{suffix}] executable: {}",
            artifact.executable_path.display()
        );
        println!(
            "built [-{suffix}] object: {}",
            artifact.object_path.display()
        );
    }
}

fn run_project(start_dir: &str, opt_level: BuildOptLevel, program_args: &[String]) {
    match build_project_with_opt_level(start_dir, None, opt_level) {
        Ok((artifact, diagnostics)) => {
            if !diagnostics.is_empty() {
                print_diagnostics_text(&diagnostics);
                process::exit(1);
            }

            let status = Command::new(&artifact.executable_path)
                .args(program_args)
                .status()
                .unwrap_or_else(|error| {
                    eprintln!("failed to run executable: {error}");
                    process::exit(1);
                });

            match status.code() {
                Some(code) => process::exit(code),
                None => process::exit(1),
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_build_json(start_dir: &str, output: Option<&str>, opt_level: BuildOptLevel) {
    let output_path = output.map(std::path::Path::new);
    match build_project_with_opt_level(start_dir, output_path, opt_level) {
        Ok((artifact, diagnostics)) => {
            println!("{{");
            println!(
                "  \"executable\": \"{}\",",
                json_escape(&artifact.executable_path.display().to_string())
            );
            println!(
                "  \"object\": \"{}\",",
                json_escape(&artifact.object_path.display().to_string())
            );
            print_diagnostics_json(&diagnostics);
            println!("}}");
            if !diagnostics.is_empty() {
                process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn run_build_all_json(start_dir: &str, output_base: &str) {
    let base = std::path::Path::new(output_base);
    println!("{{");
    println!("  \"builds\": [");

    for (index, (level, suffix)) in build_matrix_levels().iter().enumerate() {
        let output_path = derived_opt_output_path(base, suffix);
        let (artifact, diagnostics) =
            match build_project_with_opt_level(start_dir, Some(output_path.as_path()), *level) {
                Ok(result) => result,
                Err(error) => {
                    eprintln!("build failed for -{suffix}: {error}");
                    process::exit(1);
                }
            };

        println!("    {{");
        println!("      \"opt_level\": \"{suffix}\",");
        println!(
            "      \"executable\": \"{}\",",
            json_escape(&artifact.executable_path.display().to_string())
        );
        println!(
            "      \"object\": \"{}\",",
            json_escape(&artifact.object_path.display().to_string())
        );
        print_diagnostics_json_inline(&diagnostics, 6);
        print!("    }}");
        if index + 1 != build_matrix_levels().len() {
            println!(",");
        } else {
            println!();
        }

        if !diagnostics.is_empty() {
            println!("  ]");
            println!("}}");
            process::exit(1);
        }
    }

    println!("  ]");
    println!("}}");
}

fn build_matrix_levels() -> &'static [(BuildOptLevel, &'static str)] {
    &[
        (BuildOptLevel::O0, "O0"),
        (BuildOptLevel::O1, "O1"),
        (BuildOptLevel::O2, "O2"),
        (BuildOptLevel::O3, "O3"),
        (BuildOptLevel::Os, "Os"),
        (BuildOptLevel::Oz, "Oz"),
    ]
}

fn derived_opt_output_path(base: &std::path::Path, suffix: &str) -> std::path::PathBuf {
    let file_name = base
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| "a.out".to_string());

    let new_name = if let Some(dot_idx) = file_name.rfind('.') {
        let (stem, ext_with_dot) = file_name.split_at(dot_idx);
        if stem.is_empty() {
            format!("{file_name}.{suffix}")
        } else {
            format!("{stem}.{suffix}{ext_with_dot}")
        }
    } else {
        format!("{file_name}.{suffix}")
    };

    match base.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.join(new_name),
        _ => std::path::PathBuf::from(new_name),
    }
}

fn print_diagnostics_text(diagnostics: &[Diagnostic]) {
    eprintln!("\nDiagnostics:");
    for diagnostic in diagnostics {
        eprintln!("  - {diagnostic}");
        let has_primary = diagnostic.labels.iter().any(|label| label.is_primary);
        for (index, label) in diagnostic.labels.iter().enumerate() {
            let is_primary = label.is_primary || (!has_primary && index == 0);
            let tag = if is_primary { "at" } else { "related" };
            if let Some(span) = label.span {
                eprintln!(
                    "      {tag} {}:{}:{}: {}",
                    label.file_path.display(),
                    span.start_line,
                    span.start_col,
                    label.message
                );
            } else {
                eprintln!(
                    "      {tag} {}: {}",
                    label.file_path.display(),
                    label.message
                );
            }
        }
        for note in &diagnostic.notes {
            eprintln!("      note: {note}");
        }
    }
}

fn print_diagnostics_json(diagnostics: &[Diagnostic]) {
    print_diagnostics_json_with_indent(diagnostics, 2);
}

fn print_diagnostics_json_inline(diagnostics: &[Diagnostic], indent: usize) {
    print_diagnostics_json_with_indent(diagnostics, indent);
}

fn print_diagnostics_json_with_indent(diagnostics: &[Diagnostic], indent: usize) {
    let base = " ".repeat(indent);
    let item = " ".repeat(indent + 2);
    let field = " ".repeat(indent + 4);
    let label_item = " ".repeat(indent + 6);
    let label_field = " ".repeat(indent + 8);

    println!("{base}\"diagnostics\": [");
    for (diag_index, diagnostic) in diagnostics.iter().enumerate() {
        println!("{item}{{");
        println!("{field}\"code\": \"{}\",", diagnostic.code);
        println!(
            "{field}\"phase\": \"{}\",",
            json_escape(&format!("{:?}", diagnostic.phase))
        );
        println!(
            "{field}\"message\": \"{}\",",
            json_escape(&diagnostic.message)
        );
        println!("{field}\"labels\": [");
        for (label_index, label) in diagnostic.labels.iter().enumerate() {
            println!("{label_item}{{");
            println!(
                "{label_field}\"file\": \"{}\",",
                json_escape(&label.file_path.display().to_string())
            );
            println!("{label_field}\"primary\": {},", label.is_primary);
            if let Some(span) = label.span {
                println!(
                    "{label_field}\"span\": {{\"start_line\": {}, \"start_col\": {}, \"end_line\": {}, \"end_col\": {}}},",
                    span.start_line, span.start_col, span.end_line, span.end_col
                );
            } else {
                println!("{label_field}\"span\": null,");
            }
            println!(
                "{label_field}\"message\": \"{}\"",
                json_escape(&label.message)
            );
            print!("{label_item}}}");
            if label_index + 1 != diagnostic.labels.len() {
                println!(",");
            } else {
                println!();
            }
        }
        println!("{field}]");
        print!("{item}}}");
        if diag_index + 1 != diagnostics.len() {
            println!(",");
        } else {
            println!();
        }
    }
    println!("{base}]");
}

fn print_lex_session_json(
    files: &[dyn_compiler::compiler::pipeline::LexedFile],
    diagnostics: &[Diagnostic],
) {
    println!("{{");
    println!("  \"files\": [");
    for (file_index, file) in files.iter().enumerate() {
        println!("    {{");
        println!("      \"module_id\": {},", file.module_id.0);
        println!(
            "      \"file_path\": \"{}\",",
            json_escape(&file.file_path.display().to_string())
        );
        println!("      \"tokens\": [");
        for (token_index, token) in file.tokens.iter().enumerate() {
            println!("        {{");
            println!(
                "          \"kind\": \"{}\",",
                json_escape(&format!("{:?}", token.kind))
            );
            println!("          \"lexeme\": \"{}\",", json_escape(&token.lexeme));
            println!(
                "          \"span\": {{\"line\": {}, \"col\": {}, \"end_line\": {}, \"end_col\": {}}}",
                token.span.start_line, token.span.start_col, token.span.end_line, token.span.end_col
            );
            print!("        }}");
            if token_index + 1 != file.tokens.len() {
                println!(",");
            } else {
                println!();
            }
        }
        println!("      ]");
        print!("    }}");
        if file_index + 1 != files.len() {
            println!(",");
        } else {
            println!();
        }
    }
    println!("  ],");
    print_diagnostics_json(diagnostics);
    println!("}}");
}

fn json_escape(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_init_command_args_defaults_to_current_directory() {
        let args = Vec::<String>::new();
        assert_eq!(
            parse_init_command_args(&args),
            Ok(InitCommandArgs {
                target_dir: ".",
                force: false,
            })
        );
    }

    #[test]
    fn parse_init_command_args_accepts_path_and_force_any_order() {
        let args = vec!["project".to_string(), "--force".to_string()];
        assert_eq!(
            parse_init_command_args(&args),
            Ok(InitCommandArgs {
                target_dir: "project",
                force: true,
            })
        );

        let args = vec!["--force".to_string(), "project".to_string()];
        assert_eq!(
            parse_init_command_args(&args),
            Ok(InitCommandArgs {
                target_dir: "project",
                force: true,
            })
        );
    }

    #[test]
    fn parse_init_command_args_rejects_unknown_flags() {
        let args = vec!["--json".to_string()];
        assert!(parse_init_command_args(&args).is_err());
    }

    #[test]
    fn parse_init_command_args_rejects_multiple_paths() {
        let args = vec!["a".to_string(), "b".to_string()];
        assert!(parse_init_command_args(&args).is_err());
    }

    #[test]
    fn parse_new_command_args_requires_target_directory() {
        let args = Vec::<String>::new();
        assert!(parse_new_command_args(&args).is_err());
    }

    #[test]
    fn parse_new_command_args_accepts_target_and_force() {
        let args = vec!["app".to_string(), "--force".to_string()];
        assert_eq!(
            parse_new_command_args(&args),
            Ok(NewCommandArgs {
                target_dir: "app",
                force: true,
            })
        );
    }

    #[test]
    fn parse_fmt_command_args_defaults_and_check_flag() {
        let args = Vec::<String>::new();
        assert_eq!(
            parse_fmt_command_args(&args),
            Ok(FmtCommandArgs {
                target_dir: ".",
                check: false,
            })
        );

        let args = vec!["--check".to_string(), "demo".to_string()];
        assert_eq!(
            parse_fmt_command_args(&args),
            Ok(FmtCommandArgs {
                target_dir: "demo",
                check: true,
            })
        );
    }

    #[test]
    fn parse_fmt_command_args_rejects_unknown_flags() {
        let args = vec!["--force".to_string()];
        assert!(parse_fmt_command_args(&args).is_err());
    }

    #[test]
    fn normalize_dyn_text_normalizes_line_endings_and_trailing_newline() {
        assert_eq!(
            normalize_dyn_text("module main\r\nmain := () i32 => 0\r\n"),
            "module main\nmain := () i32 => 0\n"
        );
        assert_eq!(normalize_dyn_text("module main"), "module main\n");
        assert_eq!(normalize_dyn_text("module main\n\n"), "module main\n");
    }

    #[test]
    fn parse_opt_level_flag_recognizes_numeric_levels() {
        assert_eq!(parse_opt_level_flag("0"), Some(BuildOptLevel::O0));
        assert_eq!(parse_opt_level_flag("1"), Some(BuildOptLevel::O1));
        assert_eq!(parse_opt_level_flag("2"), Some(BuildOptLevel::O2));
        assert_eq!(parse_opt_level_flag("3"), Some(BuildOptLevel::O3));
        assert_eq!(parse_opt_level_flag("o2"), Some(BuildOptLevel::O2));
        assert_eq!(parse_opt_level_flag("none"), Some(BuildOptLevel::O0));
        assert_eq!(parse_opt_level_flag("speed"), Some(BuildOptLevel::O2));
        assert_eq!(parse_opt_level_flag("size"), Some(BuildOptLevel::Os));
        assert_eq!(parse_opt_level_flag("aggressive"), Some(BuildOptLevel::O3));
        assert_eq!(parse_opt_level_flag("s"), Some(BuildOptLevel::Os));
        assert_eq!(parse_opt_level_flag("z"), Some(BuildOptLevel::Oz));
        assert_eq!(parse_opt_level_flag("x"), None);
    }

    #[test]
    fn parse_opt_level_cli_arg_accepts_short_and_long_forms() {
        let args = vec!["--opt-level".to_string(), "2".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::O2, 2)))
        );

        let args = vec!["-O3".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::O3, 1)))
        );

        let args = vec!["-Os".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::Os, 1)))
        );

        let args = vec!["--opt-level".to_string(), "z".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::Oz, 2)))
        );

        let args = vec!["-o:speed".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::O2, 1)))
        );

        let args = vec!["-o:size".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::Os, 1)))
        );

        let args = vec!["-o:aggressive".to_string()];
        assert_eq!(
            parse_opt_level_cli_arg(&args, 0),
            Ok(Some((BuildOptLevel::O3, 1)))
        );
    }

    #[test]
    fn parse_opt_level_cli_arg_rejects_invalid_forms() {
        let args = vec!["--opt-level".to_string()];
        assert!(parse_opt_level_cli_arg(&args, 0).is_err());

        let args = vec!["-Ox".to_string()];
        assert!(parse_opt_level_cli_arg(&args, 0).is_err());

        let args = vec!["-o:unknown".to_string()];
        assert!(parse_opt_level_cli_arg(&args, 0).is_err());
    }

    #[test]
    fn derived_opt_output_path_inserts_suffix_before_extension() {
        let path = derived_opt_output_path(std::path::Path::new("bin/app.exe"), "O2");
        assert_eq!(path, std::path::Path::new("bin/app.O2.exe"));
    }

    #[test]
    fn derived_opt_output_path_appends_suffix_without_extension() {
        let path = derived_opt_output_path(std::path::Path::new("bin/app"), "O3");
        assert_eq!(path, std::path::Path::new("bin/app.O3"));
    }

    #[test]
    fn build_matrix_levels_includes_size_optimized_levels() {
        let levels = build_matrix_levels();
        assert!(levels
            .iter()
            .any(|(level, suffix)| *level == BuildOptLevel::Os && *suffix == "Os"));
        assert!(levels
            .iter()
            .any(|(level, suffix)| *level == BuildOptLevel::Oz && *suffix == "Oz"));
    }
}
