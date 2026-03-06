use std::env;
use std::process;

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
                "usage: cargo run -- [resolve|lex|parse|analyze|hir|mir|build] [start_directory] [--json|--ast|-o output|-O0|-O1|-O2|-O3|--opt-level 0..3]"
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
                eprintln!("\nDiagnostics:");
                for diagnostic in graph.diagnostics {
                    eprintln!("  - {diagnostic}");
                }
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
                eprintln!("\nDiagnostics:");
                for diagnostic in session.diagnostics {
                    eprintln!("  - {diagnostic}");
                }
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
                eprintln!("\nDiagnostics:");
                for diagnostic in session.diagnostics {
                    eprintln!("  - {diagnostic}");
                }
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
                eprintln!("\nDiagnostics:");
                for diagnostic in session.diagnostics {
                    eprintln!("  - {diagnostic}");
                }
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
                eprintln!("\nDiagnostics:");
                for diagnostic in sema.diagnostics {
                    eprintln!("  - {diagnostic}");
                }
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
    let mut index = 0usize;

    while index < args.len() {
        let arg = args[index].as_str();
        match arg {
            "--json" => {
                json = true;
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
            "--opt-level" => {
                if index + 1 >= args.len() {
                    eprintln!("missing optimization level after --opt-level");
                    process::exit(2);
                }
                let Some(level) = parse_opt_level_flag(args[index + 1].as_str()) else {
                    eprintln!(
                        "invalid optimization level '{}': expected 0,1,2,3",
                        args[index + 1]
                    );
                    process::exit(2);
                };
                opt_level = level;
                index += 2;
            }
            _ if arg.starts_with("-O") => {
                let Some(level) = parse_opt_level_flag(&arg[2..]) else {
                    eprintln!("invalid optimization flag '{arg}': expected -O0, -O1, -O2, or -O3");
                    process::exit(2);
                };
                opt_level = level;
                index += 1;
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
    if json {
        run_build_json(dir, output, opt_level);
    } else {
        run_build(dir, output, opt_level);
    }
}

fn parse_opt_level_flag(value: &str) -> Option<BuildOptLevel> {
    match value {
        "0" => Some(BuildOptLevel::O0),
        "1" => Some(BuildOptLevel::O1),
        "2" => Some(BuildOptLevel::O2),
        "3" => Some(BuildOptLevel::O3),
        _ => None,
    }
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

fn print_diagnostics_text(diagnostics: &[Diagnostic]) {
    eprintln!("\nDiagnostics:");
    for diagnostic in diagnostics {
        eprintln!("  - {diagnostic}");
    }
}

fn print_diagnostics_json(diagnostics: &[Diagnostic]) {
    println!("  \"diagnostics\": [");
    for (diag_index, diagnostic) in diagnostics.iter().enumerate() {
        println!("    {{");
        println!("      \"code\": \"{}\",", diagnostic.code);
        println!(
            "      \"phase\": \"{}\",",
            json_escape(&format!("{:?}", diagnostic.phase))
        );
        println!(
            "      \"message\": \"{}\",",
            json_escape(&diagnostic.message)
        );
        println!("      \"labels\": [");
        for (label_index, label) in diagnostic.labels.iter().enumerate() {
            println!("        {{");
            println!(
                "          \"file\": \"{}\",",
                json_escape(&label.file_path.display().to_string())
            );
            println!("          \"primary\": {},", label.is_primary);
            if let Some(span) = label.span {
                println!(
                    "          \"span\": {{\"start_line\": {}, \"start_col\": {}, \"end_line\": {}, \"end_col\": {}}},",
                    span.start_line, span.start_col, span.end_line, span.end_col
                );
            } else {
                println!("          \"span\": null,");
            }
            println!("          \"message\": \"{}\"", json_escape(&label.message));
            print!("        }}");
            if label_index + 1 != diagnostic.labels.len() {
                println!(",");
            } else {
                println!();
            }
        }
        println!("      ]");
        print!("    }}");
        if diag_index + 1 != diagnostics.len() {
            println!(",");
        } else {
            println!();
        }
    }
    println!("  ]");
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
