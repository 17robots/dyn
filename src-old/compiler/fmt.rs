//! AST-based Dyn source code formatter.
//!
//! Produces canonical, consistently-indented output from a parsed [`AstFile`].
//! The entry point is [`format_ast`].

use crate::compiler::ast::*;

const INDENT: &str = "    ";

// ── public entry point ────────────────────────────────────────────────────────

/// Format a parsed [`AstFile`] into canonical Dyn source.
///
/// Returns `None` if the file has no module declaration (parse error).
pub fn format_ast(file: &AstFile) -> String {
    let mut f = Formatter::new();
    f.fmt_file(file);
    f.finish()
}

// ── formatter state ───────────────────────────────────────────────────────────

struct Formatter {
    out: String,
    indent: usize,
}

impl Formatter {
    fn new() -> Self {
        Self {
            out: String::with_capacity(256),
            indent: 0,
        }
    }

    fn finish(mut self) -> String {
        // Ensure exactly one trailing newline.
        while self.out.ends_with('\n') {
            self.out.pop();
        }
        self.out.push('\n');
        self.out
    }

    // ── output helpers ────────────────────────────────────────────────────────

    fn write(&mut self, s: &str) {
        self.out.push_str(s);
    }

    fn newline(&mut self) {
        self.out.push('\n');
    }

    fn blank_line(&mut self) {
        // Avoid double-blank lines.
        if !self.out.ends_with("\n\n") {
            self.out.push('\n');
        }
    }

    fn indent_str(&self) -> String {
        INDENT.repeat(self.indent)
    }

    fn write_indent(&mut self) {
        let s = self.indent_str();
        self.out.push_str(&s);
    }

    fn indented<F: FnOnce(&mut Self)>(&mut self, f: F) {
        self.indent += 1;
        f(self);
        self.indent -= 1;
    }

    // ── file / items ──────────────────────────────────────────────────────────

    fn fmt_file(&mut self, file: &AstFile) {
        self.write("module ");
        self.write(&file.module_decl.name.text);
        self.newline();

        for item in &file.items {
            self.blank_line();
            self.fmt_item(item);
        }
    }

    fn fmt_item(&mut self, item: &Item) {
        match item {
            Item::Declaration(d) => self.fmt_declaration(d),
            Item::ExprStmt(e) => {
                self.write_indent();
                self.fmt_expr(e);
                self.newline();
            }
        }
    }

    // ── binding ───────────────────────────────────────────────────────────────

    fn fmt_docs(&mut self, docs: &[DocComment]) {
        for doc in docs {
            self.write_indent();
            self.write("///");
            self.write(&doc.text);
            self.newline();
        }
    }

    fn fmt_visibility(&mut self, vis: Visibility) {
        if vis == Visibility::Public {
            self.write("pub ");
        }
    }

    fn fmt_declaration(&mut self, d: &Declaration) {
        self.fmt_docs(&d.docs);
        self.write_indent();
        self.fmt_visibility(d.visibility);
        match &d.target {
            DeclTarget::Name(name) => {
                if d.modifiers.mutable {
                    self.write("mut ");
                }
                self.write(&name.text);
            }
            DeclTarget::Associated { owner, member } => {
                self.write(&owner.text);
                self.write(".");
                self.write(&member.text);
            }
            DeclTarget::Destructure(names) => {
                self.write("{");
                for (i, name) in names.iter().enumerate() {
                    if i > 0 {
                        self.write(", ");
                    }
                    if name.mutable {
                        self.write("mut ");
                    }
                    self.write(&name.name.text);
                }
                self.write("}");
            }
        }

        match &d.value {
            DeclValue::Expr(expr) => {
                if let Some(ann) = &d.annotation {
                    self.write(": ");
                    self.fmt_type_expr(ann);
                    self.write(" = ");
                } else {
                    self.write(" := ");
                }
                self.fmt_expr(expr);
            }
            DeclValue::ExternSignature(sig) => {
                self.write(" := extern ");
                self.fmt_type_expr(&sig.ty);
                if let Linkage::Extern {
                    link_name: Some(link),
                } = &d.modifiers.linkage
                {
                    self.write(" = \"");
                    self.write(link);
                    self.write("\"");
                }
            }
        }
        self.newline();
    }

    // ── type expressions ──────────────────────────────────────────────────────

    fn fmt_type_expr(&mut self, ty: &TypeExpr) {
        match &ty.kind {
            TypeExprKind::Named(ident) => self.write(&ident.text),
            TypeExprKind::Applied { callee, args } => {
                self.write(&callee.text);
                self.write("(");
                for (i, arg) in args.iter().enumerate() {
                    if i > 0 {
                        self.write(", ");
                    }
                    self.fmt_type_expr(arg);
                }
                self.write(")");
            }
            TypeExprKind::Pointer { inner, mutable } => {
                self.write("*");
                if *mutable {
                    self.write("mut ");
                }
                self.fmt_type_expr(inner);
            }
            TypeExprKind::Array { len, element } => {
                self.write("[");
                if let Some(l) = len {
                    self.fmt_expr(l);
                }
                self.write("]");
                self.fmt_type_expr(element);
            }
            TypeExprKind::Slice { element, mutable } => {
                self.write("[]");
                if *mutable {
                    self.write("mut ");
                }
                self.fmt_type_expr(element);
            }
            TypeExprKind::Optional { inner } => {
                self.write("?");
                self.fmt_type_expr(inner);
            }
            TypeExprKind::Function(fn_ty) => {
                self.write("(");
                for (i, param) in fn_ty.params.iter().enumerate() {
                    if i > 0 {
                        self.write(", ");
                    }
                    if let Some(name) = &param.name {
                        self.write(&name.text);
                        self.write(": ");
                    }
                    self.fmt_type_expr(&param.ty);
                }
                self.write(")");
                let omit_void = matches!(
                    &fn_ty.return_type.kind,
                    TypeExprKind::Named(name) if name.text == "void"
                );
                if !omit_void {
                    self.write(" ");
                    self.fmt_type_expr(&fn_ty.return_type);
                }
            }
            TypeExprKind::Errorable { ok, errors } => {
                self.fmt_type_expr(ok);
                self.write("!");
                for (i, err) in errors.iter().enumerate() {
                    if i > 0 {
                        self.write(",");
                    }
                    self.write(&err.text);
                }
            }
            TypeExprKind::Struct(s) => self.fmt_struct_type(s),
            TypeExprKind::Enum(e) => self.fmt_enum_type(e),
        }
    }

    fn fmt_struct_type(&mut self, s: &StructType) {
        if s.packed {
            self.write("packed struct {");
        } else {
            self.write("struct {");
        }
        if s.fields.is_empty() {
            self.write("}");
            return;
        }
        self.newline();
        self.indented(|f| {
            for field in &s.fields {
                f.write_indent();
                f.write(&field.name.text);
                f.write(": ");
                f.fmt_type_expr(&field.ty);
                if let Some(default) = &field.default_value {
                    f.write(" = ");
                    f.fmt_expr(default);
                }
                f.write(",");
                f.newline();
            }
        });
        self.write_indent();
        self.write("}");
    }

    fn fmt_enum_type(&mut self, e: &EnumType) {
        self.write("enum");
        if let Some(repr) = &e.repr {
            self.write("(");
            self.fmt_type_expr(repr);
            self.write(")");
        }
        self.write(" {");
        if e.variants.is_empty() && e.members.is_empty() {
            self.write("}");
            return;
        }
        self.newline();
        self.indented(|f| {
            for variant in &e.variants {
                f.write_indent();
                f.write(&variant.name.text);
                if let Some(payload) = &variant.payload {
                    f.write(": ");
                    f.fmt_type_expr(payload);
                }
                f.write(",");
                f.newline();
            }
            for member in &e.members {
                f.write_indent();
                f.write(&member.name.text);
                f.write(" := ");
                f.fmt_expr(&member.value);
                f.write(",");
                f.newline();
            }
        });
        self.write_indent();
        self.write("}");
    }

    // ── expressions ───────────────────────────────────────────────────────────

    fn fmt_expr(&mut self, expr: &Expr) {
        match &expr.kind {
            ExprKind::Literal(lit) => self.fmt_literal(lit),
            ExprKind::Ident(ident) => self.write(&ident.text),
            ExprKind::BuiltinIdent(ident) => self.write(&ident.text),

            ExprKind::Unary { op, expr } => {
                self.write(unary_op_str(*op));
                self.fmt_expr(expr);
            }

            ExprKind::Binary { op, left, right } => {
                let needs_parens = binary_needs_parens(left, *op);
                if needs_parens {
                    self.write("(");
                }
                self.fmt_expr(left);
                if needs_parens {
                    self.write(")");
                }
                self.write(" ");
                self.write(binary_op_str(*op));
                self.write(" ");
                let needs_parens = binary_needs_parens(right, *op);
                if needs_parens {
                    self.write("(");
                }
                self.fmt_expr(right);
                if needs_parens {
                    self.write(")");
                }
            }

            ExprKind::Call(call) => self.fmt_call(call),

            ExprKind::FieldAccess { base, field } => {
                self.fmt_expr(base);
                self.write(".");
                self.write(&field.text);
            }

            ExprKind::DerefAccess { base } => {
                self.fmt_expr(base);
                self.write(".*");
            }

            ExprKind::Index { base, index } => {
                self.fmt_expr(base);
                self.write("[");
                self.fmt_expr(index);
                self.write("]");
            }

            ExprKind::Slice(s) => {
                self.fmt_expr(&s.base);
                self.write("[");
                if let Some(start) = &s.start {
                    self.fmt_expr(start);
                }
                if s.inclusive {
                    self.write("..=");
                } else {
                    self.write("..");
                }
                if let Some(end) = &s.end {
                    self.fmt_expr(end);
                }
                self.write("]");
            }

            ExprKind::Block(block) => self.fmt_block(block),

            ExprKind::If(if_expr) => self.fmt_if(if_expr),

            ExprKind::Match(m) => self.fmt_match(m),

            ExprKind::For(f) => self.fmt_for(f),

            ExprKind::Break(b) => {
                self.write("break");
                if let Some(label) = &b.label {
                    self.write(" :");
                    self.write(&label.name.text);
                }
                if let Some(value) = &b.value {
                    self.write(" ");
                    self.fmt_expr(value);
                }
            }

            ExprKind::Continue { label } => {
                self.write("continue");
                if let Some(label) = label {
                    self.write(" :");
                    self.write(&label.name.text);
                }
            }

            ExprKind::Return { value } => {
                self.write("return");
                if let Some(v) = value {
                    self.write(" ");
                    self.fmt_expr(v);
                }
            }

            ExprKind::Defer(d) => {
                self.write("defer");
                if let Some(binding) = &d.error_binding {
                    self.write(" |");
                    self.write(&binding.text);
                    self.write("|");
                }
                self.write(" ");
                self.fmt_expr(&d.body);
            }

            ExprKind::OptionalUnwrap { expr } => {
                self.fmt_expr(expr);
                self.write(".?");
            }

            ExprKind::ErrorUnwrap { expr } => {
                self.fmt_expr(expr);
                self.write(".!");
            }

            ExprKind::OrElse(or) => {
                self.fmt_expr(&or.value);
                self.write(" or");
                if let Some(binding) = &or.error_binding {
                    self.write(" |");
                    self.write(&binding.text);
                    self.write("|");
                }
                // If the fallback is a simple expression, keep on one line;
                // if it's a block, format normally.
                match &or.fallback.kind {
                    ExprKind::Block(_) => {
                        self.write(" ");
                        self.fmt_expr(&or.fallback);
                    }
                    _ => {
                        self.write(" ");
                        self.fmt_expr(&or.fallback);
                    }
                }
            }

            ExprKind::StructLiteral(s) => self.fmt_struct_literal(s),

            ExprKind::TypeConstruct { ty_expr, fields } => {
                self.fmt_expr(ty_expr);
                self.write("{");
                for (i, field) in fields.iter().enumerate() {
                    if i > 0 {
                        self.write(", ");
                    }
                    self.write(&field.name.text);
                    self.write(": ");
                    self.fmt_expr(&field.value);
                }
                self.write("}");
            }

            ExprKind::ArrayLiteral(elems) => {
                if elems.is_empty() {
                    self.write("[]");
                } else {
                    self.write("[");
                    for (i, e) in elems.iter().enumerate() {
                        if i > 0 {
                            self.write(", ");
                        }
                        self.fmt_expr(e);
                    }
                    self.write("]");
                }
            }

            ExprKind::TupleLiteral(elems) => {
                self.write("{");
                for (i, e) in elems.iter().enumerate() {
                    if i > 0 {
                        self.write(", ");
                    }
                    self.fmt_expr(e);
                }
                self.write("}");
            }

            ExprKind::EnumVariantConstruct(ev) => {
                if let Some(root) = &ev.root {
                    self.write(&root.text);
                    self.write(".");
                }
                self.write(&ev.variant.text);
                if !ev.payload.is_empty() {
                    self.write("(");
                    for (i, p) in ev.payload.iter().enumerate() {
                        if i > 0 {
                            self.write(", ");
                        }
                        self.fmt_expr(p);
                    }
                    self.write(")");
                }
            }

            ExprKind::Fn(fn_expr) => self.fmt_fn_expr(fn_expr),

            ExprKind::Use { path } => {
                self.write("use \"");
                self.write(path);
                self.write("\"");
            }

            ExprKind::TypeLiteral(ty) => self.fmt_type_expr(ty),

            ExprKind::Comptime { expr } => {
                self.write("comp ");
                self.fmt_expr(expr);
            }

            ExprKind::Inline { expr } => {
                self.write("inline ");
                self.fmt_expr(expr);
            }
        }
    }

    fn fmt_literal(&mut self, lit: &Literal) {
        match lit {
            Literal::Integer(s) => self.write(s),
            Literal::Float(s) => self.write(s),
            Literal::String(s) => {
                self.write("\"");
                self.write(s);
                self.write("\"");
            }
            Literal::Char(c) => {
                self.write("'");
                self.out.push(*c);
                self.write("'");
            }
            Literal::Bool(b) => self.write(if *b { "true" } else { "false" }),
            Literal::Null => self.write("null"),
        }
    }

    fn fmt_call(&mut self, call: &CallExpr) {
        self.fmt_expr(&call.callee);
        self.write("(");
        for (i, arg) in call.args.iter().enumerate() {
            if i > 0 {
                self.write(", ");
            }
            if let Some(name) = &arg.name {
                self.write(&name.text);
                self.write(": ");
            }
            self.fmt_expr(&arg.value);
        }
        self.write(")");
    }

    fn fmt_fn_expr(&mut self, fn_expr: &FnExpr) {
        self.write("(");
        for (i, param) in fn_expr.params.iter().enumerate() {
            if i > 0 {
                self.write(", ");
            }
            if param.comp {
                self.write("comp ");
            }
            self.write(&param.name.text);
            if let Some(ty) = &param.ty {
                self.write(": ");
                self.fmt_type_expr(ty);
            }
            if let Some(default) = &param.default_value {
                self.write(" = ");
                self.fmt_expr(default);
            }
        }
        self.write(")");
        if let Some(ret) = &fn_expr.return_type {
            self.write(" ");
            self.fmt_type_expr(ret);
        }
        match &fn_expr.body {
            FnBody::ArrowExpr(e) => {
                self.write(" => ");
                self.fmt_expr(e);
            }
            FnBody::Block(b) => {
                self.write(" ");
                self.fmt_block(b);
            }
        }
    }

    fn fmt_block(&mut self, block: &BlockExpr) {
        if let Some(label) = &block.label {
            self.write(&label.name.text);
            self.write(": ");
        }
        self.write("{");
        if block.statements.is_empty() && block.tail_expr.is_none() {
            self.write("}");
            return;
        }
        self.newline();
        self.indented(|f| {
            for stmt in &block.statements {
                f.fmt_stmt(stmt);
            }
            if let Some(tail) = &block.tail_expr {
                f.write_indent();
                f.fmt_expr(tail);
                f.newline();
            }
        });
        self.write_indent();
        self.write("}");
    }

    fn fmt_stmt(&mut self, stmt: &Stmt) {
        match stmt {
            Stmt::Declaration(d) => self.fmt_declaration(d),
            Stmt::Assignment(assign) => {
                self.write_indent();
                self.fmt_expr(&assign.target);
                self.write(" ");
                self.write(assign_op_str(assign.op));
                self.write(" ");
                self.fmt_expr(&assign.value);
                self.newline();
            }
            Stmt::Expr(e) => {
                self.write_indent();
                self.fmt_expr(e);
                self.newline();
            }
        }
    }

    fn fmt_if(&mut self, if_expr: &IfExpr) {
        self.write("if ");
        self.fmt_expr(&if_expr.condition);
        if let Some(cap) = &if_expr.capture {
            self.write(": |");
            for (i, binding) in cap.bindings.iter().enumerate() {
                if i > 0 {
                    self.write(", ");
                }
                match binding {
                    Some(name) => self.write(&name.text),
                    None => self.write("_"),
                }
            }
            self.write("|");
        }
        self.write(" ");
        self.fmt_expr(&if_expr.then_branch);
        if let Some(else_branch) = &if_expr.else_branch {
            self.write(" else ");
            self.fmt_expr(else_branch);
        }
    }

    fn fmt_match(&mut self, m: &MatchExpr) {
        self.write("match ");
        self.fmt_expr(&m.scrutinee);
        self.write(" {");
        self.newline();
        self.indented(|f| {
            for arm in &m.arms {
                f.write_indent();
                f.fmt_pattern(&arm.pattern);
                f.write(": ");
                // Arm value: if it's a block, format inline; otherwise one line.
                f.fmt_expr(&arm.value);
                f.write(",");
                f.newline();
            }
        });
        self.write_indent();
        self.write("}");
    }

    fn fmt_pattern(&mut self, pattern: &Pattern) {
        match &pattern.kind {
            PatternKind::Wildcard => self.write("_"),
            PatternKind::Literal(lit) => match lit {
                PatternLiteral::Integer(s) => self.write(s),
                PatternLiteral::Float(s) => self.write(s),
                PatternLiteral::String(s) => {
                    self.write("\"");
                    self.write(s);
                    self.write("\"");
                }
                PatternLiteral::Char(c) => {
                    self.write("'");
                    self.out.push(*c);
                    self.write("'");
                }
                PatternLiteral::Bool(b) => self.write(if *b { "true" } else { "false" }),
                PatternLiteral::Null => self.write("null"),
            },
            PatternKind::IdentBind(ident) => self.write(&ident.text),
            PatternKind::Range {
                start,
                end,
                inclusive,
            } => {
                self.fmt_pattern(start);
                if *inclusive {
                    self.write("..=");
                } else {
                    self.write("..");
                }
                self.fmt_pattern(end);
            }
            PatternKind::EnumVariant {
                root,
                variant,
                bindings,
            } => {
                if let Some(root) = root {
                    self.write(&root.text);
                    self.write(".");
                } else {
                    self.write(".");
                }
                self.write(&variant.text);
                if !bindings.is_empty() {
                    self.write(": |");
                    for (i, b) in bindings.iter().enumerate() {
                        if i > 0 {
                            self.write(", ");
                        }
                        self.write(&b.text);
                    }
                    self.write("|");
                }
            }
            PatternKind::Typed { pattern, ty } => {
                self.fmt_pattern(pattern);
                self.write(": ");
                self.fmt_type_expr(ty);
            }
            PatternKind::TypeLiteral(ty) => self.fmt_type_expr(ty),
        }
    }

    fn fmt_for(&mut self, for_expr: &ForExpr) {
        match for_expr {
            ForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => {
                self.write("for ");
                self.fmt_expr(start);
                if *inclusive {
                    self.write("..=");
                } else {
                    self.write("..");
                }
                self.fmt_expr(end);
                if let Some(b) = binding {
                    self.write(": |");
                    self.write(&b.text);
                    self.write("|");
                }
                self.write(" ");
                self.fmt_expr(body);
            }
            ForExpr::Iterate {
                iterable,
                binding,
                body,
            } => {
                self.write("for ");
                self.fmt_expr(iterable);
                if let Some(b) = binding {
                    self.write(": |");
                    self.write(&b.text);
                    self.write("|");
                }
                self.write(" ");
                self.fmt_expr(body);
            }
            ForExpr::WhileLike { condition, body } => {
                self.write("for ");
                self.fmt_expr(condition);
                self.write(": ");
                self.fmt_expr(body);
            }
            ForExpr::Infinite { body } => {
                self.write("for ");
                self.fmt_expr(body);
            }
        }
    }

    fn fmt_struct_literal(&mut self, s: &StructLiteralExpr) {
        if let Some(root) = &s.root_type {
            self.write(&root.text);
        }
        self.write(".{");
        if s.fields.is_empty() {
            self.write("}");
            return;
        }
        // Inline if there's only one short field; otherwise multi-line.
        let is_short = s.fields.len() <= 2 && s.fields.iter().all(|f| is_simple_expr(&f.value));
        if is_short {
            self.write(" ");
            for (i, field) in s.fields.iter().enumerate() {
                if i > 0 {
                    self.write(", ");
                }
                self.write(&field.name.text);
                self.write(": ");
                self.fmt_expr(&field.value);
            }
            self.write(" }");
        } else {
            self.newline();
            self.indented(|f| {
                for field in &s.fields {
                    f.write_indent();
                    f.write(&field.name.text);
                    f.write(": ");
                    f.fmt_expr(&field.value);
                    f.write(",");
                    f.newline();
                }
            });
            self.write_indent();
            self.write("}");
        }
    }
}

// ── helpers ───────────────────────────────────────────────────────────────────

fn unary_op_str(op: UnaryOp) -> &'static str {
    match op {
        UnaryOp::Neg => "-",
        UnaryOp::Not => "!",
        UnaryOp::BitNot => "~",
        UnaryOp::Ref => "&",
        UnaryOp::RefMut => "&mut ",
    }
}

fn binary_op_str(op: BinaryOp) -> &'static str {
    match op {
        BinaryOp::Add => "+",
        BinaryOp::Sub => "-",
        BinaryOp::Mul => "*",
        BinaryOp::Div => "/",
        BinaryOp::Mod => "%",
        BinaryOp::Eq => "==",
        BinaryOp::Ne => "!=",
        BinaryOp::Lt => "<",
        BinaryOp::Le => "<=",
        BinaryOp::Gt => ">",
        BinaryOp::Ge => ">=",
        BinaryOp::LogicalAnd => "&&",
        BinaryOp::LogicalOr => "||",
        BinaryOp::BitAnd => "&",
        BinaryOp::BitOr => "|",
        BinaryOp::BitXor => "^",
        BinaryOp::Shl => "<<",
        BinaryOp::Shr => ">>",
        BinaryOp::Range => "..",
        BinaryOp::RangeInclusive => "..=",
    }
}

fn assign_op_str(op: AssignOp) -> &'static str {
    match op {
        AssignOp::Assign => "=",
        AssignOp::AddAssign => "+=",
        AssignOp::SubAssign => "-=",
        AssignOp::MulAssign => "*=",
        AssignOp::DivAssign => "/=",
        AssignOp::ModAssign => "%=",
        AssignOp::BitAndAssign => "&=",
        AssignOp::BitOrAssign => "|=",
        AssignOp::BitXorAssign => "^=",
        AssignOp::ShlAssign => "<<=",
        AssignOp::ShrAssign => ">>=",
    }
}

/// Whether `expr` in a binary context might need wrapping parens to preserve
/// the correct precedence when pretty-printed.
fn binary_needs_parens(expr: &Expr, _parent_op: BinaryOp) -> bool {
    // Only wrap inner binaries with lower-precedence ops — keep it conservative.
    matches!(expr.kind, ExprKind::Binary { .. })
}

/// True for expressions simple enough to be kept on one line.
fn is_simple_expr(expr: &Expr) -> bool {
    matches!(
        &expr.kind,
        ExprKind::Literal(_)
            | ExprKind::Ident(_)
            | ExprKind::BuiltinIdent(_)
            | ExprKind::EnumVariantConstruct(_)
    )
}
