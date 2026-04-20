use std::path::PathBuf;

use crate::compiler::ast::*;
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase, SourceSpan};
use crate::compiler::lexer::{Delimiter, Keyword, Operator, Token, TokenKind};

pub struct ParseOutput {
    pub ast: Option<AstFile>,
    pub diagnostics: Vec<crate::compiler::diagnostics::Diagnostic>,
}

pub fn parse_file(file_path: PathBuf, tokens: &[Token]) -> ParseOutput {
    Parser::new(file_path, tokens).parse_file()
}

struct Parser<'a> {
    tokens: &'a [Token],
    index: usize,
    diagnostics: Vec<crate::compiler::diagnostics::Diagnostic>,
    file_path: PathBuf,
    disallow_ident_struct_literal: bool,
    disallow_labeled_block: bool,
}

impl<'a> Parser<'a> {
    fn new(file_path: PathBuf, tokens: &'a [Token]) -> Self {
        Self {
            tokens,
            index: 0,
            diagnostics: Vec::new(),
            file_path,
            disallow_ident_struct_literal: false,
            disallow_labeled_block: false,
        }
    }

    fn parse_file(mut self) -> ParseOutput {
        let module_decl = self.parse_module_decl();
        let mut items = Vec::new();

        while !self.is_eof() {
            if self.peek_kind(TokenKind::Eof) {
                break;
            }
            if self.peek_kind(TokenKind::DocComment) || self.looks_like_top_level_item() {
                if let Some(item) = self.parse_item(true) {
                    items.push(item);
                } else {
                    self.sync_to_top_level_boundary();
                }
                continue;
            }

            if self.starts_expr() {
                let start = self.current_span();
                let span = self.parse_expr(0).map(|expr| expr.span).unwrap_or(start);
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "top-level statements are not allowed",
                    span,
                    "move this expression into a declaration or function body",
                );
                self.match_delimiter(Delimiter::Semicolon);
                continue;
            }

            self.sync_to_top_level_boundary();
        }

        let ast = module_decl.map(|module_decl| AstFile {
            span: module_decl.span,
            module_decl,
            items,
        });

        ParseOutput {
            ast,
            diagnostics: self.diagnostics,
        }
    }

    fn parse_module_decl(&mut self) -> Option<ModuleDecl> {
        while self.peek_kind(TokenKind::DocComment) {
            self.advance();
        }

        let start = self.current_span();
        if !self.match_keyword(Keyword::Module) {
            return Some(ModuleDecl {
                name: Ident {
                    text: "main".to_string(),
                    span: start,
                },
                span: start,
            });
        }

        let name = self.parse_ident()?;
        Some(ModuleDecl {
            span: merge_span(start, name.span),
            name,
        })
    }

    fn parse_item(&mut self, allow_extern_bindings: bool) -> Option<Item> {
        let docs = self.parse_doc_comments();
        let visibility = if self.match_keyword(Keyword::Pub) {
            Visibility::Public
        } else {
            Visibility::Private
        };
        let mut modifiers = self.parse_declaration_modifiers();

        if self.match_keyword(Keyword::Extern) {
            let span = self.prev_span();
            self.report_parser_error(
                DiagnosticCode::E3001,
                "extern declarations must use binding syntax",
                span,
                "use `name := extern (args) ret`",
            );

            let _ = self.parse_ident();
            if self.match_operator(Operator::Colon) {
                let _ = self.parse_type_expr();
                if self.match_operator(Operator::Equal) {
                    let _ = self.parse_string_literal();
                }
            }
            return None;
        }

        if self.looks_like_destructure_binding() {
            return self.parse_destructure_declaration(docs, visibility, modifiers);
        }

        let start = self.current_span();
        let name = self.parse_ident()?;

        // `TypeName.member := expr` or `TypeName.member: Type = expr`
        if !modifiers.mutable && self.match_operator(Operator::Dot) {
            let member = self.parse_ident()?;
            let annotation = if self.match_operator(Operator::Colon) {
                if self.peek_operator(Operator::Equal) {
                    // `:=` infer form — consume the `=`
                    self.advance();
                    None
                } else {
                    // `: Type = expr` typed form
                    let ty = self.parse_type_expr()?;
                    self.expect_operator(Operator::Equal, "expected '=' after type annotation");
                    Some(ty)
                }
            } else {
                self.expect_operator(Operator::Equal, "expected ':=' or '=' after member name");
                None
            };
            let value = DeclValue::Expr(self.parse_expr(0)?);
            let end = match &value {
                DeclValue::Expr(expr) => expr.span,
                DeclValue::ExternSignature(sig) => sig.ty.span,
            };
            return Some(Item::Declaration(Box::new(Declaration {
                docs,
                visibility,
                modifiers,
                target: DeclTarget::Associated {
                    owner: name,
                    member,
                },
                annotation,
                span: merge_span(start, end),
                value,
            })));
        }

        if self.match_operator(Operator::Colon) {
            if self.match_operator(Operator::Equal) {
                if allow_extern_bindings && self.match_keyword(Keyword::Extern) {
                    if modifiers.mutable {
                        self.report_parser_error(
                            DiagnosticCode::E3001,
                            "extern bindings cannot be mutable",
                            start,
                        "remove `mut` from extern function declaration",
                    );
                    }
                    let (ty, link_name, end) = self.parse_extern_binding_signature()?;
                    let mut modifiers = modifiers;
                    modifiers.linkage = Linkage::Extern { link_name };
                    return Some(Item::Declaration(Box::new(Declaration {
                        docs,
                        visibility,
                        modifiers,
                        target: DeclTarget::Name(name),
                        annotation: None,
                        value: DeclValue::ExternSignature(ExternSignature {
                            ty,
                            link_name: None,
                        }),
                        span: merge_span(start, end),
                    })));
                }
                let value = self.parse_declaration_value_expr(&mut modifiers)?;
                return Some(Item::Declaration(Box::new(Declaration {
                    docs,
                    visibility,
                    modifiers,
                    target: DeclTarget::Name(name),
                    annotation: None,
                    span: merge_span(start, value.span),
                    value: DeclValue::Expr(value),
                })));
            }

            let annotation = self.parse_type_expr()?;
            self.expect_operator(Operator::Equal, "expected '=' after typed binding");
            let value = self.parse_declaration_value_expr(&mut modifiers)?;
            return Some(Item::Declaration(Box::new(Declaration {
                docs,
                visibility,
                modifiers,
                target: DeclTarget::Name(name),
                annotation: Some(annotation),
                span: merge_span(start, value.span),
                value: DeclValue::Expr(value),
            })));
        }

        if self.match_operator(Operator::Equal) {
            if allow_extern_bindings && self.match_keyword(Keyword::Extern) {
                if modifiers.mutable {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "extern bindings cannot be mutable",
                        start,
                        "remove `mut` from extern function declaration",
                    );
                }
                let (ty, link_name, end) = self.parse_extern_binding_signature()?;
                let mut modifiers = modifiers;
                modifiers.linkage = Linkage::Extern { link_name };
                return Some(Item::Declaration(Box::new(Declaration {
                    docs,
                    visibility,
                    modifiers,
                    target: DeclTarget::Name(name),
                    annotation: None,
                    value: DeclValue::ExternSignature(ExternSignature {
                        ty,
                        link_name: None,
                    }),
                    span: merge_span(start, end),
                    })));
            }
            let value = self.parse_declaration_value_expr(&mut modifiers)?;
            return Some(Item::Declaration(Box::new(Declaration {
                docs,
                visibility,
                modifiers,
                target: DeclTarget::Name(name),
                annotation: None,
                span: merge_span(start, value.span),
                value: DeclValue::Expr(value),
            })));
        }

        None
    }

    fn parse_declaration_modifiers(&mut self) -> DeclModifiers {
        let mutable = self.match_keyword(Keyword::Mut);
        DeclModifiers {
            mutable,
            inline: false,
            linkage: Linkage::Normal,
        }
    }

    fn parse_declaration_value_expr(&mut self, modifiers: &mut DeclModifiers) -> Option<Expr> {
        if self.match_keyword(Keyword::Inline) {
            let start = self.prev_span();
            modifiers.inline = true;
            let value = self.parse_expr(100)?;
            if !matches!(value.kind, ExprKind::Fn(_)) {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "declaration modifier `inline` requires a function value",
                    merge_span(start, value.span),
                    "use `inline` only before a function declaration value",
                );
            }
            return Some(value);
        }

        if modifiers.inline {
            self.report_parser_error(
                DiagnosticCode::E3001,
                "inline declarations require an inline function value",
                self.current_span(),
                "write `:= inline (...) ...`",
            );
        }

        self.parse_expr(0)
    }

    fn parse_doc_comments(&mut self) -> Vec<DocComment> {
        let mut docs = Vec::new();
        while let Some(token) = self.current() {
            if token.kind != TokenKind::DocComment {
                break;
            }
            docs.push(DocComment {
                text: token.lexeme.clone(),
                span: token.span,
            });
            self.advance();
        }
        docs
    }

    fn parse_expr(&mut self, min_prec: u8) -> Option<Expr> {
        let mut left = self.parse_prefix_expr()?;

        loop {
            if self.match_keyword(Keyword::Or) {
                let capture = if self.match_operator(Operator::Pipe) {
                    let id = self.parse_ident();
                    self.expect_operator(Operator::Pipe, "expected '|' after or-capture");
                    id
                } else {
                    None
                };
                let fallback = self.parse_expr(1)?;
                let span = merge_span(left.span, fallback.span);
                left = Expr {
                    span,
                    kind: ExprKind::OrElse(OrElseExpr {
                        value: Box::new(left),
                        error_binding: capture,
                        fallback: Box::new(fallback),
                    }),
                };
                continue;
            }

            if self.peek_identifier_text("and") {
                let and_span = self.current_span();
                self.advance();
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "word-form `and` operator is not supported",
                    and_span,
                    "replace `and` with `&&`",
                );
                let right = self.parse_expr(31)?;
                let span = merge_span(left.span, right.span);
                left = Expr {
                    span,
                    kind: ExprKind::Binary {
                        op: BinaryOp::LogicalAnd,
                        left: Box::new(left),
                        right: Box::new(right),
                    },
                };
                continue;
            }

            let Some((op, prec, right_assoc)) = self.current_binary_op() else {
                break;
            };
            if prec < min_prec {
                break;
            }
            self.advance();
            let next_min_prec = if right_assoc { prec } else { prec + 1 };
            let right = self.parse_expr(next_min_prec)?;
            let span = merge_span(left.span, right.span);
            left = Expr {
                span,
                kind: ExprKind::Binary {
                    op,
                    left: Box::new(left),
                    right: Box::new(right),
                },
            };
        }

        Some(left)
    }

    fn parse_prefix_expr(&mut self) -> Option<Expr> {
        if self.match_keyword(Keyword::If) {
            return self.parse_if_expr();
        }
        if self.match_keyword(Keyword::Match) {
            return self.parse_match_expr();
        }
        if self.match_keyword(Keyword::For) {
            return self.parse_for_expr();
        }
        if self.match_keyword(Keyword::Extern) {
            let span = self.prev_span();
            self.report_parser_error(
                DiagnosticCode::E3001,
                "extern declarations must use binding syntax",
                span,
                "use `name := extern (args) ret`",
            );
            return None;
        }
        if self.match_keyword(Keyword::Break) {
            return Some(self.parse_break_expr());
        }
        if self.match_keyword(Keyword::Continue) {
            return Some(self.parse_continue_expr());
        }
        if self.match_keyword(Keyword::Return) {
            let start = self.prev_span();
            let value = if self.starts_expr() && self.current_starts_on_line(start.end_line) {
                self.parse_expr(0).map(Box::new)
            } else {
                None
            };
            let span = value.as_ref().map_or(start, |v| merge_span(start, v.span));
            return Some(Expr {
                span,
                kind: ExprKind::Return { value },
            });
        }
        if self.match_keyword(Keyword::Defer) {
            return self.parse_defer_expr();
        }
        if self.match_keyword(Keyword::Comp) {
            let start = self.prev_span();
            let expr = self.parse_expr(100)?;
            return Some(Expr {
                span: merge_span(start, expr.span),
                kind: ExprKind::Comptime {
                    expr: Box::new(expr),
                },
            });
        }
        if self.match_keyword(Keyword::Inline) {
            let start = self.prev_span();
            let expr = self.parse_expr(100)?;
            return Some(Expr {
                span: merge_span(start, expr.span),
                kind: ExprKind::Inline {
                    expr: Box::new(expr),
                },
            });
        }
        if self.match_keyword(Keyword::Use) {
            let start = self.prev_span();
            let path = self.parse_string_literal()?;
            return Some(Expr {
                span: merge_span(start, self.prev_span()),
                kind: ExprKind::Use { path },
            });
        }

        if self.match_keyword(Keyword::Packed) {
            let start = self.prev_span();
            if !self.match_keyword(Keyword::Struct) {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "expected 'struct' after 'packed'",
                    self.current_span(),
                    "use `packed struct { ... }`",
                );
                return None;
            }
            let ty = self.parse_struct_type(start, true)?;
            return Some(Expr {
                span: ty.span,
                kind: ExprKind::TypeLiteral(ty),
            });
        }

        if self.match_keyword(Keyword::Struct) {
            let start = self.prev_span();
            let ty = self.parse_struct_type(start, false)?;
            return Some(Expr {
                span: ty.span,
                kind: ExprKind::TypeLiteral(ty),
            });
        }

        if self.match_keyword(Keyword::Enum) {
            let start = self.prev_span();
            let ty = self.parse_enum_type(start)?;
            return Some(Expr {
                span: ty.span,
                kind: ExprKind::TypeLiteral(ty),
            });
        }

        if self.match_operator(Operator::Minus) {
            return self.parse_unary(UnaryOp::Neg);
        }
        if self.match_operator(Operator::Bang) {
            return self.parse_unary(UnaryOp::Not);
        }
        if self.match_operator(Operator::Tilde) {
            return self.parse_unary(UnaryOp::BitNot);
        }
        if self.match_operator(Operator::Ampersand) {
            if self.match_keyword(Keyword::Mut) {
                return self.parse_unary(UnaryOp::RefMut);
            }
            return self.parse_unary(UnaryOp::Ref);
        }

        self.parse_postfix_expr()
    }

    fn parse_unary(&mut self, op: UnaryOp) -> Option<Expr> {
        let start = self.prev_span();
        let expr = self.parse_expr(90)?;
        Some(Expr {
            span: merge_span(start, expr.span),
            kind: ExprKind::Unary {
                op,
                expr: Box::new(expr),
            },
        })
    }

    fn parse_postfix_expr(&mut self) -> Option<Expr> {
        let mut expr = self.parse_primary_expr()?;

        loop {
            if self.match_delimiter(Delimiter::LParen) {
                expr = self.finish_call(expr)?;
                continue;
            }
            if self.match_delimiter(Delimiter::LBracket) {
                expr = self.finish_index_or_slice(expr)?;
                continue;
            }
            if self.peek_operator(Operator::DotQuestion) && self.current_touches_expr_end(expr.span)
            {
                self.advance();
                let span = merge_span(expr.span, self.prev_span());
                expr = Expr {
                    span,
                    kind: ExprKind::OptionalUnwrap {
                        expr: Box::new(expr),
                    },
                };
                continue;
            }
            if self.peek_operator(Operator::DotBang) && self.current_touches_expr_end(expr.span) {
                self.advance();
                let span = merge_span(expr.span, self.prev_span());
                expr = Expr {
                    span,
                    kind: ExprKind::ErrorUnwrap {
                        expr: Box::new(expr),
                    },
                };
                continue;
            }
            if self.peek_operator(Operator::DotStar) && self.current_touches_expr_end(expr.span) {
                self.advance();
                let span = merge_span(expr.span, self.prev_span());
                expr = Expr {
                    span,
                    kind: ExprKind::DerefAccess {
                        base: Box::new(expr),
                    },
                };
                continue;
            }
            if self.peek_operator(Operator::Dot) && self.current_touches_expr_end(expr.span) {
                self.advance();
                if self.match_delimiter(Delimiter::LBrace) {
                    expr = self.finish_struct_literal(None, self.prev_span())?;
                    continue;
                }
                let field = self.parse_ident()?;
                let span = merge_span(expr.span, field.span);
                expr = Expr {
                    span,
                    kind: ExprKind::FieldAccess {
                        base: Box::new(expr),
                        field,
                    },
                };
                continue;
            }
            // `expr{}` or `expr{ field: val }` — construct a struct whose type is `expr`.
            // Only valid when `{` is byte-adjacent to the preceding expression (no whitespace),
            // preventing ambiguity with a following block statement on a new line.
            if self.peek_delimiter(Delimiter::LBrace)
                && self.current_touches_expr_end(expr.span)
                && !self.disallow_ident_struct_literal
            {
                let start = expr.span;
                self.advance(); // consume `{`
                let fields = self.parse_struct_literal_fields(true)?;
                let end = self.current_span();
                self.expect_delimiter(Delimiter::RBrace, "expected '}' after struct construction");
                expr = Expr {
                    span: merge_span(start, end),
                    kind: ExprKind::TypeConstruct {
                        ty_expr: Box::new(expr),
                        fields,
                    },
                };
                continue;
            }
            break;
        }

        Some(expr)
    }

    fn parse_primary_expr(&mut self) -> Option<Expr> {
        let token = self.current()?.clone();
        match token.kind {
            TokenKind::IntLiteral => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Integer(token.lexeme)),
                })
            }
            TokenKind::FloatLiteral => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Float(token.lexeme)),
                })
            }
            TokenKind::StringLiteral => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::String(string_from_lexeme(&token.lexeme))),
                })
            }
            TokenKind::CharLiteral => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Char(char_from_lexeme(&token.lexeme))),
                })
            }
            TokenKind::BoolLiteral(value) => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Bool(value)),
                })
            }
            TokenKind::NullLiteral => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::Literal(Literal::Null),
                })
            }
            TokenKind::Identifier => {
                self.advance();
                let ident = Ident {
                    text: token.lexeme.clone(),
                    span: token.span,
                };
                if !self.disallow_labeled_block
                    && self.peek_operator(Operator::Colon)
                    && (self.peek_next_kind(TokenKind::Delimiter(Delimiter::LBrace))
                        || self.peek_next_kind(TokenKind::Keyword(Keyword::For)))
                {
                    self.advance(); // consume `:`
                    if self.match_keyword(Keyword::For) {
                        let for_expr = self.parse_for_expr()?;
                        let span = merge_span(token.span, for_expr.span);
                        return Some(Expr {
                            span,
                            kind: ExprKind::Block(BlockExpr {
                                label: Some(Label {
                                    name: ident,
                                    span: token.span,
                                }),
                                statements: Vec::new(),
                                tail_expr: Some(Box::new(for_expr)),
                            }),
                        });
                    }
                    let mut block = self.parse_block_expr()?;
                    if let ExprKind::Block(ref mut block_expr) = block.kind {
                        block_expr.label = Some(Label {
                            name: ident,
                            span: token.span,
                        });
                    }
                    return Some(block);
                }
                if !self.disallow_ident_struct_literal && self.match_delimiter(Delimiter::LBrace) {
                    self.finish_struct_literal(Some(ident), token.span)
                } else {
                    Some(Expr {
                        span: token.span,
                        kind: ExprKind::Ident(ident),
                    })
                }
            }
            TokenKind::BuiltinIdentifier => {
                self.advance();
                Some(Expr {
                    span: token.span,
                    kind: ExprKind::BuiltinIdent(Ident {
                        text: token.lexeme,
                        span: token.span,
                    }),
                })
            }
            TokenKind::Delimiter(Delimiter::LParen) => {
                if self.looks_like_fn_literal() {
                    self.parse_fn_expr()
                } else {
                    self.advance();
                    let mut expr = self.parse_expr(0)?;
                    self.expect_delimiter(Delimiter::RParen, "expected ')' after expression");
                    // Extend span to include the closing ')' so that postfix operators
                    // like '.*' are recognized as touching the paren expression.
                    let close_span = self.prev_span();
                    expr.span = merge_span(expr.span, close_span);
                    Some(expr)
                }
            }
            TokenKind::Delimiter(Delimiter::LBracket) => self.parse_array_literal(),
            TokenKind::Delimiter(Delimiter::LBrace) => self.parse_brace_expr(),
            TokenKind::Operator(Operator::Dot) => {
                self.advance();
                if self.match_delimiter(Delimiter::LBrace) {
                    return self.finish_struct_literal(None, token.span);
                }
                let variant = self.parse_ident()?;
                if self.match_delimiter(Delimiter::LParen) {
                    let payload = self.parse_arg_values();
                    let end = self.prev_span();
                    return Some(Expr {
                        span: merge_span(token.span, end),
                        kind: ExprKind::EnumVariantConstruct(EnumVariantExpr {
                            root: None,
                            variant,
                            payload,
                        }),
                    });
                }
                Some(Expr {
                    span: merge_span(token.span, variant.span),
                    kind: ExprKind::EnumVariantConstruct(EnumVariantExpr {
                        root: None,
                        variant,
                        payload: Vec::new(),
                    }),
                })
            }
            _ => {
                self.report_parser_error(
                    DiagnosticCode::E3002,
                    "unexpected token in expression",
                    token.span,
                    "token cannot start an expression",
                );
                self.advance();
                None
            }
        }
    }

    fn parse_brace_expr(&mut self) -> Option<Expr> {
        if self.looks_like_tuple_literal() {
            self.parse_tuple_literal()
        } else {
            self.parse_block_expr()
        }
    }

    fn looks_like_tuple_literal(&self) -> bool {
        if !self.peek_delimiter(Delimiter::LBrace) {
            return false;
        }

        let mut brace_depth = 0usize;
        let mut paren_depth = 0usize;
        let mut bracket_depth = 0usize;
        for idx in self.index..self.tokens.len() {
            match self.tokens[idx].kind {
                TokenKind::Delimiter(Delimiter::LBrace) => brace_depth += 1,
                TokenKind::Delimiter(Delimiter::RBrace) => {
                    if brace_depth == 0 {
                        return false;
                    }
                    brace_depth -= 1;
                    if brace_depth == 0 {
                        return false;
                    }
                }
                TokenKind::Delimiter(Delimiter::LParen) => paren_depth += 1,
                TokenKind::Delimiter(Delimiter::RParen) => {
                    paren_depth = paren_depth.saturating_sub(1)
                }
                TokenKind::Delimiter(Delimiter::LBracket) => bracket_depth += 1,
                TokenKind::Delimiter(Delimiter::RBracket) => {
                    bracket_depth = bracket_depth.saturating_sub(1)
                }
                TokenKind::Delimiter(Delimiter::Comma)
                    if brace_depth == 1 && paren_depth == 0 && bracket_depth == 0 =>
                {
                    return true;
                }
                _ => {}
            }
        }

        false
    }

    fn parse_tuple_literal(&mut self) -> Option<Expr> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LBrace, "expected '{'");

        let mut elements = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            let element = self.parse_expr(0)?;
            elements.push(element);
            if !self.match_delimiter(Delimiter::Comma) {
                if self.peek_delimiter(Delimiter::RBrace) {
                    break;
                }
                if self.starts_expr() {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "expected ',' between tuple literal elements",
                        self.current_span(),
                        "insert ',' to separate tuple elements",
                    );
                    continue;
                }
                break;
            }
        }

        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBrace, "expected '}' after tuple literal");
        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::TupleLiteral(elements),
        })
    }

    fn parse_array_literal(&mut self) -> Option<Expr> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LBracket, "expected '['");

        let mut elements = Vec::new();
        while !self.peek_delimiter(Delimiter::RBracket) && !self.is_eof() {
            let element = self.parse_expr(0)?;
            elements.push(element);
            if !self.match_delimiter(Delimiter::Comma) {
                if self.peek_delimiter(Delimiter::RBracket) {
                    break;
                }
                if self.starts_expr() {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "expected ',' between array literal elements",
                        self.current_span(),
                        "insert ',' to separate array elements",
                    );
                    continue;
                }
                break;
            }
        }

        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBracket, "expected ']' after array literal");
        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::ArrayLiteral(elements),
        })
    }

    fn parse_block_expr(&mut self) -> Option<Expr> {
        let (expr, _closed) = self.parse_block_expr_with_status()?;
        Some(expr)
    }

    fn parse_block_expr_with_status(&mut self) -> Option<(Expr, bool)> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LBrace, "expected '{'");
        let mut statements = Vec::new();
        let mut tail_expr = None;

        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            if self.match_delimiter(Delimiter::Semicolon) {
                continue;
            }

            if self.looks_like_destructure_binding() {
                if let Some(Item::Declaration(decl)) =
                    self.parse_destructure_declaration(
                        vec![],
                        Visibility::Private,
                        DeclModifiers {
                            mutable: false,
                            inline: false,
                            linkage: Linkage::Normal,
                        },
                    )
                {
                    if let Some(stmt) = self.declaration_to_stmt(decl) {
                        statements.push(stmt);
                    }
                    tail_expr = None;
                    self.match_delimiter(Delimiter::Semicolon);
                    continue;
                }
            }

            if self.peek_kind(TokenKind::DocComment) || self.looks_like_local_binding() {
                if let Some(Item::Declaration(decl)) = self.parse_item(false) {
                    if let Some(stmt) = self.declaration_to_stmt(decl) {
                        statements.push(stmt);
                    }
                    tail_expr = None;
                    self.match_delimiter(Delimiter::Semicolon);
                    continue;
                }
            }

            if self.starts_assignment_stmt() {
                let before = self.index;
                if let Some(stmt) = self.parse_assignment_stmt() {
                    statements.push(stmt);
                    tail_expr = None;
                    self.match_delimiter(Delimiter::Semicolon);
                    continue;
                }
                self.index = before;
            }

            let before = self.index;
            if let Some(expr) = self.parse_expr(0) {
                statements.push(Stmt::Expr(Box::new(expr)));
                if let Some(Stmt::Expr(expr)) = statements.last() {
                    if expr_can_be_block_tail(expr) {
                        tail_expr = Some(expr.clone());
                    } else {
                        tail_expr = None;
                    }
                }
                self.match_delimiter(Delimiter::Semicolon);
            } else if self.index == before {
                self.advance();
            }
        }

        let end = self.current_span();
        let closed = self.peek_delimiter(Delimiter::RBrace);
        self.expect_delimiter(Delimiter::RBrace, "expected '}' to close block");

        if let Some(tail) = tail_expr.as_ref() {
            if matches!(statements.last(), Some(Stmt::Expr(last)) if last.span == tail.span) {
                statements.pop();
            }
        }

        Some((
            Expr {
                span: merge_span(start, end),
                kind: ExprKind::Block(BlockExpr {
                    label: None,
                    statements,
                    tail_expr,
                }),
            },
            closed,
        ))
    }

    fn parse_balanced_block_expr(&mut self) -> Option<Expr> {
        if !self.peek_delimiter(Delimiter::LBrace) {
            return self.parse_block_expr();
        }

        let start = self.current_span();
        self.advance();
        let mut depth = 1usize;
        let mut end = start;

        while !self.is_eof() {
            let span = self.current_span();
            match self.current().map(|token| &token.kind) {
                Some(TokenKind::Delimiter(Delimiter::LBrace)) => {
                    depth += 1;
                    self.advance();
                }
                Some(TokenKind::Delimiter(Delimiter::RBrace)) => {
                    depth -= 1;
                    end = span;
                    self.advance();
                    if depth == 0 {
                        break;
                    }
                }
                _ => {
                    self.advance();
                }
            }
        }

        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::Block(BlockExpr {
                label: None,
                statements: Vec::new(),
                tail_expr: None,
            }),
        })
    }

    fn parse_if_expr(&mut self) -> Option<Expr> {
        let start = self.prev_span();
        let prev_struct_literal = self.disallow_ident_struct_literal;
        self.disallow_ident_struct_literal = true;
        self.disallow_labeled_block = true;
        let condition = self.parse_expr(0)?;
        self.disallow_labeled_block = false;
        self.disallow_ident_struct_literal = prev_struct_literal;

        let capture = if self.match_operator(Operator::Colon) {
            self.expect_operator(Operator::Pipe, "expected '|' in if-capture");
            let mut bindings = Vec::new();
            loop {
                let binding = if self.peek_identifier_text("_") {
                    self.advance();
                    None
                } else {
                    self.parse_ident()
                };
                bindings.push(binding);
                if !self.match_delimiter(Delimiter::Comma) {
                    break;
                }
            }
            self.expect_operator(Operator::Pipe, "expected closing '|' in if-capture");
            Some(crate::compiler::ast::IfCapture { bindings })
        } else {
            None
        };

        let then_branch = self.parse_stmt_expr_bridge()?;
        let else_branch = if self.match_keyword(Keyword::Else) {
            let else_branch = self.parse_stmt_expr_bridge()?;
            Some(Box::new(else_branch))
        } else {
            None
        };

        let end_span = else_branch
            .as_ref()
            .map(|expr| expr.span)
            .unwrap_or(then_branch.span);

        let if_expr = IfExpr {
            condition: Box::new(condition),
            capture,
            then_branch: Box::new(then_branch),
            else_branch,
        };

        Some(Expr {
            span: merge_span(start, end_span),
            kind: ExprKind::If(if_expr),
        })
    }

    fn parse_match_expr(&mut self) -> Option<Expr> {
        let start = self.prev_span();
        let previous = self.disallow_ident_struct_literal;
        self.disallow_ident_struct_literal = true;
        let scrutinee = self.parse_expr(0);
        self.disallow_ident_struct_literal = previous;
        let scrutinee = scrutinee?;
        self.expect_delimiter(Delimiter::LBrace, "expected '{' after match expression");

        let mut arms = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            let mut pattern = self.parse_pattern()?;
            // Collect additional comma-separated patterns: `p1, p2, p3: body`
            let mut extra_patterns = Vec::new();
            while self.peek_delimiter(Delimiter::Comma)
                && matches!(
                    self.tokens.get(self.index + 1).map(|t| &t.kind),
                    Some(TokenKind::CharLiteral)
                        | Some(TokenKind::IntLiteral)
                        | Some(TokenKind::FloatLiteral)
                        | Some(TokenKind::StringLiteral)
                        | Some(TokenKind::BoolLiteral(_))
                        | Some(TokenKind::NullLiteral)
                        | Some(TokenKind::Operator(Operator::Dot))
                )
            {
                self.advance(); // consume `,`
                if let Some(extra_pat) = self.parse_pattern() {
                    extra_patterns.push(extra_pat);
                }
            }
            let guard = if self.match_keyword(Keyword::If) {
                Some(self.parse_expr(0)?)
            } else {
                None
            };
            if self.match_operator(Operator::FatArrow) {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "expected ':' after match pattern",
                    self.prev_span(),
                    "match arms use ':'; replace '=>' with ':'",
                );
            } else {
                self.expect_operator(Operator::Colon, "expected ':' after match pattern");
            }

            let mut capture = None;
            if self.match_operator(Operator::Pipe) {
                if self.peek_identifier_text("_") {
                    self.advance();
                } else {
                    capture = self.parse_ident();
                }
                self.expect_operator(Operator::Pipe, "expected closing '|' in match capture");
            }

            let value = self.parse_expr(0)?;
            if let Some(capture) = capture {
                if let PatternKind::EnumVariant { bindings, .. } = &mut pattern.kind {
                    if bindings.is_empty() {
                        bindings.push(capture);
                    }
                }
            }
            let arm_span = merge_span(pattern.span, value.span);
            // Emit one arm per pattern (multi-pattern arms share the same body)
            for extra_pat in extra_patterns {
                arms.push(MatchArm {
                    pattern: extra_pat,
                    guard: guard.clone(),
                    value: value.clone(),
                    span: arm_span,
                });
            }
            arms.push(MatchArm {
                pattern,
                guard,
                value,
                span: arm_span,
            });

            if self.match_delimiter(Delimiter::Comma) {
                continue;
            }
            if self.peek_delimiter(Delimiter::RBrace) {
                break;
            }
            if self.looks_like_match_pattern_start() {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "expected ',' between match arms",
                    self.current_span(),
                    "insert ',' to separate match arms",
                );
                continue;
            }
            break;
        }

        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBrace, "expected '}' to close match expression");

        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::Match(MatchExpr {
                scrutinee: Box::new(scrutinee),
                arms,
            }),
        })
    }

    fn parse_for_expr(&mut self) -> Option<Expr> {
        let start = self.prev_span();
        if self.peek_delimiter(Delimiter::LBrace) {
            let body = self.parse_stmt_expr_bridge()?;
            let span = merge_span(start, body.span);
            return Some(Expr {
                span,
                kind: ExprKind::For(ForExpr::Infinite {
                    body: Box::new(body),
                }),
            });
        }

        let prev_struct_literal = self.disallow_ident_struct_literal;
        self.disallow_ident_struct_literal = true;
        self.disallow_labeled_block = true;
        let left = self.parse_expr(11)?;
        self.disallow_labeled_block = false;
        self.disallow_ident_struct_literal = prev_struct_literal;
        if self.match_operator(Operator::DotDot) || self.match_operator(Operator::DotDotEq) {
            let inclusive = self.prev_kind() == Some(TokenKind::Operator(Operator::DotDotEq));
            self.disallow_ident_struct_literal = true;
            self.disallow_labeled_block = true;
            let right = self.parse_expr(11)?;
            self.disallow_labeled_block = false;
            self.disallow_ident_struct_literal = prev_struct_literal;
            self.match_operator(Operator::Colon);
            let binding = self.parse_optional_pipe_binding();
            let body = self.parse_stmt_expr_bridge()?;
            let span = merge_span(start, body.span);
            return Some(Expr {
                span,
                kind: ExprKind::For(ForExpr::Range {
                    start: Box::new(left),
                    end: Box::new(right),
                    inclusive,
                    binding,
                    body: Box::new(body),
                }),
            });
        }

        self.match_operator(Operator::Colon);
        let binding = self.parse_optional_pipe_binding();
        let body = self.parse_stmt_expr_bridge()?;
        let span = merge_span(start, body.span);

        if binding.is_some() {
            Some(Expr {
                span,
                kind: ExprKind::For(ForExpr::Iterate {
                    iterable: Box::new(left),
                    binding,
                    body: Box::new(body),
                }),
            })
        } else {
            Some(Expr {
                span,
                kind: ExprKind::For(ForExpr::WhileLike {
                    condition: Box::new(left),
                    body: Box::new(body),
                }),
            })
        }
    }

    fn parse_break_expr(&mut self) -> Expr {
        let start = self.prev_span();
        let label = self.parse_optional_jump_label();

        let value = if self.starts_expr() && self.current_starts_on_line(start.end_line) {
            self.parse_expr(0).map(Box::new)
        } else {
            None
        };

        let end = value.as_ref().map_or(start, |expr| expr.span);
        Expr {
            span: merge_span(start, end),
            kind: ExprKind::Break(BreakExpr { label, value }),
        }
    }

    fn parse_continue_expr(&mut self) -> Expr {
        let start = self.prev_span();
        let label = self.parse_optional_jump_label();
        let end = label.as_ref().map_or(start, |label| label.span);
        Expr {
            span: merge_span(start, end),
            kind: ExprKind::Continue { label },
        }
    }

    fn parse_optional_jump_label(&mut self) -> Option<Label> {
        if self.peek_operator(Operator::Colon)
            && matches!(
                self.tokens.get(self.index + 1).map(|token| &token.kind),
                Some(TokenKind::Identifier) | Some(TokenKind::Keyword(_))
            )
        {
            self.advance();
            self.parse_ident().map(|name| Label {
                span: name.span,
                name,
            })
        } else {
            None
        }
    }

    fn parse_extern_binding_signature(&mut self) -> Option<(TypeExpr, Option<String>, SourceSpan)> {
        let ty = if self.peek_delimiter(Delimiter::LParen) {
            self.parse_extern_fn_type_from_params()?
        } else {
            self.parse_type_expr()?
        };

        if !matches!(ty.kind, TypeExprKind::Function(_)) {
            self.report_parser_error(
                DiagnosticCode::E3001,
                "extern bindings must declare function signatures",
                ty.span,
                "use `extern (args) ret`",
            );
        }

        let link_name = if self.match_operator(Operator::Equal) {
            self.parse_string_literal()
        } else {
            None
        };
        let end = self.prev_span();
        Some((ty, link_name, end))
    }

    fn parse_extern_fn_type_from_params(&mut self) -> Option<TypeExpr> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LParen, "expected '(' after extern");
        let params = self.parse_fn_type_params();
        self.expect_delimiter(
            Delimiter::RParen,
            "expected ')' to close extern function params",
        );
        let return_type = self.parse_type_expr_or_void();

        Some(TypeExpr {
            span: merge_span(start, return_type.span),
            kind: TypeExprKind::Function(FnType {
                params,
                return_type: Box::new(return_type),
            }),
        })
    }

    fn parse_defer_expr(&mut self) -> Option<Expr> {
        let start = self.prev_span();
        let error_binding = if self.match_operator(Operator::Pipe) {
            let ident = self.parse_ident();
            self.expect_operator(Operator::Pipe, "expected closing '|' in defer binding");
            ident
        } else {
            None
        };
        let body = self.parse_expr(0)?;
        Some(Expr {
            span: merge_span(start, body.span),
            kind: ExprKind::Defer(DeferExpr {
                error_binding,
                body: Box::new(body),
            }),
        })
    }

    fn parse_fn_expr(&mut self) -> Option<Expr> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LParen, "expected '(' for function params");
        let mut params = Vec::new();
        while !self.peek_delimiter(Delimiter::RParen) && !self.is_eof() {
            let name = self.parse_ident()?;
            let (comp, ty) = if self.match_operator(Operator::Colon) {
                let comp = self.match_keyword(Keyword::Comp);
                (comp, Some(self.parse_param_type_expr()?))
            } else {
                (false, None)
            };
            let default_value = if self.match_operator(Operator::Equal) {
                self.parse_expr(0)
            } else {
                None
            };
            params.push(FnParam {
                name,
                ty,
                default_value,
                comp,
            });
            if !self.match_delimiter(Delimiter::Comma) {
                if self.peek_delimiter(Delimiter::RParen) {
                    break;
                }
                if self.peek_kind(TokenKind::Identifier) {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "expected ',' between function parameters",
                        self.current_span(),
                        "insert ',' to separate function parameters",
                    );
                    continue;
                }
                break;
            }
        }
        self.expect_delimiter(Delimiter::RParen, "expected ')' after function params");

        let mut return_type = None;
        if !self.peek_operator(Operator::FatArrow)
            && !self.peek_delimiter(Delimiter::LBrace)
            && !self.peek_keyword(Keyword::Comp)
            && !self.peek_keyword(Keyword::Inline)
            && !self.peek_operator(Operator::Bang)
        {
            return_type = self.parse_type_expr();
        }

        if self.match_operator(Operator::Bang) {
            let errors = self.parse_error_list();
            let base = return_type.unwrap_or(TypeExpr {
                kind: TypeExprKind::Named(Ident {
                    text: "void".to_string(),
                    span: self.prev_span(),
                }),
                span: self.prev_span(),
            });
            let span = base.span;
            return_type = Some(TypeExpr {
                span,
                kind: TypeExprKind::Errorable {
                    ok: Box::new(base),
                    errors,
                },
            });
        }

        if self.match_keyword(Keyword::Comp) {
            let ret_expr = self.parse_expr(0)?;
            if self.match_operator(Operator::FatArrow) {
                if self.peek_delimiter(Delimiter::LBrace) {
                    let arrow_span = self.prev_span();
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "arrow function body must be a single expression",
                        arrow_span,
                        "remove '=>' and use a block body directly",
                    );
                }
                let body_expr = self.parse_expr(0)?;
                return Some(Expr {
                    span: merge_span(start, body_expr.span),
                    kind: ExprKind::Fn(FnExpr {
                        params,
                        return_type,
                        body: FnBody::ArrowExpr(Box::new(body_expr)),
                    }),
                });
            }
            return Some(Expr {
                span: merge_span(start, ret_expr.span),
                kind: ExprKind::Fn(FnExpr {
                    params,
                    return_type,
                    body: FnBody::ArrowExpr(Box::new(Expr {
                        span: ret_expr.span,
                        kind: ExprKind::Comptime {
                            expr: Box::new(ret_expr),
                        },
                    })),
                }),
            });
        }

        let parse_block_body = |parser: &mut Self| -> Option<FnBody> {
            let block_start_index = parser.index;
            let (block_expr, closed) = parser.parse_block_expr_with_status()?;
            let block_expr = if !closed {
                parser.index = block_start_index;
                if parser.peek_delimiter(Delimiter::LBrace) {
                    parser.parse_balanced_block_expr().unwrap_or(block_expr)
                } else {
                    block_expr
                }
            } else {
                block_expr
            };
            Some(match block_expr.kind {
                ExprKind::Block(block) => FnBody::Block(block),
                _ => FnBody::ArrowExpr(Box::new(block_expr)),
            })
        };

        let body = if self.match_operator(Operator::FatArrow) {
            if self.peek_delimiter(Delimiter::LBrace) {
                let arrow_span = self.prev_span();
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "arrow function body must be a single expression",
                    arrow_span,
                    "remove '=>' and use a block body directly",
                );
                parse_block_body(self)?
            } else {
                FnBody::ArrowExpr(Box::new(self.parse_expr(0)?))
            }
        } else {
            parse_block_body(self)?
        };

        let end = match &body {
            FnBody::Block(block) => block.tail_expr.as_ref().map_or(start, |expr| expr.span),
            FnBody::ArrowExpr(expr) => expr.span,
        };
        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::Fn(FnExpr {
                params,
                return_type,
                body,
            }),
        })
    }

    fn parse_pattern(&mut self) -> Option<Pattern> {
        let token = self.current()?.clone();
        if token.kind == TokenKind::Identifier && token.lexeme == "_" {
            self.advance();
            return Some(Pattern {
                span: token.span,
                kind: PatternKind::Wildcard,
            });
        }

        // Type-starting tokens: `[]T`, `*T`, `?T` — parse as a TypeLiteral pattern
        // for use in `comp match $typeof(v) { []u8: ... }`.
        if matches!(
            token.kind,
            TokenKind::Delimiter(Delimiter::LBracket)
                | TokenKind::Operator(Operator::Star)
                | TokenKind::Operator(Operator::Question)
        ) {
            let start = token.span;
            if let Some(ty) = self.parse_type_expr() {
                return Some(Pattern {
                    span: merge_span(start, self.prev_span()),
                    kind: PatternKind::TypeLiteral(ty),
                });
            }
        }

        if token.kind == TokenKind::Operator(Operator::Dot) {
            self.advance();
            let variant = self.parse_ident()?;
            let bindings = if self.match_delimiter(Delimiter::LParen) {
                self.parse_pattern_binding_list()
            } else {
                Vec::new()
            };
            return Some(Pattern {
                span: merge_span(token.span, self.prev_span()),
                kind: PatternKind::EnumVariant {
                    root: None,
                    variant,
                    bindings,
                },
            });
        }

        if matches!(
            token.kind,
            TokenKind::IntLiteral
                | TokenKind::FloatLiteral
                | TokenKind::StringLiteral
                | TokenKind::CharLiteral
                | TokenKind::BoolLiteral(_)
                | TokenKind::NullLiteral
        ) {
            self.advance();
            let mut pattern = Pattern {
                span: token.span,
                kind: PatternKind::Literal(pattern_literal_from_token(&token)),
            };
            if self.match_operator(Operator::DotDot) || self.match_operator(Operator::DotDotEq) {
                let inclusive = self.prev_kind() == Some(TokenKind::Operator(Operator::DotDotEq));
                let end = self.parse_pattern()?;
                let span = merge_span(pattern.span, end.span);
                pattern = Pattern {
                    span,
                    kind: PatternKind::Range {
                        start: Box::new(pattern),
                        end: Box::new(end),
                        inclusive,
                    },
                };
            }
            return Some(pattern);
        }

        let ident = self.parse_ident()?;

        if self.match_operator(Operator::Dot) {
            let variant = self.parse_ident()?;
            let bindings = if self.match_delimiter(Delimiter::LParen) {
                self.parse_pattern_binding_list()
            } else {
                Vec::new()
            };
            return Some(Pattern {
                span: merge_span(ident.span, self.prev_span()),
                kind: PatternKind::EnumVariant {
                    root: Some(ident),
                    variant,
                    bindings,
                },
            });
        }

        Some(Pattern {
            span: ident.span,
            kind: PatternKind::IdentBind(ident),
        })
    }

    fn parse_pattern_binding_list(&mut self) -> Vec<Ident> {
        let mut bindings = Vec::new();
        while !self.peek_delimiter(Delimiter::RParen) && !self.is_eof() {
            if let Some(ident) = self.parse_ident() {
                bindings.push(ident);
            }
            if !self.match_delimiter(Delimiter::Comma) {
                break;
            }
        }
        self.expect_delimiter(
            Delimiter::RParen,
            "expected ')' to close enum pattern bindings",
        );
        bindings
    }

    fn parse_param_type_expr(&mut self) -> Option<TypeExpr> {
        let start = self.current_span();
        if self.match_operator(Operator::Star) {
            let mutable = self.match_keyword(Keyword::Mut);
            let inner = self.parse_type_expr()?;
            return Some(TypeExpr {
                span: merge_span(start, inner.span),
                kind: TypeExprKind::Pointer {
                    mutable,
                    inner: Box::new(inner),
                },
            });
        }

        if self.peek_delimiter(Delimiter::LBracket)
            && self.peek_next_kind(TokenKind::Delimiter(Delimiter::RBracket))
        {
            self.advance();
            self.advance();
            let mutable = self.match_keyword(Keyword::Mut);
            let element = self.parse_type_expr()?;
            return Some(TypeExpr {
                span: merge_span(start, element.span),
                kind: TypeExprKind::Slice {
                    mutable,
                    element: Box::new(element),
                },
            });
        }

        self.parse_type_expr()
    }

    fn parse_type_expr(&mut self) -> Option<TypeExpr> {
        let start = self.current_span();
        if self.match_keyword(Keyword::Comp) || self.match_keyword(Keyword::Inline) {
            let mut inner = self.parse_type_expr()?;
            inner.span = merge_span(start, inner.span);
            return Some(inner);
        }
        if self.match_operator(Operator::Question) {
            let inner = self.parse_type_expr()?;
            return Some(TypeExpr {
                span: merge_span(start, inner.span),
                kind: TypeExprKind::Optional {
                    inner: Box::new(inner),
                },
            });
        }
        if self.match_operator(Operator::Star) {
            let mutable = self.match_keyword(Keyword::Mut);
            let inner = self.parse_type_expr()?;
            return Some(TypeExpr {
                span: merge_span(start, inner.span),
                kind: TypeExprKind::Pointer {
                    mutable,
                    inner: Box::new(inner),
                },
            });
        }
        if self.match_delimiter(Delimiter::LBracket) {
            if self.match_delimiter(Delimiter::RBracket) {
                let mutable = self.match_keyword(Keyword::Mut);
                let element = self.parse_type_expr()?;
                let span = merge_span(start, element.span);
                return Some(TypeExpr {
                    span,
                    kind: TypeExprKind::Slice {
                        mutable,
                        element: Box::new(element),
                    },
                });
            }
            let len = self.parse_expr(0)?;
            self.expect_delimiter(Delimiter::RBracket, "expected ']' in array type");
            let element = self.parse_type_expr()?;
            return Some(TypeExpr {
                span: merge_span(start, element.span),
                kind: TypeExprKind::Array {
                    len: Some(Box::new(len)),
                    element: Box::new(element),
                },
            });
        }

        if self.match_delimiter(Delimiter::LParen) {
            let params = self.parse_fn_type_params();
            self.expect_delimiter(
                Delimiter::RParen,
                "expected ')' to close function type params",
            );
            let return_type = self.parse_type_expr_or_void();
            return Some(TypeExpr {
                span: merge_span(start, return_type.span),
                kind: TypeExprKind::Function(FnType {
                    params,
                    return_type: Box::new(return_type),
                }),
            });
        }

        if self.match_keyword(Keyword::Packed) {
            if self.match_keyword(Keyword::Struct) {
                return self.parse_struct_type(start, true);
            }
            self.report_parser_error(
                DiagnosticCode::E3001,
                "expected 'struct' after 'packed'",
                self.current_span(),
                "use `packed struct { ... }`",
            );
            return None;
        }

        if self.match_keyword(Keyword::Struct) {
            return self.parse_struct_type(start, false);
        }
        if self.match_keyword(Keyword::Enum) {
            return self.parse_enum_type(start);
        }

        let mut name = self.parse_ident()?;
        // Handle qualified types like `io.Writer`
        while self.peek_operator(Operator::Dot) {
            if matches!(
                self.tokens.get(self.index + 1).map(|t| &t.kind),
                Some(TokenKind::Identifier)
            ) {
                self.advance(); // consume `.`
                let field = self.parse_ident()?;
                let span = merge_span(name.span, field.span);
                name = Ident {
                    text: format!("{}.{}", name.text, field.text),
                    span,
                };
            } else {
                break;
            }
        }
        if name.text == "fn" && self.peek_delimiter(Delimiter::LParen) {
            return self.parse_removed_fn_keyword_type(name);
        }
        let mut ty = if self.match_delimiter(Delimiter::LParen) {
            let args = self.parse_type_args();
            TypeExpr {
                span: merge_span(name.span, self.prev_span()),
                kind: TypeExprKind::Applied { callee: name, args },
            }
        } else {
            TypeExpr {
                span: name.span,
                kind: TypeExprKind::Named(name),
            }
        };

        if self.match_operator(Operator::Bang) {
            let errors = self.parse_error_list();
            let span = merge_span(ty.span, self.prev_span());
            ty = TypeExpr {
                span,
                kind: TypeExprKind::Errorable {
                    ok: Box::new(ty),
                    errors,
                },
            }
        }

        Some(ty)
    }

    fn parse_removed_fn_keyword_type(&mut self, name: Ident) -> Option<TypeExpr> {
        self.report_parser_error(
            DiagnosticCode::E3001,
            "`fn(...)` type syntax has been removed",
            name.span,
            "use `(param: Type, ...) ReturnType` instead",
        );
        self.expect_delimiter(Delimiter::LParen, "expected '(' after `fn`");
        let params = self.parse_fn_type_params();
        self.expect_delimiter(
            Delimiter::RParen,
            "expected ')' to close function type params",
        );
        let return_type = self.parse_type_expr_or_void();
        Some(TypeExpr {
            span: merge_span(name.span, return_type.span),
            kind: TypeExprKind::Function(FnType {
                params,
                return_type: Box::new(return_type),
            }),
        })
    }

    fn parse_type_expr_or_void(&mut self) -> TypeExpr {
        if self.starts_type_expr() {
            self.parse_type_expr().unwrap_or(TypeExpr {
                span: self.prev_span(),
                kind: TypeExprKind::Named(Ident {
                    text: "void".to_string(),
                    span: self.prev_span(),
                }),
            })
        } else {
            TypeExpr {
                span: self.prev_span(),
                kind: TypeExprKind::Named(Ident {
                    text: "void".to_string(),
                    span: self.prev_span(),
                }),
            }
        }
    }

    fn parse_fn_type_params(&mut self) -> Vec<FnTypeParam> {
        let mut params = Vec::new();
        while !self.peek_delimiter(Delimiter::RParen) && !self.is_eof() {
            let (name, ty) = if self.peek_kind(TokenKind::Identifier)
                && self.peek_next_kind(TokenKind::Operator(Operator::Colon))
            {
                let name = self.parse_ident();
                self.expect_operator(Operator::Colon, "expected ':' in function type param");
                let ty = match self.parse_param_type_expr() {
                    Some(ty) => ty,
                    None => break,
                };
                (name, ty)
            } else {
                let Some(ty) = self.parse_param_type_expr() else {
                    break;
                };
                (None, ty)
            };
            params.push(FnTypeParam { name, ty });
            if !self.match_delimiter(Delimiter::Comma) {
                break;
            }
        }
        params
    }

    fn parse_type_args(&mut self) -> Vec<TypeExpr> {
        let mut args = Vec::new();
        while !self.peek_delimiter(Delimiter::RParen) && !self.is_eof() {
            if let Some(arg) = self.parse_type_expr() {
                args.push(arg);
            } else {
                break;
            }
            if !self.match_delimiter(Delimiter::Comma) {
                break;
            }
        }
        self.expect_delimiter(Delimiter::RParen, "expected ')' to close type arguments");
        args
    }

    fn parse_struct_type(&mut self, start: SourceSpan, packed: bool) -> Option<TypeExpr> {
        self.expect_delimiter(Delimiter::LBrace, "expected '{' after struct");
        let mut fields = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            // Skip doc comments inside struct bodies.
            while self.peek_kind(TokenKind::DocComment) {
                self.advance();
            }
            if self.peek_delimiter(Delimiter::RBrace) || self.is_eof() {
                break;
            }
            let name = self.parse_ident()?;
            if self.match_operator(Operator::Colon) {
                let ty = self.parse_type_expr()?;
                let default_value = if self.match_operator(Operator::Equal) {
                    Some(self.parse_expr(0)?)
                } else {
                    None
                };
                fields.push(StructFieldType {
                    name,
                    ty,
                    default_value,
                });
            }
            self.match_delimiter(Delimiter::Comma);
            if self.peek_delimiter(Delimiter::RBrace) {
                break;
            }
            if !self.peek_kind(TokenKind::Identifier) {
                let _ = self.parse_expr(0);
                self.match_delimiter(Delimiter::Comma);
            }
        }
        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBrace, "expected '}' to close struct type");

        Some(TypeExpr {
            span: merge_span(start, end),
            kind: TypeExprKind::Struct(StructType { packed, fields }),
        })
    }

    fn parse_enum_type(&mut self, start: SourceSpan) -> Option<TypeExpr> {
        let repr = if self.match_delimiter(Delimiter::LParen) {
            let repr = self.parse_type_expr()?;
            self.expect_delimiter(
                Delimiter::RParen,
                "expected ')' after enum representation type",
            );
            if !matches!(
                &repr.kind,
                TypeExprKind::Named(name)
                    if matches!(name.text.as_str(), "u8" | "u16" | "u32" | "u64" | "usize")
            ) {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "enum representation type must be unsigned integer",
                    repr.span,
                    "use one of `u8`, `u16`, `u32`, `u64`, or `usize`",
                );
            }
            Some(Box::new(repr))
        } else {
            None
        };
        self.expect_delimiter(Delimiter::LBrace, "expected '{' after enum");
        let mut variants = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            let name = self.parse_ident()?;
            if self.match_operator(Operator::Colon) {
                if self.match_operator(Operator::Equal) {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "enum body members are not supported",
                        name.span,
                        "keep only enum variants inside `enum { ... }`",
                    );
                    let _ = self.parse_expr(0);
                    self.match_delimiter(Delimiter::Comma);
                    continue;
                }
                let payload = self.parse_type_expr();
                variants.push(EnumVariantType { name, payload });
            } else {
                variants.push(EnumVariantType {
                    name,
                    payload: None,
                });
            }
            self.match_delimiter(Delimiter::Comma);
        }
        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBrace, "expected '}' to close enum type");
        Some(TypeExpr {
            span: merge_span(start, end),
            kind: TypeExprKind::Enum(EnumType {
                repr,
                variants,
                members: Vec::new(),
            }),
        })
    }

    fn finish_call(&mut self, callee: Expr) -> Option<Expr> {
        let args = self.parse_call_args(Some(&callee));
        let end = self.prev_span();
        Some(Expr {
            span: merge_span(callee.span, end),
            kind: ExprKind::Call(CallExpr {
                callee: Box::new(callee),
                args,
            }),
        })
    }

    fn should_parse_builtin_type_arg(&self, callee: Option<&Expr>, arg_index: usize) -> bool {
        let Some(Expr {
            kind: ExprKind::BuiltinIdent(Ident { text, .. }),
            ..
        }) = callee
        else {
            return false;
        };
        match text.as_str() {
            // $as(Type, value) — first arg is always a type
            "$as" => arg_index == 0,
            // $sizeof(T), $alignof(T) — single type arg
            "$sizeof" | "$alignof" => arg_index == 0,
            // $offsetof(T, field) — first arg is a type; second is an ident (handled by expr parser)
            "$offsetof" => arg_index == 0,
            // $typeof(expr) — arg is an expression, not a type
            _ => false,
        }
    }

    fn parse_call_args(&mut self, callee: Option<&Expr>) -> Vec<CallArg> {
        let mut args = Vec::new();
        while !self.peek_delimiter(Delimiter::RParen) && !self.is_eof() {
            if self.peek_kind(TokenKind::Identifier)
                && self.peek_next_kind(TokenKind::Operator(Operator::Colon))
            {
                let name = self.parse_ident();
                self.expect_operator(Operator::Colon, "expected ':' in named argument");
                let value = match self.parse_expr(0) {
                    Some(value) => value,
                    None => break,
                };
                args.push(CallArg { name, value });
            } else if self.should_parse_builtin_type_arg(callee, args.len()) {
                if let Some(ty) = self.parse_type_expr() {
                    let span = ty.span;
                    args.push(CallArg {
                        name: None,
                        value: Expr {
                            span,
                            kind: ExprKind::TypeLiteral(ty),
                        },
                    });
                } else if let Some(value) = self.parse_expr(0) {
                    args.push(CallArg { name: None, value });
                } else {
                    break;
                }
            } else if let Some(value) = self.parse_expr(0) {
                args.push(CallArg { name: None, value });
            } else {
                break;
            }

            if !self.match_delimiter(Delimiter::Comma) {
                if self.peek_delimiter(Delimiter::RParen) {
                    break;
                }
                if self.starts_expr() {
                    self.report_parser_error(
                        DiagnosticCode::E3001,
                        "expected ',' between call arguments",
                        self.current_span(),
                        "insert ',' to separate call arguments",
                    );
                    continue;
                }
                break;
            }
        }
        self.expect_delimiter(Delimiter::RParen, "expected ')' to close call arguments");
        args
    }

    fn parse_arg_values(&mut self) -> Vec<Expr> {
        let args = self.parse_call_args(None);
        args.into_iter().map(|arg| arg.value).collect()
    }

    fn finish_index_or_slice(&mut self, base: Expr) -> Option<Expr> {
        if self.match_operator(Operator::DotDot) || self.match_operator(Operator::DotDotEq) {
            let inclusive = self.prev_kind() == Some(TokenKind::Operator(Operator::DotDotEq));
            let end = if self.peek_delimiter(Delimiter::RBracket) {
                None
            } else {
                Some(Box::new(self.parse_expr(11)?))
            };
            self.expect_delimiter(Delimiter::RBracket, "expected ']' after slice expression");
            let end_span = end.as_ref().map(|expr| expr.span).unwrap_or(base.span);
            return Some(Expr {
                span: merge_span(base.span, end_span),
                kind: ExprKind::Slice(SliceExpr {
                    base: Box::new(base),
                    start: None,
                    end,
                    inclusive,
                }),
            });
        }

        let first = self.parse_expr(11)?;
        if self.match_operator(Operator::DotDot) || self.match_operator(Operator::DotDotEq) {
            let inclusive = self.prev_kind() == Some(TokenKind::Operator(Operator::DotDotEq));
            let end = if self.peek_delimiter(Delimiter::RBracket) {
                None
            } else {
                Some(Box::new(self.parse_expr(11)?))
            };
            self.expect_delimiter(Delimiter::RBracket, "expected ']' after slice expression");
            let end_span = end.as_ref().map(|expr| expr.span).unwrap_or(first.span);
            return Some(Expr {
                span: merge_span(base.span, end_span),
                kind: ExprKind::Slice(SliceExpr {
                    base: Box::new(base),
                    start: Some(Box::new(first)),
                    end,
                    inclusive,
                }),
            });
        }

        self.expect_delimiter(Delimiter::RBracket, "expected ']' after index expression");
        let span = merge_span(base.span, first.span);
        Some(Expr {
            span,
            kind: ExprKind::Index {
                base: Box::new(base),
                index: Box::new(first),
            },
        })
    }

    fn finish_struct_literal(
        &mut self,
        root_type: Option<Ident>,
        start: SourceSpan,
    ) -> Option<Expr> {
        let anonymous_struct = root_type.is_none() && self.looks_like_inferred_struct_field_list();

        // If there is no root type and the field list is not clearly struct-shaped,
        // treat it as a positional tuple literal: .{ a, b, c }.
        if root_type.is_none() && !anonymous_struct {
            let mut elements = Vec::new();
            while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
                let element = self.parse_expr(0)?;
                elements.push(element);
                if !self.match_delimiter(Delimiter::Comma) {
                    break;
                }
            }
            let end = self.current_span();
            self.expect_delimiter(Delimiter::RBrace, "expected '}' after tuple literal");
            return Some(Expr {
                span: merge_span(start, end),
                kind: ExprKind::TupleLiteral(elements),
            });
        }

        let fields = self.parse_struct_literal_fields(root_type.is_some() || anonymous_struct)?;
        let end = self.current_span();
        self.expect_delimiter(Delimiter::RBrace, "expected '}' after struct literal");
        Some(Expr {
            span: merge_span(start, end),
            kind: ExprKind::StructLiteral(StructLiteralExpr { root_type, fields }),
        })
    }

    fn parse_struct_literal_fields(
        &mut self,
        allow_shorthand: bool,
    ) -> Option<Vec<StructLiteralField>> {
        let mut fields = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            let name = self.parse_ident()?;
            let value = if self.match_operator(Operator::Colon) {
                self.parse_expr(0)?
            } else if allow_shorthand
                && (self.peek_delimiter(Delimiter::Comma) || self.peek_delimiter(Delimiter::RBrace))
            {
                Expr {
                    span: name.span,
                    kind: ExprKind::Ident(name.clone()),
                }
            } else {
                self.expect_operator(Operator::Colon, "expected ':' in struct literal field");
                self.parse_expr(0)?
            };
            fields.push(StructLiteralField { name, value });
            if self.match_delimiter(Delimiter::Comma) {
                continue;
            }
            if self.peek_delimiter(Delimiter::RBrace) {
                break;
            }
            if self.peek_kind(TokenKind::Identifier) {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "expected ',' between struct literal fields",
                    self.current_span(),
                    "insert ',' to separate struct fields",
                );
                continue;
            }
            break;
        }
        Some(fields)
    }

    /// Returns true when an anonymous `.{ ... }` literal is unambiguously struct-shaped.
    /// Bare shorthand fields only become valid when at least one explicit `name: value`
    /// field appears in the same literal; otherwise `.{ a, b }` remains a tuple.
    fn looks_like_inferred_struct_field_list(&self) -> bool {
        let mut cursor = self.index;
        let mut saw_explicit_field = false;

        while cursor < self.tokens.len() {
            if matches!(
                self.tokens[cursor].kind,
                TokenKind::Delimiter(Delimiter::RBrace)
            ) {
                break;
            }

            if self.tokens[cursor].kind != TokenKind::Identifier {
                return false;
            }

            let explicit = cursor + 1 < self.tokens.len()
                && matches!(
                    self.tokens[cursor + 1].kind,
                    TokenKind::Operator(Operator::Colon)
                );
            if explicit {
                saw_explicit_field = true;
                cursor += 2;
            } else {
                cursor += 1;
            }

            let mut paren_depth = 0usize;
            let mut bracket_depth = 0usize;
            let mut brace_depth = 0usize;
            while cursor < self.tokens.len() {
                match &self.tokens[cursor].kind {
                    TokenKind::Delimiter(Delimiter::LParen) => paren_depth += 1,
                    TokenKind::Delimiter(Delimiter::RParen) => {
                        if paren_depth == 0 {
                            return false;
                        }
                        paren_depth -= 1;
                    }
                    TokenKind::Delimiter(Delimiter::LBracket) => bracket_depth += 1,
                    TokenKind::Delimiter(Delimiter::RBracket) => {
                        if bracket_depth == 0 {
                            return false;
                        }
                        bracket_depth -= 1;
                    }
                    TokenKind::Delimiter(Delimiter::LBrace) => brace_depth += 1,
                    TokenKind::Delimiter(Delimiter::RBrace) => {
                        if paren_depth == 0 && bracket_depth == 0 && brace_depth == 0 {
                            return saw_explicit_field;
                        }
                        if brace_depth == 0 {
                            return false;
                        }
                        brace_depth -= 1;
                    }
                    TokenKind::Delimiter(Delimiter::Comma) => {
                        if paren_depth == 0 && bracket_depth == 0 && brace_depth == 0 {
                            cursor += 1;
                            break;
                        }
                    }
                    _ => {}
                }
                cursor += 1;
            }
        }

        saw_explicit_field
    }

    fn parse_optional_pipe_binding(&mut self) -> Option<Ident> {
        if !self.match_operator(Operator::Pipe) {
            return None;
        }

        if self.peek_identifier_text("_") {
            self.advance();
            self.expect_operator(Operator::Pipe, "expected '|' after discard binding");
            return None;
        }

        let ident = self.parse_ident();
        self.expect_operator(Operator::Pipe, "expected '|' after for binding");
        ident
    }

    fn looks_like_match_pattern_start(&self) -> bool {
        matches!(
            self.current().map(|token| &token.kind),
            Some(TokenKind::Identifier)
                | Some(TokenKind::Keyword(_))
                | Some(TokenKind::IntLiteral)
                | Some(TokenKind::FloatLiteral)
                | Some(TokenKind::StringLiteral)
                | Some(TokenKind::CharLiteral)
                | Some(TokenKind::BoolLiteral(_))
                | Some(TokenKind::NullLiteral)
                | Some(TokenKind::Operator(Operator::Dot))
        )
    }

    fn parse_error_list(&mut self) -> Vec<Ident> {
        let mut errors = Vec::new();
        while matches!(
            self.current().map(|token| &token.kind),
            Some(TokenKind::Identifier) | Some(TokenKind::Keyword(_))
        ) {
            let Some(error_ident) = self.parse_ident() else {
                break;
            };
            errors.push(error_ident);
            if !self.match_delimiter(Delimiter::Comma) {
                break;
            }
        }
        errors
    }

    fn parse_ident(&mut self) -> Option<Ident> {
        let token = self.current()?.clone();
        match token.kind {
            TokenKind::Identifier | TokenKind::Keyword(_) => {
                self.advance();
                Some(Ident {
                    text: token.lexeme,
                    span: token.span,
                })
            }
            _ => {
                let found = token_description(&token);
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    format!("expected identifier, found {found}"),
                    token.span,
                    format!("expected an identifier here, found {found}"),
                );
                self.advance();
                None
            }
        }
    }

    fn parse_string_literal(&mut self) -> Option<String> {
        let token = self.current()?.clone();
        if token.kind != TokenKind::StringLiteral {
            let found = token_description(&token);
            self.report_parser_error(
                DiagnosticCode::E3001,
                format!("expected string literal, found {found}"),
                token.span,
                format!("imports require a quoted string path; found {found}"),
            );
            self.advance();
            return None;
        }
        self.advance();
        Some(string_from_lexeme(&token.lexeme))
    }

    fn current_binary_op(&self) -> Option<(BinaryOp, u8, bool)> {
        match self.current()?.kind {
            TokenKind::Operator(Operator::Star) => Some((BinaryOp::Mul, 80, false)),
            TokenKind::Operator(Operator::Slash) => Some((BinaryOp::Div, 80, false)),
            TokenKind::Operator(Operator::Percent) => Some((BinaryOp::Mod, 80, false)),
            TokenKind::Operator(Operator::Plus) => Some((BinaryOp::Add, 70, false)),
            TokenKind::Operator(Operator::Minus) => Some((BinaryOp::Sub, 70, false)),
            TokenKind::Operator(Operator::LeftShift) => Some((BinaryOp::Shl, 65, false)),
            TokenKind::Operator(Operator::RightShift) => Some((BinaryOp::Shr, 65, false)),
            TokenKind::Operator(Operator::Ampersand) => Some((BinaryOp::BitAnd, 60, false)),
            TokenKind::Operator(Operator::Caret) => Some((BinaryOp::BitXor, 55, false)),
            TokenKind::Operator(Operator::Pipe) => Some((BinaryOp::BitOr, 50, false)),
            TokenKind::Operator(Operator::EqualEqual) => Some((BinaryOp::Eq, 40, false)),
            TokenKind::Operator(Operator::BangEqual) => Some((BinaryOp::Ne, 40, false)),
            TokenKind::Operator(Operator::Less) => Some((BinaryOp::Lt, 40, false)),
            TokenKind::Operator(Operator::LessEqual) => Some((BinaryOp::Le, 40, false)),
            TokenKind::Operator(Operator::Greater) => Some((BinaryOp::Gt, 40, false)),
            TokenKind::Operator(Operator::GreaterEqual) => Some((BinaryOp::Ge, 40, false)),
            TokenKind::Operator(Operator::AndAnd) => Some((BinaryOp::LogicalAnd, 30, false)),
            TokenKind::Operator(Operator::OrOr) => Some((BinaryOp::LogicalOr, 20, false)),
            TokenKind::Operator(Operator::DotDot) => Some((BinaryOp::Range, 10, true)),
            TokenKind::Operator(Operator::DotDotEq) => Some((BinaryOp::RangeInclusive, 10, true)),
            _ => None,
        }
    }

    fn current_assign_op(&self) -> Option<AssignOp> {
        match self.current()?.kind {
            TokenKind::Operator(Operator::Equal) => Some(AssignOp::Assign),
            TokenKind::Operator(Operator::PlusEqual) => Some(AssignOp::AddAssign),
            TokenKind::Operator(Operator::MinusEqual) => Some(AssignOp::SubAssign),
            TokenKind::Operator(Operator::StarEqual) => Some(AssignOp::MulAssign),
            TokenKind::Operator(Operator::SlashEqual) => Some(AssignOp::DivAssign),
            TokenKind::Operator(Operator::PercentEqual) => Some(AssignOp::ModAssign),
            TokenKind::Operator(Operator::AmpersandEqual) => Some(AssignOp::BitAndAssign),
            TokenKind::Operator(Operator::PipeEqual) => Some(AssignOp::BitOrAssign),
            TokenKind::Operator(Operator::CaretEqual) => Some(AssignOp::BitXorAssign),
            TokenKind::Operator(Operator::LeftShiftEqual) => Some(AssignOp::ShlAssign),
            TokenKind::Operator(Operator::RightShiftEqual) => Some(AssignOp::ShrAssign),
            _ => None,
        }
    }

    fn looks_like_fn_literal(&self) -> bool {
        if !self.peek_delimiter(Delimiter::LParen) {
            return false;
        }
        let mut depth = 0usize;
        for idx in self.index..self.tokens.len() {
            match self.tokens[idx].kind {
                TokenKind::Delimiter(Delimiter::LParen) => depth += 1,
                TokenKind::Delimiter(Delimiter::RParen) => {
                    depth -= 1;
                    if depth == 0 {
                        if !self.paren_contents_look_like_fn_params(self.index, idx) {
                            return false;
                        }

                        if let Some(next) = self.tokens.get(idx + 1) {
                            let close_line = self.tokens[idx].span.end_line;
                            if next.span.start_line != close_line
                                && !matches!(
                                    next.kind,
                                    TokenKind::Delimiter(Delimiter::LBrace)
                                        | TokenKind::Operator(Operator::FatArrow)
                                )
                            {
                                return false;
                            }
                            return matches!(
                                next.kind,
                                TokenKind::Delimiter(Delimiter::LBrace)
                                    | TokenKind::Delimiter(Delimiter::LParen)
                                    | TokenKind::Operator(Operator::FatArrow)
                                    | TokenKind::Operator(Operator::Bang)
                                    | TokenKind::Identifier
                                    | TokenKind::Keyword(Keyword::Type)
                                    | TokenKind::Keyword(Keyword::Packed)
                                    | TokenKind::Keyword(Keyword::Struct)
                                    | TokenKind::Keyword(Keyword::Enum)
                                    | TokenKind::Keyword(Keyword::Inline)
                                    | TokenKind::Keyword(Keyword::Comp)
                                    | TokenKind::Operator(Operator::Question)
                                    | TokenKind::Operator(Operator::Star)
                                    | TokenKind::Delimiter(Delimiter::LBracket)
                            );
                        }
                        return false;
                    }
                }
                _ => {}
            }
        }
        false
    }

    fn paren_contents_look_like_fn_params(&self, open_idx: usize, close_idx: usize) -> bool {
        if close_idx <= open_idx + 1 {
            return true;
        }

        let mut idx = open_idx + 1;
        while idx < close_idx {
            if !matches!(
                self.tokens.get(idx).map(|token| &token.kind),
                Some(TokenKind::Identifier) | Some(TokenKind::Keyword(_))
            ) {
                return false;
            }
            idx += 1;

            let Some(next_kind) = self.tokens.get(idx).map(|token| &token.kind) else {
                return false;
            };
            match next_kind {
                TokenKind::Delimiter(Delimiter::RParen) => return idx == close_idx,
                TokenKind::Delimiter(Delimiter::Comma) => {
                    idx += 1;
                    continue;
                }
                TokenKind::Operator(Operator::Colon) | TokenKind::Operator(Operator::Equal) => {
                    idx += 1;
                    if idx >= close_idx {
                        return false;
                    }

                    let mut paren_depth = 0usize;
                    let mut bracket_depth = 0usize;
                    let mut brace_depth = 0usize;
                    let mut consumed_any = false;

                    while idx < close_idx {
                        let Some(kind) = self.tokens.get(idx).map(|token| &token.kind) else {
                            return false;
                        };
                        match kind {
                            TokenKind::Delimiter(Delimiter::LParen) => paren_depth += 1,
                            TokenKind::Delimiter(Delimiter::RParen) => {
                                if paren_depth == 0 {
                                    break;
                                }
                                paren_depth -= 1;
                            }
                            TokenKind::Delimiter(Delimiter::LBracket) => bracket_depth += 1,
                            TokenKind::Delimiter(Delimiter::RBracket) => {
                                bracket_depth = bracket_depth.saturating_sub(1)
                            }
                            TokenKind::Delimiter(Delimiter::LBrace) => brace_depth += 1,
                            TokenKind::Delimiter(Delimiter::RBrace) => {
                                brace_depth = brace_depth.saturating_sub(1)
                            }
                            TokenKind::Delimiter(Delimiter::Comma)
                                if paren_depth == 0 && bracket_depth == 0 && brace_depth == 0 =>
                            {
                                break;
                            }
                            _ => {}
                        }
                        consumed_any = true;
                        idx += 1;
                    }

                    if !consumed_any {
                        return false;
                    }

                    if idx < close_idx
                        && matches!(
                            self.tokens.get(idx).map(|token| &token.kind),
                            Some(TokenKind::Delimiter(Delimiter::Comma))
                        )
                    {
                        idx += 1;
                    }
                }
                _ => return false,
            }
        }

        idx == close_idx
    }

    fn starts_expr(&self) -> bool {
        matches!(
            self.current().map(|token| &token.kind),
            Some(
                TokenKind::Identifier
                    | TokenKind::BuiltinIdentifier
                    | TokenKind::IntLiteral
                    | TokenKind::FloatLiteral
                    | TokenKind::StringLiteral
                    | TokenKind::CharLiteral
                    | TokenKind::NullLiteral
                    | TokenKind::BoolLiteral(_)
                    | TokenKind::Keyword(Keyword::If)
                    | TokenKind::Keyword(Keyword::Match)
                    | TokenKind::Keyword(Keyword::For)
                    | TokenKind::Keyword(Keyword::Break)
                    | TokenKind::Keyword(Keyword::Continue)
                    | TokenKind::Keyword(Keyword::Return)
                    | TokenKind::Keyword(Keyword::Defer)
                    | TokenKind::Keyword(Keyword::Comp)
                    | TokenKind::Keyword(Keyword::Inline)
                    | TokenKind::Keyword(Keyword::Use)
                    | TokenKind::Keyword(Keyword::Packed)
                    | TokenKind::Keyword(Keyword::Struct)
                    | TokenKind::Keyword(Keyword::Enum)
                    | TokenKind::Delimiter(Delimiter::LParen)
                    | TokenKind::Delimiter(Delimiter::LBracket)
                    | TokenKind::Delimiter(Delimiter::LBrace)
                    | TokenKind::Operator(Operator::Minus)
                    | TokenKind::Operator(Operator::Bang)
                    | TokenKind::Operator(Operator::Tilde)
                    | TokenKind::Operator(Operator::Ampersand)
                    | TokenKind::Operator(Operator::Dot)
            )
        )
    }

    fn current_starts_on_line(&self, line: usize) -> bool {
        self.current()
            .map(|token| token.span.start_line == line)
            .unwrap_or(false)
    }

    fn looks_like_top_level_item(&self) -> bool {
        if self.looks_like_destructure_binding() {
            return true;
        }

        let mut idx = self.index;
        while matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::DocComment)
        ) {
            idx += 1;
        }
        if matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Keyword(Keyword::Pub))
        ) {
            idx += 1;
        }
        if matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Keyword(Keyword::Extern))
        ) {
            return true;
        }
        if matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Keyword(Keyword::Mut))
        ) {
            idx += 1;
        }
        if !matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Identifier)
        ) {
            return false;
        }
        // `TypeName.method_name :=` — method binding
        if matches!(
            self.tokens.get(idx + 1).map(|t| &t.kind),
            Some(TokenKind::Operator(Operator::Dot))
        ) && matches!(
            self.tokens.get(idx + 2).map(|t| &t.kind),
            Some(TokenKind::Identifier)
        ) && matches!(
            self.tokens.get(idx + 3).map(|t| &t.kind),
            Some(TokenKind::Operator(Operator::Colon)) | Some(TokenKind::Operator(Operator::Equal))
        ) {
            return true;
        }
        matches!(
            self.tokens.get(idx + 1).map(|t| &t.kind),
            Some(TokenKind::Operator(Operator::Colon)) | Some(TokenKind::Operator(Operator::Equal))
        )
    }

    fn sync_to_top_level_boundary(&mut self) {
        while !self.is_eof() {
            if self.peek_kind(TokenKind::Eof)
                || self.peek_kind(TokenKind::DocComment)
                || self.looks_like_top_level_item()
            {
                break;
            }
            self.advance();
        }
    }

    /// Returns true if the current position looks like `{ names } :=`.
    /// Used to disambiguate destructuring from a block expression.
    fn looks_like_destructure_binding(&self) -> bool {
        let mut idx = self.index;
        // Must start with `{`
        if !matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Delimiter(Delimiter::LBrace))
        ) {
            return false;
        }
        idx += 1;
        // Must have at least one name (optionally preceded by `mut`)
        let has_item = loop {
            if matches!(
                self.tokens.get(idx).map(|t| &t.kind),
                Some(TokenKind::Keyword(Keyword::Mut))
            ) {
                idx += 1;
            }
            if !matches!(
                self.tokens.get(idx).map(|t| &t.kind),
                Some(TokenKind::Identifier)
            ) {
                break false;
            }
            idx += 1;
            match self.tokens.get(idx).map(|t| &t.kind) {
                Some(TokenKind::Delimiter(Delimiter::Comma)) => {
                    idx += 1;
                    continue;
                }
                Some(TokenKind::Delimiter(Delimiter::RBrace)) => {
                    idx += 1;
                    break true;
                }
                _ => break false,
            }
        };
        if !has_item {
            return false;
        }
        // Must be followed by `:=`
        matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Operator(Operator::Colon))
        ) && matches!(
            self.tokens.get(idx + 1).map(|t| &t.kind),
            Some(TokenKind::Operator(Operator::Equal))
        )
    }

    fn parse_destructure_declaration(
        &mut self,
        docs: Vec<DocComment>,
        visibility: Visibility,
        modifiers: DeclModifiers,
    ) -> Option<Item> {
        let start = self.current_span();
        self.expect_delimiter(Delimiter::LBrace, "expected '{' for destructure pattern");
        let mut names = Vec::new();
        while !self.peek_delimiter(Delimiter::RBrace) && !self.is_eof() {
            let mutable = self.match_keyword(Keyword::Mut);
            let name = self.parse_ident()?;
            names.push(DestructureName { mutable, name });
            if !self.match_delimiter(Delimiter::Comma) {
                break;
            }
        }
        self.expect_delimiter(Delimiter::RBrace, "expected '}' after destructure names");
        self.expect_operator(Operator::Colon, "expected ':=' after destructure pattern");
        self.expect_operator(Operator::Equal, "expected '=' after ':' in destructure");
        let value = self.parse_expr(0)?;
        Some(Item::Declaration(Box::new(Declaration {
            docs,
            visibility,
            modifiers,
            target: DeclTarget::Destructure(names),
            annotation: None,
            span: merge_span(start, value.span),
            value: DeclValue::Expr(value),
        })))
    }

    fn declaration_to_stmt(&mut self, decl: Box<Declaration>) -> Option<Stmt> {
        match &decl.value {
            DeclValue::ExternSignature(_) => {
                self.report_parser_error(
                    DiagnosticCode::E3001,
                    "extern declarations are not allowed in local scope",
                    decl.span,
                    "move this declaration to top level",
                );
                return None;
            }
            DeclValue::Expr(_) => {}
        }
        Some(Stmt::Declaration(decl))
    }

    fn parse_assignment_stmt(&mut self) -> Option<Stmt> {
        let target = self.parse_postfix_expr()?;
        let op = self.current_assign_op()?;
        self.advance();
        let value = self.parse_expr(1)?;
        Some(Stmt::Assignment(Box::new(AssignmentStmt {
            op,
            span: merge_span(target.span, value.span),
            target,
            value,
        })))
    }

    fn parse_stmt_expr_bridge(&mut self) -> Option<Expr> {
        if self.starts_assignment_stmt() {
            let before = self.index;
            if let Some(stmt) = self.parse_assignment_stmt() {
                let span = stmt_span(&stmt);
                return Some(Expr {
                    span,
                    kind: ExprKind::Block(BlockExpr {
                        label: None,
                        statements: vec![stmt],
                        tail_expr: None,
                    }),
                });
            }
            self.index = before;
        }
        self.parse_expr(0)
    }

    fn looks_like_local_binding(&self) -> bool {
        let mut idx = self.index;
        let saw_mut = matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Keyword(Keyword::Mut))
        );
        if saw_mut {
            idx += 1;
        }
        if !matches!(
            self.tokens.get(idx).map(|t| &t.kind),
            Some(TokenKind::Identifier)
        ) {
            return false;
        }
        if !saw_mut
            && matches!(
                self.tokens.get(idx + 1).map(|t| &t.kind),
                Some(TokenKind::Operator(Operator::Dot))
            )
            && matches!(
                self.tokens.get(idx + 2).map(|t| &t.kind),
                Some(TokenKind::Identifier)
            )
            && matches!(
                self.tokens.get(idx + 3).map(|t| &t.kind),
                Some(TokenKind::Operator(Operator::Colon))
            )
        {
            return true;
        }
        match self.tokens.get(idx + 1).map(|t| &t.kind) {
            Some(TokenKind::Operator(Operator::Colon)) => {
                !matches!(
                    self.tokens.get(idx + 2).map(|t| &t.kind),
                    Some(TokenKind::Delimiter(Delimiter::LBrace))
                        | Some(TokenKind::Keyword(Keyword::For))
                )
            }
            Some(TokenKind::Operator(Operator::Equal)) => saw_mut,
            _ => false,
        }
    }

    fn starts_assignment_stmt(&self) -> bool {
        matches!(
            self.current().map(|token| &token.kind),
            Some(TokenKind::Identifier) | Some(TokenKind::BuiltinIdentifier)
        )
    }

    fn expect_operator(&mut self, op: Operator, message: &str) {
        if !self.match_operator(op) {
            let found = self.current_token_description();
            self.report_parser_error(
                DiagnosticCode::E3001,
                format!("{message}; found {found}"),
                self.current_span(),
                format!("expected operator here, found {found}"),
            );
        }
    }

    fn expect_delimiter(&mut self, delimiter: Delimiter, message: &str) {
        if !self.match_delimiter(delimiter) {
            let found = self.current_token_description();
            self.report_parser_error(
                DiagnosticCode::E3001,
                format!("{message}; found {found}"),
                self.current_span(),
                format!("expected delimiter here, found {found}"),
            );
        }
    }

    fn report_parser_error(
        &mut self,
        code: DiagnosticCode,
        message: impl Into<String>,
        span: SourceSpan,
        label: impl Into<String>,
    ) {
        self.diagnostics.push(
            Diagnostic::error(DiagnosticPhase::Parser, code, message).with_primary_file_label(
                self.file_path.clone(),
                Some(span),
                label,
            ),
        );
    }

    fn current(&self) -> Option<&Token> {
        self.tokens.get(self.index)
    }

    fn current_span(&self) -> SourceSpan {
        self.current()
            .map(|token| token.span)
            .unwrap_or(SourceSpan {
                start_byte: 0,
                end_byte: 0,
                start_line: 1,
                start_col: 1,
                end_line: 1,
                end_col: 1,
            })
    }

    fn current_token_description(&self) -> String {
        self.current()
            .map(token_description)
            .unwrap_or_else(|| "end of file".to_string())
    }

    fn prev_span(&self) -> SourceSpan {
        if self.index == 0 {
            return self.current_span();
        }
        self.tokens[self.index - 1].span
    }

    fn prev_kind(&self) -> Option<TokenKind> {
        if self.index == 0 {
            return None;
        }
        Some(self.tokens[self.index - 1].kind.clone())
    }

    fn advance(&mut self) {
        if !self.is_eof() {
            self.index += 1;
        }
    }

    fn is_eof(&self) -> bool {
        self.index >= self.tokens.len()
    }

    fn match_keyword(&mut self, keyword: Keyword) -> bool {
        if self.peek_keyword(keyword) {
            self.advance();
            return true;
        }
        false
    }

    fn match_operator(&mut self, op: Operator) -> bool {
        if self.peek_operator(op) {
            self.advance();
            return true;
        }
        false
    }

    fn match_delimiter(&mut self, delimiter: Delimiter) -> bool {
        if self.peek_delimiter(delimiter) {
            self.advance();
            return true;
        }
        false
    }

    fn peek_keyword(&self, keyword: Keyword) -> bool {
        matches!(self.current().map(|t| &t.kind), Some(TokenKind::Keyword(k)) if *k == keyword)
    }

    fn peek_operator(&self, op: Operator) -> bool {
        matches!(self.current().map(|t| &t.kind), Some(TokenKind::Operator(o)) if *o == op)
    }

    fn peek_delimiter(&self, delimiter: Delimiter) -> bool {
        matches!(self.current().map(|t| &t.kind), Some(TokenKind::Delimiter(d)) if *d == delimiter)
    }

    fn peek_kind(&self, kind: TokenKind) -> bool {
        self.current().map(|t| t.kind.clone()) == Some(kind)
    }

    fn peek_next_kind(&self, kind: TokenKind) -> bool {
        self.tokens.get(self.index + 1).map(|t| t.kind.clone()) == Some(kind)
    }

    fn peek_identifier_text(&self, text: &str) -> bool {
        matches!(self.current(), Some(Token { kind: TokenKind::Identifier, lexeme, .. }) if lexeme == text)
    }

    fn starts_type_expr(&self) -> bool {
        matches!(
            self.current().map(|t| &t.kind),
            Some(TokenKind::Identifier)
                | Some(TokenKind::Keyword(Keyword::Type))
                | Some(TokenKind::Keyword(Keyword::Packed))
                | Some(TokenKind::Keyword(Keyword::Struct))
                | Some(TokenKind::Keyword(Keyword::Enum))
                | Some(TokenKind::Keyword(Keyword::Inline))
                | Some(TokenKind::Keyword(Keyword::Comp))
                | Some(TokenKind::Operator(Operator::Question))
                | Some(TokenKind::Operator(Operator::Star))
                | Some(TokenKind::Delimiter(Delimiter::LBracket))
                | Some(TokenKind::Delimiter(Delimiter::LParen))
        )
    }

    fn current_touches_expr_end(&self, expr_span: SourceSpan) -> bool {
        self.current()
            .map(|token| token.span.start_byte == expr_span.end_byte)
            .unwrap_or(false)
    }
}

fn merge_span(left: SourceSpan, right: SourceSpan) -> SourceSpan {
    SourceSpan {
        start_byte: left.start_byte,
        end_byte: right.end_byte,
        start_line: left.start_line,
        start_col: left.start_col,
        end_line: right.end_line,
        end_col: right.end_col,
    }
}

fn expr_can_be_block_tail(expr: &Expr) -> bool {
    match &expr.kind {
        ExprKind::If(if_expr) => if_expr.else_branch.is_some(),
        ExprKind::Break(_) | ExprKind::Continue { .. } | ExprKind::Return { .. } => false,
        _ => true,
    }
}

fn stmt_span(stmt: &Stmt) -> SourceSpan {
    match stmt {
        Stmt::Declaration(decl) => decl.span,
        Stmt::Assignment(assign) => assign.span,
        Stmt::Expr(expr) => expr.span,
    }
}

fn token_description(token: &Token) -> String {
    if token.kind == TokenKind::Eof {
        return "end of file".to_string();
    }
    if token.lexeme.is_empty() {
        return "token".to_string();
    }
    let escaped = token
        .lexeme
        .chars()
        .flat_map(char::escape_default)
        .collect::<String>();
    format!("`{escaped}`")
}

fn pattern_literal_from_token(token: &Token) -> PatternLiteral {
    match &token.kind {
        TokenKind::IntLiteral => PatternLiteral::Integer(token.lexeme.clone()),
        TokenKind::FloatLiteral => PatternLiteral::Float(token.lexeme.clone()),
        TokenKind::StringLiteral => PatternLiteral::String(string_from_lexeme(&token.lexeme)),
        TokenKind::CharLiteral => PatternLiteral::Char(char_from_lexeme(&token.lexeme)),
        TokenKind::BoolLiteral(value) => PatternLiteral::Bool(*value),
        TokenKind::NullLiteral => PatternLiteral::Null,
        _ => PatternLiteral::String(token.lexeme.clone()),
    }
}

fn string_from_lexeme(lexeme: &str) -> String {
    let content = if lexeme.len() >= 2 && lexeme.starts_with('"') && lexeme.ends_with('"') {
        &lexeme[1..lexeme.len() - 1]
    } else {
        lexeme
    };

    let mut out = String::with_capacity(content.len());
    let mut chars = content.chars();
    while let Some(ch) = chars.next() {
        if ch != '\\' {
            out.push(ch);
            continue;
        }

        let Some(next) = chars.next() else {
            out.push('\\');
            break;
        };

        match next {
            'n' => out.push('\n'),
            'r' => out.push('\r'),
            't' => out.push('\t'),
            '0' => out.push('\0'),
            '\\' => out.push('\\'),
            '"' => out.push('"'),
            '\'' => out.push('\''),
            other => out.push(other),
        }
    }

    out
}

fn char_from_lexeme(lexeme: &str) -> char {
    let trimmed = lexeme.trim_matches('\'');
    if trimmed.starts_with('\\') {
        return match trimmed.chars().nth(1) {
            Some('n') => '\n',
            Some('r') => '\r',
            Some('t') => '\t',
            Some('0') => '\0',
            Some('\\') => '\\',
            Some('"') => '"',
            Some('\'') => '\'',
            Some(ch) => ch,
            None => '\0',
        };
    }
    trimmed.chars().next().unwrap_or('\0')
}
