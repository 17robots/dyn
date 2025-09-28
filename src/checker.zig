const std = @import("std");
const ast = @import("ast.zig");
const Token = @import("token.zig").Token;
const Span = @import("token.zig").Span;
const DiagnosticEmitter = @import("diagnostic.zig").DiagnosticEmitter;
const SourceManager = @import("source.zig").SourceManager;
const symbol = @import("symbol.zig");
const Symbol = symbol.Symbol;
const SymbolKind = symbol.SymbolKind;
const ScopeStack = symbol.ScopeStack;
const Mutability = symbol.Mutability;
const TypeTable = symbol.TypeTable;
const Type = symbol.Type;
const TagType = symbol.TagType;

pub const Checker = struct {
    allocator: std.mem.Allocator,
    diags: *DiagnosticEmitter,
    sources: *SourceManager,
    scopes: *ScopeStack,
    types: *TypeTable,

    pub fn init(a: std.mem.Allocator, d: *DiagnosticEmitter, sm: *SourceManager, sc: *ScopeStack, t: TypeTable) Checker {
        var c = Checker{ .allocator = a, .diags = d, .sources = sm, .scopes = sc, .types = t };
        _ = try c.types.add(.{ .tag = .void, .payload = Type.payload.void} );
        _ = try c.types.add(.{ .tag = .boolean, .payload = Type.payload.boolean} );
        _ = try c.types.add(.{ .tag = .int, .payload = Type.payload.int} );
        _ = try c.types.add(.{ .tag = .float, .payload = Type.payload.float} );
        _ = try c.types.add(.{ .tag = .string, .payload = Type.payload.string} );
        _ = try c.types.add(.{ .tag = .null, .payload = Type.payload.null} );
        _ = try c.types.add(.{ .tag = .undefined, .payload = Type.payload.undefined} );
        _ = try c.types.add(.{ .tag = .type, .payload = Type.payload.type} );
        _ = try c.scopes.push(.global);
        return c;
    }
    pub fn deinit(s: *Checker) void {
        s.scopes.deinit();
        s.types.deinit();
    }
    pub fn check(s: *Checker, file_id: u32, n: ast.Node) void {
        switch(n.type) {
            .program => |p| {
                for(p.declarations.items) |d| s.collectTopLevelDecl(file_id, d);
                for(p.declarations.items) |d| s.checkTopLevelDecl(file_id, d);
            },
            else => {} // throw error
        }
    }
    fn collectTopLevelDecl(s: *Checker, file_id: u32, n: ast.Node) void {
        switch(n.type) {
            .declaration => |d| {
                const name = d.name.type.identifier; // should be this or it dies
                const sym = Symbol{ .name = name, .kind = .@"var", .span = n.span, .mutability = if(d.mut) .mutable else .immutable };
                s.scopes.delcare(sym, s.diags, file_id);
            },
            else => {}, // error
        }
    }
    fn checkTopLevelDecl(s: *Checker, file_id: u32, n: ast.Node) void {
        switch(n.type) {
            .declaration => |d| {
                const name = d.name.type.identifier;
                var sym = s.scopes.lookup(name) orelse {
                    const s2 = Symbol{ .name = name, .kind = .@"var", .span = n.span };
                    s.scopes.delcare(s2, s.diags, file_id);
                };
                const ty_id: u32 = if(d.type) |tptr| s.typeOfTypeExpr(file_id, tptr.*) else s.typesIDUnknown();
                const val_ty: ?u32 = if(d.val) |v| s.typeOfExpr(file_id, v.*) else null;

                if(d.type != null and val_ty != null) {
                    if(!s.unify(ty_id, val_ty.?)) s.diags.emit(file_id, n.span, .err, "Type mismatch in declaration '{s}'", .{name});
                    sym.type_id = ty_id;
                } else if(d.type != null) { sym.type_id = ty_id; }
                else if (val_ty != null) { sym.type_id = val_ty; }
                else s.diags.emit(file_id, n.span, .err, "Declaration '{s}' requires a type or value", .{name});
                if(d.val) |v| {
                    if(v.type == .function or v.type == .function_type) {
                        sym.kind = .func;
                    }
                }
            },
            else => {},
        }
    }
    fn typeOfExpr(s: *Checker, file_id: u32, n: ast.Node) u32 {
        return switch(n.type) {
            .literal => |lit| switch(lit.kind) {},
            .identifier => |i| {
                const sym = s.scopes.lookup(i) orelse {
                    s.diags.emit(file_id, n.span, .err, "Undefined identifier '{s}'", .{i});
                    return s.typesIDUnknown();
                };
                return sym.type_id orelse s.typesIDUnknown();
            },
            .unary => |u| {
                const b = s.typeOfExpr(file_id, u.b.*);
                return b;
            },
            .binary => |b| {
                const lt = s.typeOfExpr(file_id, b.a.*);
                const rt = s.typeOfExpr(file_id, b.b.*);
                // check that op is valid on left and right types
                if(!s.unify(lt, rt)) s.diag.emit(file_id, n.span, "Left type '{s}' not equal to right type '{s}'", .{});
                if(!s.compatibleOp(lt, rt)) s.diag.emit(file_id, n.span, "Type '{s}' not usable with operand {any}", {});
                return lt;
            },
            .call => |c| {
                const fnty = s.typeOfExpr(file_id, c.name.*);
                _ = fnty;
                // check args vs params
                // return result type on success, unknown on failure;
                return s.typesIDUnknown();
            },
            .array_init => {
                // infer arr element type from elements or return empty if unknown from items (like when [])
                // also ensure that all types of elems are the same, error if not
            },
            .struct_init => {
                // if name present, validate fields if name known
                // return unknown if not
                return s.typesIDUnknown();
            },
            .range_expression => |re| {
                // ranges are based on the left and the right vals, which need to be the same
                const lt = s.typeOfExpr(file_id, re.a.*);
                const rt = s.typeOfExpr(file_id, re.b.*);
                if(!s.unify(lt, rt)) {
                    s.diag.emit(file_id, n.span, "Type '{s}' not equal to type '{s}'", .{});
                    return s.typesIDUnknown();
                }
                // verify types can use range vals, if not error and return empty
                return lt;
            },
            .if_expression => |if_| {
                const bt = s.typeOfExpr(if_.body.*);
                const et = s.typeOfExpr(if_.else_body.*);
                if(!s.unify(bt, et)) {
                    s.diag.emit(file_id, n.span, "Type '{s}' not equal to type '{s}'", .{});
                    return s.typesIDUnknown();
                }
            },
            .match => {
                // compute common result type across arms; check patterns
                return s.typesIDUnknown();
            },
            else => s.typesIDUnknown(),
        };
    }
    fn typeOfTypeExpr(s: *Checker, file_id: u32, n: ast.Node) u32 {
        return switch(n.type) {
            .identifier => blk: {
                // resolve a type alias/symbol
                break :blk s.typesIDUnknown();
            },
            .pointer_type => |pt| blk: {
                const inner = s.typeOfTypeExpr(file_id, pt.expression.*);
                break :blk s.typesAdd(.{ .tag = .pointer, .payload = .{ .pointer = inner }});
            },
            .optional_type => |ot| blk: {
                const inner = s.typeOfTypeExpr(file_id, ot.expression.*);
                break :blk s.typesAdd(.{ .tag = .optional, .payload = .{ .optional = inner }});
            },
            .array_type => |at| blk: {
                const inner = s.typeOfTypeExpr(file_id, at.expression.*);
                break :blk s.typesAdd(.{ .tag = .slice, .payload = .{ .clice = inner }});
            },
            .function_type => |ft| blk: {
                var param_ids = std.ArrayList(u32).empty;
                defer param_ids.deinit(s.allocator);
                for(ft.parameters.items) |p| param_ids.append(s.allocator, s.typeOfTypeExpr(file_id, p)) catch {};
                const res = if(ft.result) |r| s.typeOfTypeExpr(file_id, r.*) else s.typesId(.@"void");
                break :blk s.typesAdd(.{ .tag = .function, .payload = .{ .function = .{ .params = param_ids.toOwnedSlice(), .result = res, .is_inline = false }}});
            },
            .type => s.typesId(.type),
            else => s.typesIDUnknown(),
        };
    }
    fn unify(s: *Checker, a: u32, b: u32) bool {
        if(a == b) return true;
        if(s.types.get(a).tag == .unknown or s.types.get(b).tag == .unknown) return true;
        return false;
    }
    fn compatibleOp(s: *Checker, a: u32, b: u32, op: ast.Node) bool {
        switch(op.type) { // boolean types always return true because it can be compatible with any other boolean op
            .andand, .oror, .eqeq => return true,
            else => {
                const ta = s.types.get(a).tag;
                const tb = s.types.get(b).tag;
                return (ta == .int or ta == .float) and (tb == .int or tb == .float);
            }
        }
    }
    fn typesId(s: *Checker, tag: TagType) u32 {
        // return the index of preloaded primitive types (store ids at init in real code)
        // for brevity return unknown here
        switch(tag) {}
        return s.typesIDUnknown();
    }
    fn typesIDUnknown(s: *Checker) u32 {
        return s.typesAdd( .{.tag = .unknown, .payload = Type.payload.unknown});
    }
};
