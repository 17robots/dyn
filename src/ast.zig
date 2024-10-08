const std = @import("std");
const token = @import("token.zig");
const TokenType = token.TokenType;

// useblock,
// usedeclaration,
// functiondeclaration,
// functioncall,
// variabledeclaration,
// literal,
// typeliteral,
// optionaltype,
// pointertype,
// arraytype,
// variablereference,
// pointerdereference,
// condition,
// block,
// match,
// matchbranch,
// deferstatement,
// breakstatement,
// returnstatement,
// loop,
// forstatement,
// rangeclause,
// capture,
// loopmodifier,
// arrayliteral,
// structliteral,
// callargs,
// declargs,
// errordecl,
// errormember,
// errortype,
// trystatement,
// catchstatement,
// uniondeclaration,
// unionmember,
// unionliteral,
// selectionexpression,

pub const LiteralType = enum {};

pub const AstNode = union(enum) { Program: struct { declarations: []AstNode }, ModuleDeclaration: struct { name: []const u8 }, UseDeclaration: struct { modules: []struct { import: []const u8, alias: ?[]const u8 } }, StructDefinition: struct {
    name: []const u8,
    genericParams: ?[]AstNode,
    members: []AstNode,
}, EnumDefinition: struct {
    name: []const u8,
    variants: []const []const u8,
}, UnionDefinition: struct {
    name: []const u8,
    isErrorUnion: bool,
    fields: []AstNode,
}, ErrorDefinition: struct {
    name: []const u8,
    variants: []AstNode,
}, TypeDefinition: struct {
    name: []const u8,
    genericParams: []AstNode,
    aliasedType: AstNode,
}, FunctionDefinition: struct {
    inlineFunction: bool,
    returnType: AstNode,
    name: []const u8,
    parameters: []AstNode,
    body: AstNode,
}, MethodDefinition: struct {
    inlineMethod: bool,
    returnType: AstNode,
    name: []const u8,
    parameters: []AstNode,
    body: AstNode,
}, Parameter: struct {
    mutable: bool,
    isComptime: bool,
    paramType: ?AstNode,
    name: []const u8,
}, FieldDeclaration: struct {
    fieldType: AstNode,
    names: []const []const u8,
    defaultValue: ?AstNode,
}, Block: struct { statements: []AstNode }, IfStatement: struct {
    condition: AstNode,
    capture: ?[]const u8,
    thenBranch: AstNode,
    elseBranch: ?AstNode,
}, LoopStatement: struct { body: AstNode }, ForStatement: struct {
    inlineFor: bool,
    iterable: AstNode,
    loopVar: []const u8,
    update: ?AstNode,
    body: AstNode,
}, MatchStatement: struct {
    value: AstNode,
    arms: []AstNode,
}, MatchArm: struct {
    pattern: AstNode,
    guard: ?AstNode,
    body: AstNode,
}, EnumVariant: struct { variant: []const u8 }, RangePattern: struct {
    start: AstNode,
    end: AstNode,
}, WildCard: struct {}, DeferError: struct {
    errorVar: []const u8,
    body: AstNode,
}, Defer: struct {
    body: AstNode,
}, InlineBlock: struct {
    body: AstNode,
}, VariableDeclaration: struct {
    mutable: bool,
    isComptime: bool,
    varType: AstNode,
    name: []const u8,
    initializer: ?AstNode,
}, ExpressionStatement: struct {
    expression: AstNode,
}, Assignment: struct {
    target: AstNode,
    operator: TokenType,
    value: AstNode,
}, Binary: struct {
    left: AstNode,
    operator: TokenType,
    right: AstNode,
}, Unary: struct {
    operator: TokenType,
    right: AstNode,
}, Literal: struct {
    type: LiteralType,
    value: []const u8,
}, Variable: struct { name: []const u8 }, FunctionCall: struct {
    callee: AstNode,
    args: []AstNode,
}, MemberAccess: struct {
    obj: AstNode,
    member: []const u8,
}, IndexAccess: struct {
    object: AstNode,
    Index: AstNode,
}, Range: struct { start: AstNode, end: AstNode }, NullableType: struct { type: AstNode }, PointerType: struct { type: AstNode }, Type: struct { type: []const u8 }, ArrayType: struct { type: AstNode }, StructField: struct { field_type: AstNode, name: [][]const u8 }, StructMethod: struct { return_type: AstNode, name: []const u8, parameters: []AstNode, body: AstNode } };
