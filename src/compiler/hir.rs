use crate::compiler::ast::{
    AssignOp, BinaryOp, DestructureBinding, Expr, ExprKind, Literal, PatternKind, PatternLiteral,
    TypeExprKind, UnaryOp, Visibility,
};
use crate::compiler::diagnostics::SourceSpan;
use crate::compiler::module_resolver::{ModuleId, ModuleKey};
use crate::compiler::sema::{ModuleUnit, SemanticSession};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirProgram {
    pub modules: Vec<HirModule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirModule {
    pub module_id: ModuleId,
    pub key: ModuleKey,
    pub items: Vec<HirItem>,
    pub extern_functions: Vec<HirExternFunction>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirExternFunction {
    pub name: String,
    pub link_name: Option<String>,
    pub return_type: Option<String>,
    pub param_type_hints: Vec<Option<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirItem {
    pub name: String,
    pub def_id: Option<usize>,
    pub visibility: Visibility,
    pub mutable: bool,
    pub type_hint: Option<String>,
    pub inferred_type: Option<String>,
    pub value: HirExpr,
    pub span: SourceSpan,
    /// Set when this item was a member function inside a struct definition.
    /// Used to resolve `$self()` in members that have no `self` parameter.
    pub enclosing_struct: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirExpr {
    pub kind: HirExprKind,
    pub span: SourceSpan,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirCallArg {
    pub name: Option<String>,
    pub value: HirExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirIfCapture {
    pub binding: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirExprKind {
    Literal(HirLiteral),
    Ident(String),
    Unary {
        op: UnaryOp,
        expr: Box<HirExpr>,
    },
    Binary {
        op: BinaryOp,
        left: Box<HirExpr>,
        right: Box<HirExpr>,
    },
    Assign {
        op: AssignOp,
        target: Box<HirExpr>,
        value: Box<HirExpr>,
    },
    Call {
        callee: Box<HirExpr>,
        args: Vec<HirCallArg>,
    },
    FieldAccess {
        base: Box<HirExpr>,
        field: String,
    },
    DerefAccess {
        base: Box<HirExpr>,
    },
    Index {
        base: Box<HirExpr>,
        index: Box<HirExpr>,
    },
    Slice {
        base: Box<HirExpr>,
        start: Option<Box<HirExpr>>,
        end: Option<Box<HirExpr>>,
        inclusive: bool,
    },
    StructLiteral {
        root_type: Option<String>,
        fields: Vec<(String, HirExpr)>,
    },
    EnumVariant {
        root: Option<String>,
        variant: String,
        payload: Vec<HirExpr>,
    },
    Block {
        body: Vec<HirExpr>,
    },
    Let {
        name: String,
        mutable: bool,
        type_hint: Option<String>,
        value: Box<HirExpr>,
    },
    If {
        condition: Box<HirExpr>,
        capture: Option<HirIfCapture>,
        then_branch: Box<HirExpr>,
        else_branch: Option<Box<HirExpr>>,
    },
    Match {
        value: Box<HirExpr>,
        arms: Vec<HirMatchArm>,
    },
    For(HirForExpr),
    Break {
        value: Option<Box<HirExpr>>,
    },
    Continue,
    Return {
        value: Option<Box<HirExpr>>,
    },
    Defer {
        error_binding: Option<String>,
        body: Box<HirExpr>,
    },
    OptionalUnwrap {
        value: Box<HirExpr>,
    },
    ErrorUnwrap {
        value: Box<HirExpr>,
    },
    OrElse {
        value: Box<HirExpr>,
        error_binding: Option<String>,
        fallback: Box<HirExpr>,
    },
    Use {
        path: String,
    },
    TypeLiteral(String),
    Comptime {
        expr: Box<HirExpr>,
    },
    Inline {
        expr: Box<HirExpr>,
    },
    Function {
        params: Vec<String>,
        param_types: Vec<Option<String>>,
        param_defaults: Vec<Option<HirExpr>>,
        has_explicit_return_type: bool,
        body: Box<HirExpr>,
    },
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirForExpr {
    Infinite {
        body: Box<HirExpr>,
    },
    WhileLike {
        condition: Box<HirExpr>,
        body: Box<HirExpr>,
    },
    Range {
        start: Box<HirExpr>,
        end: Box<HirExpr>,
        inclusive: bool,
        binding: Option<String>,
        body: Box<HirExpr>,
    },
    Iterate {
        iterable: Box<HirExpr>,
        binding: Option<String>,
        body: Box<HirExpr>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HirMatchArm {
    pub pattern: HirPattern,
    pub guard: Option<HirExpr>,
    pub value: HirExpr,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirPattern {
    Wildcard,
    IdentBind(String),
    Literal(HirLiteral),
    RangeLiteral {
        start: HirLiteral,
        end: HirLiteral,
        inclusive: bool,
    },
    EnumVariant {
        root: Option<String>,
        variant: String,
        bindings: Vec<String>,
    },
    /// A type name used as a pattern in `comp match $typeof(v) { []u8: ... }`
    TypeLiteral(String),
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HirLiteral {
    Integer(String),
    Float(String),
    String(String),
    Char(char),
    Bool(bool),
    Null,
}

#[derive(Default)]
struct MethodIndex {
    type_names: BTreeSet<String>,
    import_aliases: BTreeSet<String>,
    static_methods: BTreeMap<(String, String), String>,
    instance_methods: BTreeMap<(String, String), MethodTarget>,
    call_result_nominals: BTreeMap<String, String>,
    struct_field_nominals: BTreeMap<(String, String), String>,
    struct_field_names: BTreeMap<String, BTreeSet<String>>,
}

#[derive(Default)]
struct EnumRootIndex {
    by_name: BTreeMap<String, String>,
    by_variant: BTreeMap<String, String>,
    struct_field_defaults: BTreeMap<(String, String), crate::compiler::ast::Expr>,
}

#[derive(Copy, Clone)]
enum ReceiverStyle {
    Value,
    Ptr,
}

#[derive(Clone)]
struct MethodTarget {
    name: String,
    receiver: ReceiverStyle,
}

#[derive(Clone)]
struct BindingInfo {
    nominal_type: String,
    /// True when the binding holds a pointer to the nominal type (`*T`), so
    /// that `ptr.field` can be auto-dereferenced to `ptr.*.field`.
    is_ptr: bool,
}

pub fn lower_module_units(units: &[ModuleUnit]) -> HirProgram {
    lower_module_units_with_metadata(units, None, &BTreeMap::new())
}

pub fn lower_module_units_with_metadata(
    units: &[ModuleUnit],
    sema: Option<&SemanticSession>,
    inferred_types: &BTreeMap<(crate::compiler::module_resolver::ModuleId, String), String>,
) -> HirProgram {
    let def_map = sema
        .map(|session| {
            let mut map = BTreeMap::new();
            for module in &session.modules {
                for decl in &module.declarations {
                    map.insert((module.module_id, decl.name.clone()), decl.def_id.0);
                }
            }
            map
        })
        .unwrap_or_default();

    let units_by_key = units
        .iter()
        .map(|unit| (unit.key.clone(), unit))
        .collect::<BTreeMap<_, _>>();

    let modules = units
        .iter()
        .map(|unit| {
            let method_index = build_method_index(unit, &units_by_key);
            let enum_root_index = build_enum_root_index(unit, &units_by_key);
            // Build a lookup from synthetic decl name → enclosing type name for type-scoped bindings.
            let enclosing_by_name: BTreeMap<String, String> = unit
                .type_associations
                .iter()
                .map(|a| {
                    (
                        format!("{}__{}", a.type_name, a.member_name),
                        a.type_name.clone(),
                    )
                })
                .collect();
            let mut items = unit
                .declarations
                .iter()
                .map(|decl| HirItem {
                    name: decl.name.clone(),
                    def_id: def_map.get(&(unit.module_id, decl.name.clone())).copied(),
                    visibility: decl.visibility,
                    mutable: decl.mutable,
                    type_hint: decl.annotation.as_ref().map(type_expr_to_string),
                    inferred_type: inferred_types
                        .get(&(unit.module_id, decl.name.clone()))
                        .cloned(),
                    value: rewrite_method_calls(
                        lower_expr(&decl.value, &enum_root_index),
                        &method_index,
                    ),
                    span: decl.span,
                    enclosing_struct: enclosing_by_name.get(&decl.name).cloned(),
                })
                .collect::<Vec<_>>();

            let extern_functions = unit
                .extern_declarations
                .iter()
                .filter_map(|extern_decl| {
                    let TypeExprKind::Function(fn_ty) = &extern_decl.ty.kind else {
                        return None;
                    };
                    Some(crate::compiler::hir::HirExternFunction {
                        name: extern_decl.name.clone(),
                        link_name: extern_decl.link_name.clone(),
                        return_type: Some(type_expr_to_string(&fn_ty.return_type)),
                        param_type_hints: fn_ty
                            .params
                            .iter()
                            .map(|param| Some(type_expr_to_string(&param.ty)))
                            .collect(),
                    })
                })
                .collect::<Vec<_>>();

            for decl in &unit.declarations {
                append_member_function_items(&mut items, decl, &method_index, &enum_root_index);
                append_enum_member_items(&mut items, decl, &method_index, &enum_root_index);
            }

            HirModule {
                module_id: unit.module_id,
                key: unit.key.clone(),
                items,
                extern_functions,
            }
        })
        .collect::<Vec<_>>();

    HirProgram { modules }
}

fn build_method_index(
    unit: &ModuleUnit,
    units_by_key: &BTreeMap<ModuleKey, &ModuleUnit>,
) -> MethodIndex {
    let mut index = MethodIndex::default();
    let mut module_keys = vec![unit.key.clone()];
    let mut seen_keys = BTreeSet::new();
    seen_keys.insert(unit.key.clone());

    for import in &unit.imports {
        let alias_name = import.alias.clone().unwrap_or_else(|| "_".to_string());
        index.import_aliases.insert(alias_name);
        let target_key =
            crate::compiler::module_resolver::module_key_for_import(&unit.key, &import.path);
        if seen_keys.insert(target_key.clone()) {
            module_keys.push(target_key);
        }
    }

    for key in &module_keys {
        let Some(target_unit) = units_by_key.get(key).copied() else {
            continue;
        };
        for decl in &target_unit.declarations {
            if decl_struct_type(decl).is_some() || decl_enum_type(decl).is_some() {
                index.type_names.insert(decl.name.clone());
            }
        }
    }

    for key in module_keys {
        let Some(target_unit) = units_by_key.get(&key).copied() else {
            continue;
        };
        for decl in &target_unit.declarations {
            index_struct_decl_methods(&mut index, decl);
            index_enum_decl_methods(&mut index, decl);
        }
        for assoc in &target_unit.type_associations {
            index_type_association(&mut index, assoc, &target_unit.declarations);
        }
    }

    index
}

fn build_enum_root_index(
    unit: &ModuleUnit,
    units_by_key: &BTreeMap<ModuleKey, &ModuleUnit>,
) -> EnumRootIndex {
    let mut index = EnumRootIndex::default();

    for decl in &unit.declarations {
        let Some(enum_ty) = decl_enum_type(decl) else {
            continue;
        };
        let qualified = qualified_enum_root_name(unit.module_id.0, &decl.name);
        index.by_name.insert(decl.name.clone(), qualified.clone());
        for variant in &enum_ty.variants {
            index
                .by_variant
                .insert(variant.name.text.clone(), qualified.clone());
        }
    }

    let mut module_keys = Vec::new();
    let mut seen_keys = BTreeSet::new();
    seen_keys.insert(unit.key.clone());

    for import in &unit.imports {
        let target_key =
            crate::compiler::module_resolver::module_key_for_import(&unit.key, &import.path);
        if seen_keys.insert(target_key.clone()) {
            module_keys.push(target_key);
        }
    }

    let mut conflicting_names = BTreeSet::new();
    let mut conflicting_variants = BTreeSet::new();
    let mut import_names = BTreeMap::new();
    let mut import_variants = BTreeMap::new();
    for key in module_keys {
        let Some(target_unit) = units_by_key.get(&key).copied() else {
            continue;
        };
        for decl in &target_unit.declarations {
            let Some(enum_ty) = decl_enum_type(decl) else {
                continue;
            };
            let qualified = qualified_enum_root_name(target_unit.module_id.0, &decl.name);
            insert_unique_root_mapping(
                &mut import_names,
                &mut conflicting_names,
                decl.name.clone(),
                qualified.clone(),
            );
            for variant in &enum_ty.variants {
                insert_unique_root_mapping(
                    &mut import_variants,
                    &mut conflicting_variants,
                    variant.name.text.clone(),
                    qualified.clone(),
                );
            }
        }
    }

    for (name, root) in import_names {
        index.by_name.entry(name).or_insert(root);
    }
    for (variant, root) in import_variants {
        index.by_variant.entry(variant).or_insert(root);
    }

    for decl in &unit.declarations {
        let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
            continue;
        };
        let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
            continue;
        };
        for field in &struct_ty.fields {
            if let Some(default) = &field.default_value {
                index.struct_field_defaults.insert(
                    (decl.name.clone(), field.name.text.clone()),
                    default.clone(),
                );
            }
        }
    }

    index
}

fn insert_unique_root_mapping(
    map: &mut BTreeMap<String, String>,
    conflicts: &mut BTreeSet<String>,
    key: String,
    value: String,
) {
    if conflicts.contains(&key) {
        return;
    }
    if let Some(existing) = map.get(&key) {
        if existing != &value {
            map.remove(&key);
            conflicts.insert(key);
        }
    } else {
        map.insert(key, value);
    }
}

fn qualified_enum_root_name(module_id: usize, enum_name: &str) -> String {
    format!("#{module_id}::{enum_name}")
}

fn index_struct_decl_methods(index: &mut MethodIndex, decl: &crate::compiler::sema::DeclStub) {
    let Some(struct_ty) = decl_struct_type(decl) else {
        return;
    };
    index.type_names.insert(decl.name.clone());
    let mut field_names = BTreeSet::new();
    for field in &struct_ty.fields {
        field_names.insert(field.name.text.clone());
        if let Some(nominal) = type_expr_nominal_name(&field.ty) {
            if !is_predeclared_type_name(&nominal) {
                index
                    .struct_field_nominals
                    .insert((decl.name.clone(), field.name.text.clone()), nominal);
            }
        }
    }
    index
        .struct_field_names
        .insert(decl.name.clone(), field_names);
}

fn index_enum_decl_methods(index: &mut MethodIndex, decl: &crate::compiler::sema::DeclStub) {
    let Some(enum_ty) = decl_enum_type(decl) else {
        return;
    };
    index.type_names.insert(decl.name.clone());
    for member in &enum_ty.members {
        let Some(fn_expr) = member_fn_expr(&member.value) else {
            continue;
        };
        let synthetic = format!("{}__{}", decl.name, member.name.text);
        index.static_methods.insert(
            (decl.name.clone(), member.name.text.clone()),
            synthetic.clone(),
        );
        let receiver_style = instance_receiver_style(fn_expr, &decl.name);
        if let Some(receiver) = receiver_style {
            index.instance_methods.insert(
                (decl.name.clone(), member.name.text.clone()),
                MethodTarget {
                    name: synthetic.clone(),
                    receiver,
                },
            );
        }
        if let Some(nominal) = fn_expr
            .return_type
            .as_ref()
            .and_then(type_expr_nominal_name)
            .filter(|name| !is_predeclared_type_name(name))
        {
            index
                .call_result_nominals
                .insert(synthetic.clone(), nominal);
        }
    }
}

fn index_type_association(
    index: &mut MethodIndex,
    assoc: &crate::compiler::sema::TypeAssociation,
    decls: &[crate::compiler::sema::DeclStub],
) {
    let synthetic = format!("{}__{}", assoc.type_name, assoc.member_name);
    index.static_methods.insert(
        (assoc.type_name.clone(), assoc.member_name.clone()),
        synthetic.clone(),
    );
    // For functions, also register UFCS instance dispatch and return-type nominal tracking.
    let fn_expr = decls
        .iter()
        .find(|d| d.name == synthetic)
        .and_then(|d| member_fn_expr(&d.value));
    let Some(fn_expr) = fn_expr else {
        return;
    };
    let receiver_style = instance_receiver_style(fn_expr, &assoc.type_name);
    if let Some(receiver) = receiver_style {
        index.instance_methods.insert(
            (assoc.type_name.clone(), assoc.member_name.clone()),
            MethodTarget {
                name: synthetic.clone(),
                receiver,
            },
        );
    }
    if let Some(nominal) = fn_expr
        .return_type
        .as_ref()
        .and_then(type_expr_nominal_name)
        .filter(|name| !is_predeclared_type_name(name))
    {
        index.call_result_nominals.insert(synthetic, nominal);
    }
}

fn is_predeclared_type_name(name: &str) -> bool {
    matches!(
        name,
        "u1" | "u8"
            | "u16"
            | "u32"
            | "u64"
            | "i8"
            | "i16"
            | "i31"
            | "i32"
            | "i64"
            | "f32"
            | "f64"
            | "type"
            | "any"
            | "opaque"
            | "void"
            | "usize"
            | "isize"
            | "bool"
    )
}

fn nominal_name_from_type_hint_text(text: &str) -> Option<String> {
    let mut ty = text.trim();
    if let Some(stripped) = ty.strip_prefix("*mut ") {
        ty = stripped.trim();
    } else if let Some(stripped) = ty.strip_prefix('*') {
        ty = stripped.trim();
    }
    if let Some(stripped) = ty.strip_prefix('?') {
        ty = stripped.trim();
    }
    if let Some((ok, _errs)) = ty.split_once('!') {
        ty = ok.trim();
    }

    let nominal = if let Some((head, _)) = ty.split_once('(') {
        head.trim()
    } else {
        ty
    };
    if nominal.is_empty() || is_predeclared_type_name(nominal) {
        return None;
    }
    Some(nominal.to_string())
}

fn type_expr_nominal_name(ty: &crate::compiler::ast::TypeExpr) -> Option<String> {
    match &ty.kind {
        TypeExprKind::Named(ident) => Some(ident.text.clone()),
        TypeExprKind::Applied { callee, .. } => Some(callee.text.clone()),
        TypeExprKind::Pointer { inner, .. } | TypeExprKind::Optional { inner } => {
            type_expr_nominal_name(inner)
        }
        TypeExprKind::Errorable { ok, .. } => type_expr_nominal_name(ok),
        TypeExprKind::Array { .. }
        | TypeExprKind::Slice { .. }
        | TypeExprKind::Function(_)
        | TypeExprKind::Struct(_)
        | TypeExprKind::Enum(_) => None,
    }
}

fn instance_receiver_style(
    fn_expr: &crate::compiler::ast::FnExpr,
    type_name: &str,
) -> Option<ReceiverStyle> {
    let first = fn_expr.params.first()?;
    let Some(first_ty) = &first.ty else {
        return None;
    };
    if matches!(&first_ty.kind, TypeExprKind::Named(ident) if ident.text == type_name)
        || matches!(&first_ty.kind, TypeExprKind::Applied { callee, .. } if callee.text == type_name)
    {
        return Some(ReceiverStyle::Value);
    }
    if let TypeExprKind::Pointer { inner } = &first_ty.kind {
        if matches!(inner.kind, TypeExprKind::Named(ref ident) if ident.text == type_name)
            || matches!(inner.kind, TypeExprKind::Applied { ref callee, .. } if callee.text == type_name)
        {
            return Some(ReceiverStyle::Ptr);
        }
    }
    None
}

fn append_member_function_items(
    _items: &mut Vec<HirItem>,
    _decl: &crate::compiler::sema::DeclStub,
    _method_index: &MethodIndex,
    _enum_root_index: &EnumRootIndex,
) {
    // Struct methods are now defined as top-level method bindings (TypeName.method := ...)
    // and are emitted by append_method_binding_items instead.
}

fn append_enum_member_items(
    items: &mut Vec<HirItem>,
    decl: &crate::compiler::sema::DeclStub,
    method_index: &MethodIndex,
    enum_root_index: &EnumRootIndex,
) {
    let Some(enum_ty) = decl_enum_type(decl) else {
        return;
    };
    for member in &enum_ty.members {
        let Some(fn_expr) = member_fn_expr(&member.value) else {
            continue;
        };
        let Some(name) = method_index
            .static_methods
            .get(&(decl.name.clone(), member.name.text.clone()))
        else {
            continue;
        };
        let lowered_member = lower_expr(&member.value, enum_root_index);
        items.push(HirItem {
            name: name.clone(),
            def_id: None,
            visibility: decl.visibility,
            mutable: false,
            type_hint: None,
            inferred_type: fn_expr.return_type.as_ref().map(type_expr_to_string),
            value: rewrite_method_calls(lowered_member, method_index),
            span: member.value.span,
            enclosing_struct: Some(decl.name.clone()),
        });
    }
}

/// Returns the type parameters from a generic struct declaration (e.g. `T: comp type` from
/// `Vec := (T: comp type) type => struct { ... }`). Used when prepending outer params to
/// static method bindings on generic types.
#[allow(dead_code)]
fn decl_outer_type_params(decl: &crate::compiler::sema::DeclStub) -> Vec<(String, Option<String>)> {
    let fn_expr = match &decl.value.kind {
        ExprKind::Fn(fn_expr) => Some(fn_expr),
        ExprKind::Inline { expr } => match &expr.kind {
            ExprKind::Fn(fn_expr) => Some(fn_expr),
            _ => None,
        },
        _ => None,
    };
    let Some(fn_expr) = fn_expr else {
        return Vec::new();
    };
    fn_expr
        .params
        .iter()
        .map(|param| {
            (
                param.name.text.clone(),
                param.ty.as_ref().map(type_expr_to_string),
            )
        })
        .collect()
}

#[allow(dead_code)]
fn prepend_outer_type_params_to_member_fn(
    expr: HirExpr,
    outer_params: &[(String, Option<String>)],
) -> HirExpr {
    if outer_params.is_empty() {
        return expr;
    }
    let span = expr.span;
    match expr.kind {
        HirExprKind::Function {
            mut params,
            mut param_types,
            param_defaults,
            has_explicit_return_type,
            body,
        } => {
            let mut all_params = outer_params
                .iter()
                .map(|(name, _)| name.clone())
                .collect::<Vec<_>>();
            all_params.append(&mut params);

            let mut all_param_types = outer_params
                .iter()
                .map(|(_, ty)| ty.clone())
                .collect::<Vec<_>>();
            all_param_types.append(&mut param_types);

            let mut all_param_defaults = vec![None; outer_params.len()];
            all_param_defaults.extend(param_defaults);

            HirExpr {
                kind: HirExprKind::Function {
                    params: all_params,
                    param_types: all_param_types,
                    param_defaults: all_param_defaults,
                    has_explicit_return_type,
                    body,
                },
                span,
            }
        }
        HirExprKind::Inline { expr } => HirExpr {
            kind: HirExprKind::Inline {
                expr: Box::new(prepend_outer_type_params_to_member_fn(*expr, outer_params)),
            },
            span,
        },
        other => HirExpr { kind: other, span },
    }
}

fn decl_struct_type(
    decl: &crate::compiler::sema::DeclStub,
) -> Option<&crate::compiler::ast::StructType> {
    match &decl.value.kind {
        ExprKind::TypeLiteral(type_lit) => {
            if let TypeExprKind::Struct(struct_ty) = &type_lit.kind {
                Some(struct_ty)
            } else {
                None
            }
        }
        ExprKind::Fn(fn_expr) => match &fn_expr.body {
            crate::compiler::ast::FnBody::ArrowExpr(expr) => expr_type_literal_struct(expr),
            crate::compiler::ast::FnBody::Block(block) => {
                if let Some(tail) = &block.tail_expr {
                    expr_type_literal_struct(tail)
                } else {
                    None
                }
            }
        },
        _ => None,
    }
}

fn decl_enum_type(
    decl: &crate::compiler::sema::DeclStub,
) -> Option<&crate::compiler::ast::EnumType> {
    let ExprKind::TypeLiteral(type_lit) = &decl.value.kind else {
        return None;
    };
    let TypeExprKind::Enum(enum_ty) = &type_lit.kind else {
        return None;
    };
    Some(enum_ty)
}

fn expr_type_literal_struct(expr: &Expr) -> Option<&crate::compiler::ast::StructType> {
    let ExprKind::TypeLiteral(type_lit) = &expr.kind else {
        return None;
    };
    let TypeExprKind::Struct(struct_ty) = &type_lit.kind else {
        return None;
    };
    Some(struct_ty)
}

fn member_fn_expr(expr: &Expr) -> Option<&crate::compiler::ast::FnExpr> {
    match &expr.kind {
        ExprKind::Fn(fn_expr) => Some(fn_expr),
        ExprKind::Inline { expr } => match &expr.kind {
            ExprKind::Fn(fn_expr) => Some(fn_expr),
            _ => None,
        },
        _ => None,
    }
}

fn rewrite_method_calls(expr: HirExpr, method_index: &MethodIndex) -> HirExpr {
    let mut scopes = vec![BTreeMap::<String, BindingInfo>::new()];
    rewrite_method_calls_with_scopes(expr, method_index, &mut scopes)
}

fn rewrite_method_calls_with_scopes(
    expr: HirExpr,
    method_index: &MethodIndex,
    scopes: &mut Vec<BTreeMap<String, BindingInfo>>,
) -> HirExpr {
    let span = expr.span;
    let kind = match expr.kind {
        HirExprKind::Call { callee, args } => {
            let callee = rewrite_method_calls_with_scopes(*callee, method_index, scopes);
            let mut args = args
                .into_iter()
                .map(|arg| HirCallArg {
                    name: arg.name,
                    value: rewrite_method_calls_with_scopes(arg.value, method_index, scopes),
                })
                .collect::<Vec<_>>();
            if let HirExprKind::FieldAccess { base, field } = callee.kind {
                if is_type_receiver_expr(&base, scopes, method_index) {
                    if let Some(base_nominal) = infer_nominal_type(&base, scopes, method_index) {
                        if let Some(synth) = method_index
                            .static_methods
                            .get(&(base_nominal, field.clone()))
                        {
                            let mut method_args = Vec::new();
                            if let HirExprKind::Call {
                                args: type_args, ..
                            } = &base.kind
                            {
                                method_args.extend(type_args.iter().map(|arg| HirCallArg {
                                    name: arg.name.clone(),
                                    value: rewrite_method_calls_with_scopes(
                                        arg.value.clone(),
                                        method_index,
                                        scopes,
                                    ),
                                }));
                            }
                            method_args.append(&mut args);
                            let rewritten_callee = if let Some(alias) =
                                import_alias_for_type_receiver(&base, method_index)
                            {
                                HirExpr {
                                    kind: HirExprKind::FieldAccess {
                                        base: Box::new(HirExpr {
                                            kind: HirExprKind::Ident(alias),
                                            span,
                                        }),
                                        field: synth.clone(),
                                    },
                                    span,
                                }
                            } else {
                                HirExpr {
                                    kind: HirExprKind::Ident(synth.clone()),
                                    span,
                                }
                            };
                            return HirExpr {
                                kind: HirExprKind::Call {
                                    callee: Box::new(rewritten_callee),
                                    args: method_args,
                                },
                                span,
                            };
                        }
                    }
                }

                if let Some(base_nominal) = infer_nominal_type(&base, scopes, method_index) {
                    if let Some(target) = method_index
                        .instance_methods
                        .get(&(base_nominal, field.clone()))
                    {
                        let mut method_args = Vec::with_capacity(args.len() + 1);
                        let base_value =
                            rewrite_method_calls_with_scopes(*base, method_index, scopes);
                        let receiver_expr = match target.receiver {
                            ReceiverStyle::Value => base_value,
                            ReceiverStyle::Ptr => HirExpr {
                                kind: HirExprKind::Unary {
                                    op: UnaryOp::Ref,
                                    expr: Box::new(base_value),
                                },
                                span,
                            },
                        };
                        method_args.push(HirCallArg {
                            name: None,
                            value: receiver_expr,
                        });
                        method_args.append(&mut args);
                        return HirExpr {
                            kind: HirExprKind::Call {
                                callee: Box::new(HirExpr {
                                    kind: HirExprKind::Ident(target.name.clone()),
                                    span,
                                }),
                                args: method_args,
                            },
                            span,
                        };
                    }
                }

                HirExprKind::Call {
                    callee: Box::new(HirExpr {
                        kind: HirExprKind::FieldAccess {
                            base: Box::new(rewrite_method_calls_with_scopes(
                                *base,
                                method_index,
                                scopes,
                            )),
                            field,
                        },
                        span,
                    }),
                    args,
                }
            } else {
                HirExprKind::Call {
                    callee: Box::new(callee),
                    args,
                }
            }
        }
        HirExprKind::Unary { op, expr } => HirExprKind::Unary {
            op,
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Binary { op, left, right } => HirExprKind::Binary {
            op,
            left: Box::new(rewrite_method_calls_with_scopes(
                *left,
                method_index,
                scopes,
            )),
            right: Box::new(rewrite_method_calls_with_scopes(
                *right,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Assign { op, target, value } => HirExprKind::Assign {
            op,
            target: Box::new(rewrite_method_calls_with_scopes(
                *target,
                method_index,
                scopes,
            )),
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::FieldAccess { base, field } => {
            // Auto-deref: if the base is a pointer to a struct that has this field,
            // insert a DerefAccess automatically so `ptr.field` works like `ptr.*.field`.
            let auto_deref = if let HirExprKind::Ident(name) = &base.kind {
                scopes
                    .iter()
                    .rev()
                    .find_map(|s| s.get(name))
                    .map_or(false, |info| {
                        info.is_ptr
                            && method_index
                                .struct_field_names
                                .get(&info.nominal_type)
                                .map_or(false, |fields| fields.contains(&field))
                    })
            } else {
                false
            };
            let rewritten_base = rewrite_method_calls_with_scopes(*base, method_index, scopes);
            let base_expr = if auto_deref {
                HirExpr {
                    kind: HirExprKind::DerefAccess {
                        base: Box::new(rewritten_base),
                    },
                    span,
                }
            } else {
                rewritten_base
            };
            HirExprKind::FieldAccess {
                base: Box::new(base_expr),
                field,
            }
        }
        HirExprKind::DerefAccess { base } => HirExprKind::DerefAccess {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Index { base, index } => HirExprKind::Index {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
            index: Box::new(rewrite_method_calls_with_scopes(
                *index,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Slice {
            base,
            start,
            end,
            inclusive,
        } => HirExprKind::Slice {
            base: Box::new(rewrite_method_calls_with_scopes(
                *base,
                method_index,
                scopes,
            )),
            start: start.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
            end: end.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
            inclusive,
        },
        HirExprKind::StructLiteral { root_type, fields } => HirExprKind::StructLiteral {
            root_type,
            fields: fields
                .into_iter()
                .map(|(name, expr)| {
                    (
                        name,
                        rewrite_method_calls_with_scopes(expr, method_index, scopes),
                    )
                })
                .collect(),
        },
        HirExprKind::EnumVariant {
            root,
            variant,
            payload,
        } => HirExprKind::EnumVariant {
            root,
            variant,
            payload: payload
                .into_iter()
                .map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes))
                .collect(),
        },
        HirExprKind::Block { body } => {
            scopes.push(BTreeMap::new());
            let mut out = Vec::with_capacity(body.len());
            for expr in body {
                let rewritten = rewrite_method_calls_with_scopes(expr, method_index, scopes);
                if let HirExprKind::Let {
                    name,
                    value,
                    type_hint,
                    ..
                } = &rewritten.kind
                {
                    let value_nominal = infer_binding_nominal(value, scopes, method_index);
                    // Extract nominal type and pointer flag from type hint or inferred value type.
                    let (nominal_opt, is_ptr) = if let Some(hint) = type_hint {
                        if let Some(inner) = hint.strip_prefix('*') {
                            let inner = inner.trim_start_matches("mut").trim_start();
                            (Some(inner.to_string()), true)
                        } else {
                            (value_nominal, false)
                        }
                    } else {
                        (value_nominal, false)
                    };
                    if let Some(nominal) = nominal_opt {
                        if let Some(scope) = scopes.last_mut() {
                            scope.insert(
                                name.clone(),
                                BindingInfo {
                                    nominal_type: nominal,
                                    is_ptr,
                                },
                            );
                        }
                    }
                }
                out.push(rewritten);
            }
            scopes.pop();
            HirExprKind::Block { body: out }
        }
        HirExprKind::Let {
            name,
            mutable,
            type_hint,
            value,
        } => HirExprKind::Let {
            name,
            mutable,
            type_hint,
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::If {
            condition,
            capture,
            then_branch,
            else_branch,
        } => HirExprKind::If {
            condition: Box::new(rewrite_method_calls_with_scopes(
                *condition,
                method_index,
                scopes,
            )),
            capture,
            then_branch: Box::new(rewrite_method_calls_with_scopes(
                *then_branch,
                method_index,
                scopes,
            )),
            else_branch: else_branch.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Match { value, arms } => HirExprKind::Match {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
            arms: arms
                .into_iter()
                .map(|arm| HirMatchArm {
                    pattern: arm.pattern,
                    guard: arm
                        .guard
                        .map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes)),
                    value: rewrite_method_calls_with_scopes(arm.value, method_index, scopes),
                })
                .collect(),
        },
        HirExprKind::For(for_expr) => HirExprKind::For(for_expr),
        HirExprKind::Break { value } => HirExprKind::Break {
            value: value.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Return { value } => HirExprKind::Return {
            value: value.map(|expr| {
                Box::new(rewrite_method_calls_with_scopes(
                    *expr,
                    method_index,
                    scopes,
                ))
            }),
        },
        HirExprKind::Defer {
            error_binding,
            body,
        } => HirExprKind::Defer {
            error_binding,
            body: Box::new(rewrite_method_calls_with_scopes(
                *body,
                method_index,
                scopes,
            )),
        },
        HirExprKind::OptionalUnwrap { value } => HirExprKind::OptionalUnwrap {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::ErrorUnwrap { value } => HirExprKind::ErrorUnwrap {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
        },
        HirExprKind::OrElse {
            value,
            error_binding,
            fallback,
        } => HirExprKind::OrElse {
            value: Box::new(rewrite_method_calls_with_scopes(
                *value,
                method_index,
                scopes,
            )),
            error_binding,
            fallback: Box::new(rewrite_method_calls_with_scopes(
                *fallback,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Comptime { expr } => HirExprKind::Comptime {
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Inline { expr } => HirExprKind::Inline {
            expr: Box::new(rewrite_method_calls_with_scopes(
                *expr,
                method_index,
                scopes,
            )),
        },
        HirExprKind::Function {
            params,
            param_types,
            param_defaults,
            has_explicit_return_type,
            body,
        } => {
            scopes.push(BTreeMap::new());
            if let Some(scope) = scopes.last_mut() {
                for (idx, param_name) in params.iter().enumerate() {
                    let Some(type_hint) = param_types.get(idx).and_then(|hint| hint.as_ref())
                    else {
                        continue;
                    };
                    let Some(nominal) = nominal_name_from_type_hint_text(type_hint) else {
                        continue;
                    };
                    scope.insert(
                        param_name.clone(),
                        BindingInfo {
                            nominal_type: nominal,
                            is_ptr: false,
                        },
                    );
                }
            }

            let rewritten_defaults = param_defaults
                .into_iter()
                .map(|default| {
                    default.map(|expr| rewrite_method_calls_with_scopes(expr, method_index, scopes))
                })
                .collect();
            let rewritten_body = rewrite_method_calls_with_scopes(*body, method_index, scopes);
            scopes.pop();

            HirExprKind::Function {
                params,
                param_types,
                param_defaults: rewritten_defaults,
                body: Box::new(rewritten_body),
                has_explicit_return_type,
            }
        }
        other => other,
    };
    HirExpr { kind, span }
}

fn import_alias_for_type_receiver(expr: &HirExpr, method_index: &MethodIndex) -> Option<String> {
    match &expr.kind {
        HirExprKind::Call { callee, .. } => match &callee.kind {
            HirExprKind::FieldAccess { base, field } => {
                if let HirExprKind::Ident(alias) = &base.kind {
                    if method_index.import_aliases.contains(alias)
                        && method_index.type_names.contains(field)
                    {
                        return Some(alias.clone());
                    }
                }
                None
            }
            _ => None,
        },
        _ => None,
    }
}

fn infer_nominal_type(
    expr: &HirExpr,
    scopes: &[BTreeMap<String, BindingInfo>],
    method_index: &MethodIndex,
) -> Option<String> {
    match &expr.kind {
        HirExprKind::StructLiteral {
            root_type: Some(root),
            ..
        } => Some(root.clone()),
        HirExprKind::StructLiteral {
            root_type: None,
            fields,
        } => {
            let literal_field_names = fields
                .iter()
                .map(|(name, _)| name.clone())
                .collect::<BTreeSet<_>>();
            let mut matches = method_index
                .struct_field_names
                .iter()
                .filter_map(|(nominal, field_names)| {
                    if *field_names == literal_field_names {
                        Some(nominal.clone())
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>();
            if matches.len() == 1 {
                matches.pop()
            } else {
                None
            }
        }
        HirExprKind::Ident(name) => scopes
            .iter()
            .rev()
            // Skip pointer bindings: `ptr: *T` is not a direct struct value for method dispatch.
            // Auto-deref handles field access separately; method calls need explicit `ptr.*`.
            .find_map(|scope| {
                scope.get(name).and_then(|info| {
                    if info.is_ptr {
                        None
                    } else {
                        Some(info.nominal_type.clone())
                    }
                })
            })
            .or_else(|| {
                method_index
                    .type_names
                    .contains(name)
                    .then_some(name.clone())
            }),
        HirExprKind::FieldAccess { base, field } => infer_nominal_type(base, scopes, method_index)
            .and_then(|base_nominal| {
                method_index
                    .struct_field_nominals
                    .get(&(base_nominal, field.clone()))
                    .cloned()
            }),
        HirExprKind::DerefAccess { base } => infer_nominal_type(base, scopes, method_index),
        HirExprKind::Call { callee, .. } => match &callee.kind {
            HirExprKind::Ident(name) if method_index.type_names.contains(name) => {
                Some(name.clone())
            }
            HirExprKind::Ident(name) => method_index.call_result_nominals.get(name).cloned(),
            HirExprKind::FieldAccess { base, field } => {
                if let HirExprKind::Ident(alias) = &base.kind {
                    if method_index.import_aliases.contains(alias)
                        && method_index.type_names.contains(field)
                    {
                        return Some(field.clone());
                    }
                }
                let base_nominal = infer_nominal_type(base, scopes, method_index)?;
                if let Some(synth) = method_index
                    .static_methods
                    .get(&(base_nominal.clone(), field.clone()))
                {
                    if let Some(nominal) = method_index.call_result_nominals.get(synth) {
                        return Some(nominal.clone());
                    }
                }
                if method_index
                    .instance_methods
                    .contains_key(&(base_nominal.clone(), field.clone()))
                {
                    Some(base_nominal)
                } else {
                    None
                }
            }
            _ => None,
        },
        HirExprKind::OrElse { value, .. }
        | HirExprKind::OptionalUnwrap { value }
        | HirExprKind::ErrorUnwrap { value }
        | HirExprKind::Comptime { expr: value }
        | HirExprKind::Inline { expr: value } => infer_nominal_type(value, scopes, method_index),
        HirExprKind::If {
            then_branch,
            else_branch,
            ..
        } => {
            let then_nominal = infer_nominal_type(then_branch, scopes, method_index);
            let else_nominal = else_branch
                .as_ref()
                .and_then(|branch| infer_nominal_type(branch, scopes, method_index));
            match (then_nominal, else_nominal) {
                (Some(left), Some(right)) if left == right => Some(left),
                (Some(left), None) => Some(left),
                _ => None,
            }
        }
        HirExprKind::Block { body } => body
            .last()
            .and_then(|expr| infer_nominal_type(expr, scopes, method_index)),
        _ => None,
    }
}

fn infer_binding_nominal(
    expr: &HirExpr,
    scopes: &[BTreeMap<String, BindingInfo>],
    method_index: &MethodIndex,
) -> Option<String> {
    if let HirExprKind::Call { callee, .. } = &expr.kind {
        let synthetic_name = match &callee.kind {
            HirExprKind::Ident(name) => Some(name.clone()),
            HirExprKind::FieldAccess { base, field } => {
                if matches!(&base.kind, HirExprKind::Ident(alias) if method_index.import_aliases.contains(alias))
                {
                    Some(field.clone())
                } else {
                    None
                }
            }
            _ => None,
        };
        if let Some(name) = synthetic_name {
            if let Some(nominal) = method_index.call_result_nominals.get(&name).cloned() {
                return Some(nominal);
            }
        }
    }

    infer_nominal_type(expr, scopes, method_index)
}

fn is_type_receiver_expr(
    expr: &HirExpr,
    scopes: &[BTreeMap<String, BindingInfo>],
    method_index: &MethodIndex,
) -> bool {
    match &expr.kind {
        HirExprKind::Ident(name) => {
            method_index.type_names.contains(name)
                && !scopes.iter().rev().any(|scope| scope.contains_key(name))
        }
        HirExprKind::Call { callee, .. } => match &callee.kind {
            HirExprKind::Ident(name) => method_index.type_names.contains(name),
            HirExprKind::FieldAccess { base, field } => {
                matches!(&base.kind, HirExprKind::Ident(alias)
                        if method_index.import_aliases.contains(alias)
                            && method_index.type_names.contains(field))
            }
            _ => false,
        },
        _ => false,
    }
}

fn collect_and_operands<'a>(expr: &'a Expr) -> Vec<&'a Expr> {
    match &expr.kind {
        ExprKind::Binary {
            op: crate::compiler::ast::BinaryOp::LogicalAnd,
            left,
            right,
        } => {
            let mut ops = collect_and_operands(left);
            ops.push(right);
            ops
        }
        _ => vec![expr],
    }
}

fn lower_multi_capture_if(
    condition: &Expr,
    bindings: &[Option<crate::compiler::ast::Ident>],
    then_branch: HirExpr,
    else_branch: Option<HirExpr>,
    enum_root_index: &EnumRootIndex,
    span: crate::compiler::diagnostics::SourceSpan,
) -> HirExpr {
    let operands = collect_and_operands(condition);
    let n = bindings.len();
    let m = operands.len();
    let capture_start = m.saturating_sub(n);

    // Build from the innermost (last capture) outward
    let last_binding = bindings
        .last()
        .and_then(|b| b.as_ref())
        .map(|i| i.text.clone());
    let last_op = operands
        .get(m.saturating_sub(1))
        .copied()
        .unwrap_or(condition);
    let mut result = HirExpr {
        span,
        kind: HirExprKind::If {
            condition: Box::new(lower_expr(last_op, enum_root_index)),
            capture: Some(HirIfCapture {
                binding: last_binding,
            }),
            then_branch: Box::new(then_branch),
            else_branch: else_branch.as_ref().map(|e| Box::new(e.clone())),
        },
    };

    // Wrap remaining capturable operands (right-to-left, skipping the last)
    for i in (capture_start..m.saturating_sub(1)).rev() {
        let binding_idx = i - capture_start;
        let binding = bindings
            .get(binding_idx)
            .and_then(|b| b.as_ref())
            .map(|i| i.text.clone());
        result = HirExpr {
            span,
            kind: HirExprKind::If {
                condition: Box::new(lower_expr(operands[i], enum_root_index)),
                capture: Some(HirIfCapture { binding }),
                then_branch: Box::new(result),
                else_branch: None,
            },
        };
    }

    // Wrap plain bool conditions (right-to-left)
    for i in (0..capture_start).rev() {
        result = HirExpr {
            span,
            kind: HirExprKind::If {
                condition: Box::new(lower_expr(operands[i], enum_root_index)),
                capture: None,
                then_branch: Box::new(result),
                else_branch: else_branch.as_ref().map(|e| Box::new(e.clone())),
            },
        };
    }

    result
}

fn lower_expr(expr: &Expr, enum_root_index: &EnumRootIndex) -> HirExpr {
    let kind = match &expr.kind {
        ExprKind::Literal(literal) => HirExprKind::Literal(match literal {
            Literal::Integer(value) => HirLiteral::Integer(value.clone()),
            Literal::Float(value) => HirLiteral::Float(value.clone()),
            Literal::String(value) => HirLiteral::String(value.clone()),
            Literal::Char(value) => HirLiteral::Char(*value),
            Literal::Bool(value) => HirLiteral::Bool(*value),
            Literal::Null => HirLiteral::Null,
        }),
        ExprKind::Ident(ident) | ExprKind::BuiltinIdent(ident) => {
            HirExprKind::Ident(ident.text.clone())
        }
        ExprKind::Unary { expr, op } => HirExprKind::Unary {
            op: *op,
            expr: Box::new(lower_expr(expr, enum_root_index)),
        },
        ExprKind::Binary { left, right, op } => HirExprKind::Binary {
            op: *op,
            left: Box::new(lower_expr(left, enum_root_index)),
            right: Box::new(lower_expr(right, enum_root_index)),
        },
        ExprKind::Assign { target, value, op } => HirExprKind::Assign {
            op: *op,
            target: Box::new(lower_expr(target, enum_root_index)),
            value: Box::new(lower_expr(value, enum_root_index)),
        },
        ExprKind::Call(call) => HirExprKind::Call {
            callee: Box::new(lower_expr(&call.callee, enum_root_index)),
            args: call
                .args
                .iter()
                .map(|arg| HirCallArg {
                    name: arg.name.as_ref().map(|ident| ident.text.clone()),
                    value: lower_expr(&arg.value, enum_root_index),
                })
                .collect(),
        },
        ExprKind::FieldAccess { base, field } => HirExprKind::FieldAccess {
            base: Box::new(lower_expr(base, enum_root_index)),
            field: field.text.clone(),
        },
        ExprKind::DerefAccess { base } => HirExprKind::DerefAccess {
            base: Box::new(lower_expr(base, enum_root_index)),
        },
        ExprKind::Index { base, index } => HirExprKind::Index {
            base: Box::new(lower_expr(base, enum_root_index)),
            index: Box::new(lower_expr(index, enum_root_index)),
        },
        ExprKind::Slice(slice) => HirExprKind::Slice {
            base: Box::new(lower_expr(&slice.base, enum_root_index)),
            start: slice
                .start
                .as_ref()
                .map(|expr| Box::new(lower_expr(expr, enum_root_index))),
            end: slice
                .end
                .as_ref()
                .map(|expr| Box::new(lower_expr(expr, enum_root_index))),
            inclusive: slice.inclusive,
        },
        ExprKind::StructLiteral(lit) => {
            let root_type = lit.root_type.as_ref().map(|ident| ident.text.clone());
            let mut fields: Vec<(String, HirExpr)> = lit
                .fields
                .iter()
                .map(|field| {
                    (
                        field.name.text.clone(),
                        lower_expr(&field.value, enum_root_index),
                    )
                })
                .collect();
            if let Some(ref root_name) = root_type {
                let present: std::collections::BTreeSet<String> =
                    fields.iter().map(|(name, _)| name.clone()).collect();
                let prefix = (root_name.clone(), String::new());
                for ((struct_name, field_name), default_expr) in
                    enum_root_index.struct_field_defaults.range(prefix..)
                {
                    if struct_name != root_name {
                        break;
                    }
                    if !present.contains(field_name) {
                        fields.push((
                            field_name.clone(),
                            lower_expr(default_expr, enum_root_index),
                        ));
                    }
                }
            }
            HirExprKind::StructLiteral { root_type, fields }
        }
        ExprKind::TypeConstruct { ty_expr, fields } => {
            // Extract the type name from the expression if it's resolvable at compile time
            // (e.g., a plain identifier or a call bound to a named type alias).
            let root_type = match &ty_expr.kind {
                ExprKind::Ident(ident) => Some(ident.text.clone()),
                _ => None,
            };
            HirExprKind::StructLiteral {
                root_type,
                fields: fields
                    .iter()
                    .map(|field| {
                        (
                            field.name.text.clone(),
                            lower_expr(&field.value, enum_root_index),
                        )
                    })
                    .collect(),
            }
        }
        ExprKind::ArrayLiteral(elements) => HirExprKind::StructLiteral {
            root_type: None,
            fields: elements
                .iter()
                .enumerate()
                .map(|(idx, element)| (format!("__{idx}"), lower_expr(element, enum_root_index)))
                .collect(),
        },
        ExprKind::TupleLiteral(elements) => HirExprKind::StructLiteral {
            root_type: None,
            fields: elements
                .iter()
                .enumerate()
                .map(|(idx, element)| (format!("__{idx}"), lower_expr(element, enum_root_index)))
                .collect(),
        },
        ExprKind::EnumVariantConstruct(variant) => HirExprKind::EnumVariant {
            root: variant
                .root
                .as_ref()
                .map(|ident| ident.text.clone())
                .and_then(|root| enum_root_index.by_name.get(&root).cloned().or(Some(root)))
                .or_else(|| {
                    enum_root_index
                        .by_variant
                        .get(&variant.variant.text)
                        .cloned()
                }),
            variant: variant.variant.text.clone(),
            payload: variant
                .payload
                .iter()
                .map(|payload| lower_expr(payload, enum_root_index))
                .collect(),
        },
        ExprKind::Block(block) => HirExprKind::Block {
            body: {
                let mut body = Vec::new();
                for stmt in &block.statements {
                    match stmt {
                        crate::compiler::ast::Stmt::Binding(binding) => {
                            body.push(HirExpr {
                                kind: HirExprKind::Let {
                                    name: binding.name.text.clone(),
                                    mutable: binding.mutable,
                                    type_hint: binding.annotation.as_ref().map(type_expr_to_string),
                                    value: Box::new(lower_expr(&binding.value, enum_root_index)),
                                },
                                span: binding.span,
                            });
                        }
                        crate::compiler::ast::Stmt::Destructure(d) => {
                            lower_destructure_stmt(d, enum_root_index, &mut body);
                        }
                        crate::compiler::ast::Stmt::Expr(expr) => {
                            body.push(lower_expr(expr, enum_root_index));
                        }
                    }
                }
                if let Some(tail) = &block.tail_expr {
                    body.push(lower_expr(tail, enum_root_index));
                }
                body
            },
        },
        ExprKind::If(if_expr) => {
            let n_bindings = if_expr
                .capture
                .as_ref()
                .map(|c| c.bindings.len())
                .unwrap_or(0);
            let uses_and_chain = matches!(
                &if_expr.condition.kind,
                crate::compiler::ast::ExprKind::Binary {
                    op: crate::compiler::ast::BinaryOp::LogicalAnd,
                    ..
                }
            );
            if n_bindings > 1 || (n_bindings == 1 && uses_and_chain) {
                let capture = if_expr.capture.as_ref().unwrap();
                let then_branch = lower_expr(&if_expr.then_branch, enum_root_index);
                let else_branch = if_expr
                    .else_branch
                    .as_ref()
                    .map(|e| lower_expr(e, enum_root_index));
                return lower_multi_capture_if(
                    &if_expr.condition,
                    &capture.bindings,
                    then_branch,
                    else_branch,
                    enum_root_index,
                    expr.span,
                );
            }
            HirExprKind::If {
                condition: Box::new(lower_expr(&if_expr.condition, enum_root_index)),
                capture: if_expr.capture.as_ref().map(|capture| HirIfCapture {
                    binding: capture
                        .bindings
                        .first()
                        .and_then(|b| b.as_ref())
                        .map(|ident| ident.text.clone()),
                }),
                then_branch: Box::new(lower_expr(&if_expr.then_branch, enum_root_index)),
                else_branch: if_expr
                    .else_branch
                    .as_ref()
                    .map(|expr| Box::new(lower_expr(expr, enum_root_index))),
            }
        }
        ExprKind::Match(match_expr) => HirExprKind::Match {
            value: Box::new(lower_expr(&match_expr.scrutinee, enum_root_index)),
            arms: match_expr
                .arms
                .iter()
                .map(|arm| HirMatchArm {
                    pattern: lower_pattern(&arm.pattern.kind, enum_root_index),
                    guard: arm
                        .guard
                        .as_ref()
                        .map(|guard| lower_expr(guard, enum_root_index)),
                    value: lower_expr(&arm.value, enum_root_index),
                })
                .collect(),
        },
        ExprKind::For(for_expr) => HirExprKind::For(match for_expr {
            crate::compiler::ast::ForExpr::Infinite { body } => {
                crate::compiler::hir::HirForExpr::Infinite {
                    body: Box::new(lower_expr(body, enum_root_index)),
                }
            }
            crate::compiler::ast::ForExpr::WhileLike { condition, body } => {
                crate::compiler::hir::HirForExpr::WhileLike {
                    condition: Box::new(lower_expr(condition, enum_root_index)),
                    body: Box::new(lower_expr(body, enum_root_index)),
                }
            }
            crate::compiler::ast::ForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => crate::compiler::hir::HirForExpr::Range {
                start: Box::new(lower_expr(start, enum_root_index)),
                end: Box::new(lower_expr(end, enum_root_index)),
                inclusive: *inclusive,
                binding: binding.as_ref().map(|ident| ident.text.clone()),
                body: Box::new(lower_expr(body, enum_root_index)),
            },
            crate::compiler::ast::ForExpr::Iterate {
                iterable,
                binding,
                body,
            } => crate::compiler::hir::HirForExpr::Iterate {
                iterable: Box::new(lower_expr(iterable, enum_root_index)),
                binding: binding.as_ref().map(|ident| ident.text.clone()),
                body: Box::new(lower_expr(body, enum_root_index)),
            },
        }),
        ExprKind::Break(brk) => HirExprKind::Break {
            value: brk
                .value
                .as_ref()
                .map(|value| Box::new(lower_expr(value, enum_root_index))),
        },
        ExprKind::Continue { .. } => HirExprKind::Continue,
        ExprKind::Return { value } => HirExprKind::Return {
            value: value
                .as_ref()
                .map(|expr| Box::new(lower_expr(expr, enum_root_index))),
        },
        ExprKind::Defer(defer_expr) => HirExprKind::Defer {
            error_binding: defer_expr
                .error_binding
                .as_ref()
                .map(|ident| ident.text.clone()),
            body: Box::new(lower_expr(&defer_expr.body, enum_root_index)),
        },
        ExprKind::OptionalUnwrap { expr } => HirExprKind::OptionalUnwrap {
            value: Box::new(lower_expr(expr, enum_root_index)),
        },
        ExprKind::ErrorUnwrap { expr } => HirExprKind::ErrorUnwrap {
            value: Box::new(lower_expr(expr, enum_root_index)),
        },
        ExprKind::OrElse(or_else) => HirExprKind::OrElse {
            value: Box::new(lower_expr(&or_else.value, enum_root_index)),
            error_binding: or_else
                .error_binding
                .as_ref()
                .map(|ident| ident.text.clone()),
            fallback: Box::new(lower_expr(&or_else.fallback, enum_root_index)),
        },
        ExprKind::Use { path } => HirExprKind::Use { path: path.clone() },
        ExprKind::TypeLiteral(ty) => HirExprKind::TypeLiteral(type_expr_to_string(ty)),
        ExprKind::Comptime { expr } => HirExprKind::Comptime {
            expr: Box::new(lower_expr(expr, enum_root_index)),
        },
        ExprKind::Inline { expr } => HirExprKind::Inline {
            expr: Box::new(lower_expr(expr, enum_root_index)),
        },
        ExprKind::Fn(fn_expr) => {
            let body = match &fn_expr.body {
                crate::compiler::ast::FnBody::Block(block) => HirExpr {
                    kind: HirExprKind::Block {
                        body: {
                            let mut body = Vec::new();
                            for stmt in &block.statements {
                                match stmt {
                                    crate::compiler::ast::Stmt::Binding(binding) => {
                                        body.push(HirExpr {
                                            kind: HirExprKind::Let {
                                                name: binding.name.text.clone(),
                                                mutable: binding.mutable,
                                                type_hint: binding
                                                    .annotation
                                                    .as_ref()
                                                    .map(type_expr_to_string),
                                                value: Box::new(lower_expr(
                                                    &binding.value,
                                                    enum_root_index,
                                                )),
                                            },
                                            span: binding.span,
                                        });
                                    }
                                    crate::compiler::ast::Stmt::Destructure(d) => {
                                        lower_destructure_stmt(d, enum_root_index, &mut body);
                                    }
                                    crate::compiler::ast::Stmt::Expr(expr) => {
                                        body.push(lower_expr(expr, enum_root_index));
                                    }
                                }
                            }
                            if let Some(tail) = &block.tail_expr {
                                body.push(lower_expr(tail, enum_root_index));
                            }
                            body
                        },
                    },
                    span: expr.span,
                },
                crate::compiler::ast::FnBody::ArrowExpr(arrow_expr) => {
                    lower_expr(arrow_expr, enum_root_index)
                }
            };
            {
                let has_comp_param = fn_expr.params.iter().any(|p| {
                    p.comp
                        || matches!(p.ty.as_ref(), Some(ty) if matches!(&ty.kind, crate::compiler::ast::TypeExprKind::Named(n) if n.text == "any"))
                });
                let fn_kind = HirExprKind::Function {
                    params: fn_expr
                        .params
                        .iter()
                        .map(|param| param.name.text.clone())
                        .collect(),
                    param_types: fn_expr
                        .params
                        .iter()
                        .map(|param| param.ty.as_ref().map(type_expr_to_string))
                        .collect(),
                    param_defaults: fn_expr
                        .params
                        .iter()
                        .map(|param| {
                            param
                                .default_value
                                .as_ref()
                                .map(|default| lower_expr(default, enum_root_index))
                        })
                        .collect(),
                    has_explicit_return_type: fn_expr.return_type.is_some(),
                    body: Box::new(body),
                };
                // Functions with `comp` parameters must be inlined at every call site so that
                // the concrete argument type is visible inside the body for `comp match $typeof`,
                // `$fields`, `inline for`, etc.
                if has_comp_param {
                    HirExprKind::Inline {
                        expr: Box::new(HirExpr {
                            kind: fn_kind,
                            span: expr.span,
                        }),
                    }
                } else {
                    fn_kind
                }
            }
        }
    };

    HirExpr {
        kind,
        span: expr.span,
    }
}

fn lower_pattern(pattern: &PatternKind, enum_root_index: &EnumRootIndex) -> HirPattern {
    match pattern {
        PatternKind::Wildcard => HirPattern::Wildcard,
        PatternKind::IdentBind(ident) => HirPattern::IdentBind(ident.text.clone()),
        PatternKind::Literal(lit) => HirPattern::Literal(match lit {
            PatternLiteral::Integer(v) => HirLiteral::Integer(v.clone()),
            PatternLiteral::Float(v) => HirLiteral::Float(v.clone()),
            PatternLiteral::String(v) => HirLiteral::String(v.clone()),
            PatternLiteral::Char(v) => HirLiteral::Char(*v),
            PatternLiteral::Bool(v) => HirLiteral::Bool(*v),
            PatternLiteral::Null => HirLiteral::Null,
        }),
        PatternKind::EnumVariant {
            root,
            variant,
            bindings,
        } => HirPattern::EnumVariant {
            root: root
                .as_ref()
                .map(|ident| ident.text.clone())
                .and_then(|root| enum_root_index.by_name.get(&root).cloned().or(Some(root)))
                .or_else(|| enum_root_index.by_variant.get(&variant.text).cloned()),
            variant: variant.text.clone(),
            bindings: bindings.iter().map(|ident| ident.text.clone()).collect(),
        },
        PatternKind::Range {
            start,
            end,
            inclusive,
        } => {
            let Some(start_lit) = lower_pattern_literal(&start.kind) else {
                return HirPattern::Other;
            };
            let Some(end_lit) = lower_pattern_literal(&end.kind) else {
                return HirPattern::Other;
            };
            HirPattern::RangeLiteral {
                start: start_lit,
                end: end_lit,
                inclusive: *inclusive,
            }
        }
        PatternKind::Typed { pattern, .. } => lower_pattern(&pattern.kind, enum_root_index),
        PatternKind::TypeLiteral(ty) => HirPattern::TypeLiteral(type_expr_to_string(ty)),
    }
}

fn lower_pattern_literal(pattern: &PatternKind) -> Option<HirLiteral> {
    match pattern {
        PatternKind::Literal(PatternLiteral::Integer(v)) => Some(HirLiteral::Integer(v.clone())),
        PatternKind::Literal(PatternLiteral::Float(v)) => Some(HirLiteral::Float(v.clone())),
        PatternKind::Literal(PatternLiteral::String(v)) => Some(HirLiteral::String(v.clone())),
        PatternKind::Literal(PatternLiteral::Char(v)) => Some(HirLiteral::Char(*v)),
        PatternKind::Literal(PatternLiteral::Bool(v)) => Some(HirLiteral::Bool(*v)),
        PatternKind::Literal(PatternLiteral::Null) => Some(HirLiteral::Null),
        _ => None,
    }
}

/// Desugar `{a, b} := expr` into:
///   `__destruct_N := expr`
///   `a := __destruct_N.a`
///   `b := __destruct_N.b`
fn lower_destructure_stmt(
    d: &DestructureBinding,
    enum_root_index: &EnumRootIndex,
    body: &mut Vec<HirExpr>,
) {
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    let tmp_name = format!("__destruct_{id}");

    // Bind the RHS to a temp.
    body.push(HirExpr {
        kind: HirExprKind::Let {
            name: tmp_name.clone(),
            mutable: false,
            type_hint: None,
            value: Box::new(lower_expr(&d.value, enum_root_index)),
        },
        span: d.span,
    });

    // Bind each name via field access on the temp.
    for dn in &d.names {
        body.push(HirExpr {
            kind: HirExprKind::Let {
                name: dn.name.text.clone(),
                mutable: dn.mutable,
                type_hint: None,
                value: Box::new(HirExpr {
                    kind: HirExprKind::FieldAccess {
                        base: Box::new(HirExpr {
                            kind: HirExprKind::Ident(tmp_name.clone()),
                            span: d.span,
                        }),
                        field: dn.name.text.clone(),
                    },
                    span: dn.name.span,
                }),
            },
            span: dn.name.span,
        });
    }
}

fn type_expr_to_string(type_expr: &crate::compiler::ast::TypeExpr) -> String {
    match &type_expr.kind {
        TypeExprKind::Named(ident) => ident.text.clone(),
        TypeExprKind::Applied { callee, args } => {
            let rendered = args
                .iter()
                .map(type_expr_to_string)
                .collect::<Vec<_>>()
                .join(", ");
            format!("{}({})", callee.text, rendered)
        }
        TypeExprKind::Optional { inner } => format!("?{}", type_expr_to_string(inner)),
        TypeExprKind::Pointer { inner } => format!("*{}", type_expr_to_string(inner)),
        TypeExprKind::Slice { element } => format!("[]{}", type_expr_to_string(element)),
        TypeExprKind::Array { element, .. } => format!("[?]{}", type_expr_to_string(element)),
        TypeExprKind::Errorable { ok, errors } => {
            let list = errors
                .iter()
                .map(|ident| ident.text.clone())
                .collect::<Vec<_>>()
                .join(",");
            format!("{}!{}", type_expr_to_string(ok), list)
        }
        TypeExprKind::Struct(struct_ty) => {
            let fields = struct_ty
                .fields
                .iter()
                .map(|field| format!("{}:{}", field.name.text, type_expr_to_string(&field.ty)))
                .collect::<Vec<_>>()
                .join(",");
            if struct_ty.packed {
                format!("packed struct{{{fields}}}")
            } else {
                format!("struct{{{fields}}}")
            }
        }
        TypeExprKind::Enum(enum_ty) => {
            let variants = enum_ty
                .variants
                .iter()
                .map(|variant| {
                    if let Some(payload) = &variant.payload {
                        format!("{}:{}", variant.name.text, type_expr_to_string(payload))
                    } else {
                        variant.name.text.clone()
                    }
                })
                .collect::<Vec<_>>()
                .join(",");
            if let Some(repr) = &enum_ty.repr {
                format!("enum({}){{{variants}}}", type_expr_to_string(repr))
            } else {
                format!("enum{{{variants}}}")
            }
        }
        TypeExprKind::Function(fn_ty) => {
            let params = fn_ty
                .params
                .iter()
                .map(|param| type_expr_to_string(&param.ty))
                .collect::<Vec<_>>()
                .join(",");
            let ret = type_expr_to_string(&fn_ty.return_type);
            format!("({params})->{ret}")
        }
    }
}
