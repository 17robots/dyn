const token = @import("token.zig");
const TokenType = token.TokenType;

pub const LiteralType = enum {
    int,
    float,
    string,
    underscore,
};

pub const AstNode = union(enum) { Program: struct {
    declarations: []*const AstNode,
    pub_declarations: []*const AstNode,
}, ModuleDeclaration: struct {
    name: []const u8,
}, UseDeclaration: struct {
    modules: []struct {
        import: []const u8,
        alias: ?[]const u8,
    },
}, StructDefinition: struct {
    name: []const u8,
    genericParams: ?[]*const AstNode,
    members: []*const AstNode,
}, EnumDefinition: struct {
    name: []const u8,
    variants: []*const AstNode,
}, ErrorDefinition: struct {
    name: []const u8,
    variants: []*const AstNode,
}, TypeDefinition: struct {
    name: []const u8,
    aliasedType: *const AstNode,
}, FunctionDefinition: struct {
    inlineFunction: bool,
    returnType: *const AstNode,
    name: []const u8,
    parameters: []*const AstNode,
    body: *const AstNode,
}, FunctionLiteral: struct {
    function_type: *const AstNode,
    parameters: []*const AstNode,
    body: *const AstNode,
}, FunctionType: struct {
    function_type: *const AstNode,
    parameters: *const AstNode,
}, Parameter: struct {
    mutable: bool,
    isComptime: bool,
    paramType: ?*const AstNode,
    name: []const u8,
}, FieldDeclaration: struct {
    fieldType: *const AstNode,
    names: []const []const u8,
    defaultValue: ?*const AstNode,
}, Block: struct {
    statements: []*const AstNode,
}, IfStatement: struct {
    condition: *const AstNode,
    capture: ?[]const u8,
    thenBranch: *const AstNode,
    elseBranch: ?*const AstNode,
}, WhileStatement: struct {
    inlineWhile: bool,
    condition: *const AstNode,
    body: *const AstNode,
}, ForStatement: struct {
    inlineFor: bool,
    iterable: *const AstNode,
    loopVar: []const u8,
    update: ?*const AstNode,
    body: *const AstNode,
}, MatchStatement: struct {
    value: *const AstNode,
    arms: []*const AstNode,
}, MatchArm: struct {
    pattern: []*const AstNode,
    body: *const AstNode,
}, EnumVariant: struct {
    variant_type: ?*const AstNode,
    variant: []const u8,
}, ErrorVariant: struct {
    variant_type: ?*const AstNode,
    variant: []const u8,
}, RangePattern: struct {
    start: *const AstNode,
    end: *const AstNode,
}, WildCard: struct {}, DeferError: struct {
    errorVar: []const u8,
    body: *const AstNode,
}, Defer: struct {
    body: *const AstNode,
}, InlineBlock: struct {
    body: *const AstNode,
}, VariableDeclaration: struct {
    mutable: bool,
    varType: *const AstNode,
    name: []const u8,
    initializer: ?*const AstNode,
}, ExpressionStatement: struct {
    expression: *const AstNode,
}, StatementExpression: struct {
    statement: *const AstNode,
}, Assignment: struct {
    target: *const AstNode,
    value: *const AstNode,
}, Binary: struct {
    left: *const AstNode,
    operator: TokenType,
    right: *const AstNode,
}, LogicalBinary: struct {
    left: *const AstNode,
    operator: TokenType,
    right: *const AstNode,
}, Unary: struct {
    operator: TokenType,
    right: *const AstNode,
}, LogicalUnary: struct {
    operator: TokenType,
    right: *const AstNode,
}, Literal: struct {
    type: LiteralType,
    value: []const u8,
}, Variable: struct {
    name: []const u8,
}, FunctionCall: struct {
    callee: *const AstNode,
    args: []*const AstNode,
}, MemberAccess: struct {
    obj: *const AstNode,
    member: []const u8,
}, IndexAccess: struct {
    object: *const AstNode,
    index: *const AstNode,
}, Range: struct {
    start: *const AstNode,
    end: *const AstNode,
}, NullableType: struct {
    type: *const AstNode,
}, PointerType: struct {
    type: *const AstNode,
}, Type: struct {
    type: []const u8,
}, ArrayType: struct {
    type: *const AstNode,
}, StructField: struct {
    field_type: *const AstNode,
    name: [][]const u8,
}, StructMethod: struct {
    return_type: *const AstNode,
    name: []const u8,
    parameters: []*const AstNode,
    body: *const AstNode,
}, ErrorType: struct {
    core_type: *const AstNode,
    error_type: []const u8,
}, Grouping: struct {
    expr: *const AstNode,
}, Identifier: struct {
    value: []const u8,
}, Capture: struct {
    captured_var: []const u8,
} };
