/// <reference types="tree-sitter-cli/dsl" />

const PREC = {
  ASSIGN: 1,
  LOGICAL_OR: 2,
  LOGICAL_AND: 3,
  EQUALITY: 4,
  RELATIONAL: 5,
  BIT_OR: 6,
  BIT_XOR: 7,
  BIT_AND: 8,
  SHIFT: 9,
  ADD: 10,
  MUL: 11,
  PREFIX: 12,
  POSTFIX: 13,
};
const commaSep = (rule) =>
  optional(seq(rule, repeat(seq(",", rule)), optional(",")));
const commaSep1 = (rule) => seq(rule, repeat(seq(",", rule)));
module.exports = grammar({
  name: "dyn",
  extras: ($) => [/\s/, $.comment],
  externals: ($) => [$._trailing_float],
  word: ($) => $.identifier,
  conflicts: ($) => [
    [$.use],
    [$.primary, $.struct_literal],
    [$.field_type, $.primary],
    [$.field_type, $.primary, $.struct_literal],
    [$.array_type, $.array_literal],
    [$.array_type, $.literal],
    [$.statement, $.primary],
    [$.statement, $.expression],
    [$.defer, $.primary],
    [$.defer, $.expression],
  ],
  rules: {
    source_file: ($) => repeat(choice($.target_directive, $.link_directive, $.declaration)),
    target_directive: ($) =>
      seq(token("#target"), "(", commaSep1($.target_condition), ")"),
    target_condition: ($) => seq($.identifier, ":", choice($.identifier, $.number_)),
    link_directive: ($) =>
      seq(token("#link"), "(", field("library", $.string_), ")"),
    declaration: ($) =>
      choice(
        $.use,
        seq(
          optional(token("pub")),
          choice(
            $.const_variable,
            $.struct,
            $.enum,
            $.fn,
            $.extern_fn,
            $.extern_variable,
            $.type_alias,
            $.variable,
          ),
        ),
      ),
    // Keep both interpretations until the next token distinguishes an alias
    // from a following global declaration (newlines are ordinary whitespace).
    use: ($) =>
      seq(token("use"), field("path", $.string_), optional(field("alias", $.identifier))),
    variable: ($) =>
      seq(
        $.identifier,
        choice(
          $.type_qualifier,
          seq(":", $.type, "=", $.expression),
          seq(":=", $.expression),
        ),
      ),
    const_variable: ($) => seq(token("const"), $.variable),
    type_alias: ($) =>
      seq(
        optional(token("distinct")),
        token("type"),
        $.identifier,
        "=",
        $.type,
      ),
    struct: ($) =>
      seq(
        optional(token("packed")),
        token("struct"),
        $.identifier,
        "{",
        commaSep($.struct_member),
        "}",
      ),
    struct_member: ($) =>
      seq(
        $.identifier,
        repeat(seq(",", $.identifier)),
        $.type_qualifier,
        optional(seq("=", $.expression)),
      ),
    enum: ($) =>
      seq(
        token("enum"),
        optional(seq("(", choice($.primitive, $.field_type), ")")),
        $.identifier,
        "{",
        commaSep($.enum_member),
        "}",
      ),
    enum_member: ($) =>
      seq(
        $.identifier,
        optional($.type_qualifier),
        optional(seq("=", $.expression)),
      ),
    fn: ($) =>
      seq(
        token("fn"),
        field("name", $.identifier),
        "(",
        commaSep(choice($.fn_param, $.variadic_param)),
        ")",
        optional($.type),
        $.block,
      ),
    extern_fn: ($) =>
      prec.right(
        seq(
          token("extern"),
          token("fn"),
          field("name", $.identifier),
          optional(field("link_name", $.string_)),
          "(",
          choice(
            seq(commaSep1($.fn_param), optional(seq(",", optional($.variadic)))),
            optional($.variadic),
          ),
          ")",
          optional($.type),
        ),
      ),
    extern_variable: ($) =>
      seq(
        token("extern"),
        field("name", $.identifier),
        optional(field("link_name", $.string_)),
        $.type_qualifier,
      ),
    fn_param: ($) =>
      seq($.identifier, repeat(seq(",", $.identifier)), $.type_qualifier),
    variadic_param: ($) =>
      seq(field("name", $.identifier), ":", $.variadic, field("type", $.type)),
    variadic: (_) => "...",
    block: ($) => seq("{", repeat(choice($.statement)), "}"),
    statement: ($) =>
      choice(
        $.return_,
        $.continue_,
        $.break_,
        $.variable,
        $.const_variable,
        $.if_,
        $.case_,
        $.for_,
        $.defer,
        $.call,
        $.assignment,
        $.panic,
        $.syscall,
        $.type_alias,
      ),
    return_: ($) => prec.right(seq(token("return"), optional($.expression))),
    continue_: ($) => seq(token("continue"), optional(seq(":", $.identifier))),
    break_: ($) => seq(token("break"), optional(seq(":", $.identifier))),
    if_: ($) => seq(token("if"), $.expression, $.block, optional($.else_)),
    else_: ($) => seq(token("else"), choice($.if_, $.block)),
    case_: ($) =>
      seq(token("case"), $.expression, "{", commaSep($.case_arm), "}"),
    case_arm: ($) =>
      choice(
        seq($.type_pattern, "=>", $.block),
        seq(choice("_", seq($.case_pattern, repeat(seq(",", $.case_pattern)))),
            optional($.identifier), "=>", $.block),
      ),
    case_pattern: ($) => choice($.range, $.expression),
    type_pattern: ($) => seq(token("is"), $.type, optional($.identifier)),
    for_: ($) =>
      seq(
        optional(seq($.identifier, ":")),
        token("for"),
        optional($.for_condition),
        $.block,
      ),
    for_condition: ($) =>
      choice(
        seq(
          choice(
            $.identifier,
            seq("*", $.identifier),
            seq("*", "const", $.identifier),
          ),
          token("in"),
          $.expression,
        ),
        $.expression,
      ),
    defer: ($) =>
      seq(
        token("defer"),
        choice(
          $.block,
          $.call,
          $.assignment,
          $.if_,
          $.case_,
          $.for_,
          $.panic,
          $.syscall,
        ),
      ),
    assignment: ($) =>
      prec(
        PREC.ASSIGN,
        seq(
          $.primary,
          choice(
            "=",
            "+=",
            "-=",
            "*=",
            "/=",
            "%=",
            "&=",
            "|=",
            ">>=",
            "<<=",
            "^=",
          ),
          $.expression,
        ),
      ),
    panic: ($) => seq(token("#panic"), "(", $.expression, ")"),
    syscall: ($) => seq(token("#syscall"), "(", commaSep($.expression), ")"),
    range: ($) => seq($.expression, choice("..", "..="), $.expression),
    type_qualifier: ($) => seq(":", $.type),
    type: ($) =>
      prec.right(
        choice(
          $.field_type,
          $.array_type,
          $.pointer_type,
          $.primitive,
        ),
      ),
    field_type: ($) =>
      prec.right(seq($.identifier, repeat(seq(".", $.identifier)))),
    array_type: ($) =>
      seq("[", optional($.number_), "]", optional(token("const")), $.type),
    pointer_type: ($) =>
      seq("*", choice($.fn_type, seq(optional(token("const")), $.type))),
    primitive: (_) =>
      token(
        choice(
          "i8",
          "i16",
          "i32",
          "i64",
          "u8",
          "u16",
          "u32",
          "u64",
          "f32",
          "f64",
          "isize",
          "usize",
          "bool",
          "rawptr",
          "any",
        ),
      ),
    fn_type: ($) =>
      prec.right(
        seq(token("fn"), "(", commaSep($.type), ")", optional($.type)),
      ),
    expression: ($) =>
      choice(
        $.literal,
        $.primary,
        $.unary_prefix,
        $.binary,
        $.size,
        $.cast,
        $.len,
        $.align,
        $.typeof,
        $.syscall,
      ),
    primary: ($) =>
      choice(
        $.identifier,
        $.unary_postfix,
        $.group,
        $.call,
        $.field_access,
        $.index,
      ),
    group: ($) => seq("(", $.expression, ")"),
    binary: ($) =>
      choice(
        ...[
          ["||", PREC.LOGICAL_OR],
          ["&&", PREC.LOGICAL_AND],
          ["==", PREC.EQUALITY],
          ["!=", PREC.EQUALITY],
          [">", PREC.RELATIONAL],
          ["<", PREC.RELATIONAL],
          [">=", PREC.RELATIONAL],
          ["<=", PREC.RELATIONAL],
          ["|", PREC.BIT_OR],
          ["^", PREC.BIT_XOR],
          ["&", PREC.BIT_AND],
          ["<<", PREC.SHIFT],
          [">>", PREC.SHIFT],
          ["+", PREC.ADD],
          ["-", PREC.ADD],
          ["*", PREC.MUL],
          ["/", PREC.MUL],
          ["%", PREC.MUL],
        ].map(([op, p]) => prec.left(p, seq($.expression, op, $.expression))),
      ),
    unary_prefix: ($) =>
      prec(PREC.PREFIX, seq(choice("-", "&", "!", "~"), $.expression)),
    unary_postfix: ($) => prec(PREC.POSTFIX, seq($.expression, ".*")),
    call: ($) =>
      prec(
        PREC.POSTFIX,
        seq($.primary, "(", field("call_args", commaSep($.expression)), ")"),
      ),
    field_access: ($) => prec(PREC.POSTFIX, seq($.primary, ".", $.identifier)),
    index: ($) =>
      prec(
        PREC.POSTFIX,
        seq(
          $.primary,
          "[",
          choice(
            $.expression,
            "..",
            seq("..", $.expression),
            seq($.expression, ".."),
            seq($.expression, "..", $.expression),
          ),
          "]",
        ),
      ),
    size: ($) => seq(token("#sizeof"), "(", choice($.type, $.expression), ")"),
    align: ($) =>
      seq(token("#alignof"), "(", choice($.type, $.expression), ")"),
    typeof: ($) =>
      seq(token("#typeof"), "(", choice($.type, $.expression), ")"),
    len: ($) => seq(token("#len"), "(", $.expression, ")"),
    cast: ($) =>
      prec(PREC.PREFIX, seq(
        choice(token("#cast"), token("#bitcast")),
        "(",
        $.type,
        ")",
        $.expression,
      )),
    literal: ($) =>
      choice(
        $.bool_,
        $.null_,
        $.number_,
        $.string_,
        $.char_,
        $.struct_literal,
        $.array_literal,
      ),
    struct_literal: ($) =>
      seq(
        choice(seq($.identifier, repeat(seq(".", $.identifier))), "."),
        "{",
        commaSep($.struct_literal_member),
        "}",
      ),
    struct_literal_member: ($) => seq($.identifier, ":", $.expression),
    array_literal: ($) => seq("[", commaSep($.expression), "]"),
    bool_: (_) => choice("true", "false"),
    null_: (_) => "nil",
    number_: ($) =>
      choice(
        $._trailing_float,
        token(
          choice(
            /0x[0-9A-Fa-f_]+/,
            /0b[01_]+/,
            /0o[0-7_]+/,
            /([0-9][0-9_]*\.[0-9][0-9_]*|\.[0-9][0-9_]*)([eE][+-]?[0-9][0-9_]*)?/,
            /[0-9][0-9_]*[eE][+-]?[0-9][0-9_]*/,
            /[0-9][0-9_]*/,
          ),
        ),
      ),
    string_: ($) =>
      seq(
        '"',
        repeat(choice($.escape_sequence, token.immediate(/[^"\\\n]+/))),
        '"',
      ),
    char_: ($) =>
      seq("'", choice($.escape_sequence, token.immediate(/[^'\\\n]/)), "'"),
    escape_sequence: (_) =>
      token.immediate(
        seq(
          "\\",
          choice(/[nrt0\\"']/, /x[0-9A-Fa-f]{2}/, /u\{[0-9A-Fa-f]{1,6}\}/),
        ),
      ),
    identifier: (_) => /[A-Za-z_][A-Za-z0-9_]*/,
    comment: (_) =>
      token(
        choice(
          seq("//", /[^\n]*/),
          seq("/*", repeat(choice(/[^*]/, /\*[^/]/)), "*/"),
        ),
      ),
  },
});
