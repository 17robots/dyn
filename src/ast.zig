const Span = @import("token.zig").Span;
const std = @import("std");

pub const NodeId = u32;
pub const NullNode: NodeId = std.math.maxInt(NodeId);

pub const UnaryOp = enum {
    neg,
    not,
    complement,
};

pub const BinaryOp = enum {
    mul,
    div,
    mod,
    add,
    sub,
    shl,
    shr,
    bit_and,
    bit_xor,
    bit_or,
    lt,
    lte,
    gt,
    gte,
    eqeq,
    neq,
    land,
    lor,
    range,
    rangeq,
};

pub const AssignOp = enum {
    eq,
    addeq,
    subeq,
    muleq,
    diveq,
    modeq,
    andeq,
    pipeq,
    xoreq,
    shleq,
    shreq,
    compleq,
};

pub const MatchArm = struct {
    kind: PatternKind,
    pat_start: NodeId,
    pat_end: NodeId,
    pat_payload: NodeId,
    inclusive: bool,
    has_pat_payload: bool,
    body: NodeId,
    capture_span: Span,
    has_capture: bool,
    span: Span,
};

pub const PatternKind = enum {
    wildcard,
    expr,
    range,
};

pub const Node = struct {
    tag: Tag,
    span: Span,
    data: Data,

    pub const Tag = enum {
        identifier,
        int_lit,
        float_lit,
        string_lit,
        char_lit,
        type_lit,
        unary,
        binary,
        assign,
        call,
        field,
        index,
        slice,
        if_expr,
        match_expr,
        block,
        decl,
        module_decl,
        fn_expr,
        param,
        use_expr,
        struct_expr,
        enum_expr,
        for_stmt,
        break_stmt,
        continue_stmt,
        defer_stmt,
        labeled_block,
        address_of,
        ptr_type,
        unwrap_optional,
        unwrap_error,
        deref,
        err,
    };

    pub const Data = union {
        none: void,
        unary: struct {
            op: UnaryOp,
            rhs: NodeId,
        },
        binary: struct {
            op: BinaryOp,
            lhs: NodeId,
            rhs: NodeId,
        },
        assign: struct {
            op: AssignOp,
            lhs: NodeId,
            rhs: NodeId,
        },
        call: struct {
            callee: NodeId,
            arg_start: u32,
            arg_count: u32,
        },
        field: struct {
            object: NodeId,
            field_span: Span,
        },
        index: struct {
            object: NodeId,
            index: NodeId,
        },
        slice: struct {
            object: NodeId,
            start: NodeId,
            end: NodeId,
            has_start: bool,
            has_end: bool,
            inclusive: bool,
        },
        if_expr: struct {
            cond: NodeId,
            then_expr: NodeId,
            else_expr: NodeId,
            has_else: bool,
            bind_span: Span,
            has_bind: bool,
        },
        match_expr: struct {
            subject: NodeId,
            arm_start: u32,
            arm_count: u32,
        },
        block: struct {
            item_start: u32,
            item_count: u32,
        },
        decl: struct {
            name_start: u32,
            name_count: u32,
            type_node: NodeId,
            init_node: NodeId,
            is_mut: bool,
            has_type: bool,
            has_init: bool,
            is_define: bool,
            is_pub: bool,
        },
        module_decl: struct {
            name_span: Span,
        },
        use_expr: struct {
            path_span: Span,
        },
        fn_expr: struct {
            param_start: u32,
            param_count: u32,
            ret_node: NodeId,
            body: NodeId,
            has_ret: bool,
            is_errorable: bool,
            concise: bool,
        },
        aggregate: struct {
            item_start: u32,
            item_count: u32,
        },
        param: struct {
            name_start: u32,
            name_count: u32,
            type_node: NodeId,
            default_node: NodeId,
            has_type: bool,
            has_default: bool,
            is_comp: bool,
        },
        for_stmt: struct {
            cond: NodeId,
            body: NodeId,
            capture_span: Span,
            has_capture: bool,
            is_infinite: bool,
        },
        break_stmt: struct {
            value: NodeId,
            has_value: bool,
            label_span: Span,
            has_label: bool,
        },
        continue_stmt: struct {
            label_span: Span,
            has_label: bool,
        },
        defer_stmt: struct {
            value: NodeId,
        },
        labeled_block: struct {
            label_span: Span,
            body: NodeId,
        },
        one: struct {
            child: NodeId,
        },
        ptr_type: struct {
            child: NodeId,
            mutable: bool,
        },
    };
};
