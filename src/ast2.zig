const std = @import("std");
const Span = @import("token.zig").Span;

pub const Node = struct {
    type: NodeType,
    span: Span,
    left: ?*Node,
    right: ?*Node,
};

pub const NodeType = union(enum(u8)) {
    add: void, // left, right
    addeq: void, // left, right
    @"and": void, // left, right
    andand: void, // left, right
    andeq: void, // left, right,
    arm: void, // left, pair(left, right)
    array_index: void, // left, right
    array_init: void, // left, nil
    array_type: void, // left, right
    bang: void, // left?, right
    bangeq: void, // left, right
    block: void, // left (label), right
    boolean: []const u8,
    break_expr: void, // left (label), right
    call: void, // left, right
    capture: void, // left (mut), right
    catch_: void, // left (capture), right
    char: []const u8,
    comp: void, // left, nil
    @"continue": void, // left (label), nil
    declaration: void, // left: pair(left (pub), right (mut)), right: pair(type, val)
    defer_statement: void, // left (capture), right block
    div: void, // left, right
    diveq: void, // left, right
    enum_: void, // left (tag), right pair(member, pair(...))
    enum_err_init: void, // left (name), right: val
    eq: void, // left, right
    eqeq: void, // left, right
    error_: void, // nil, right pair(member, pair(...))
    error_union_type: void, // left: type, right: pair(type)
    float: []const u8,
    for_: void, // left: pair(inline, expressions), right: pair(captures, body)
    function: void, // left: pair(inline, parameters), right: pair(result, body)
    fn_param: void, // left: name list, right: type
    fn_type: void, // left: params, right: result
    grouped: void, // left: expr, nil
    gt: void, // left, right
    gte: void, // left, right
    identifier: []const u8, // nil, nil
    if_expression, // left: prefix, right: pair(body, else_body)
    if_prefix, // left: expression, right: capture
    if_statement, // left: expression, right: pair(body, else_body)
    int: []const u8,
    lt: void, // left, right
    lte: void, // left, right
    match: void, // left: expression, right pair(arm, pair(...))
    member: void, // left: names, right: pair(type, val)
    member_access: void, // left: name, // right: member
    mod: void, // left, right
    modeq: void, // left, right
    mul: void, // left?, right
    muleq: void, // left, right
    mut: void, // nil, nil
    null: void, // nil, nil
    nullish: void, // left, right
    optional_deref: void, // left: expr, nil
    optional_type: void, // left: expr, nil
    @"or": void, // left, right
    oreq: void, // left, right
    oror: void, // left, right
    pair: void, // left, right
    pointer_deref: void, // left: expr, nil
    pointer_type: void, // left: expr, nil
    program: void, // left: pair(decl, pair(...)), nil
    pub_: void, // nil, nil
    range: void, // left, right
    return_: void, // left: expr, nil
    string: []const u8,
    struct_: void, // left: pair(member, pair(...)), nil
    struct_init: void, // left: name, right: inits
    struct_init_member: void, // left: name, right: val
    sub: void, // left?, right
    subeq: void, // left, right
    try_: void, // left: expr, nil
    type: void, // nil, nil
    undefined: void, // nil, nil
    underscore: void, // nil, nil
    use: void, // left: string, nil
    while_: void, // left: pair(expr, capture), right: body
    xor: void, // left?, right
    xoreq: void, // left, right
};
