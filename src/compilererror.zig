pub const CompilerError = error {
    // parser errors
    InvalidDeclarationToken,
    InvalidFunctionBodyToken,
    InvalidOperatorToken,
    AtLeastOneExpressionExpected,
    InvalidElseBodyMarker,
    InvalidPostDotExpression,
    InvalidPrefixExpression,
    InvalidDotMemberExpression,
    UnexpectedToken,
    InvalidLiteral,
    ExpectedStringForUsePath,
    // lexer errors
    InvalidCharacter,
    InvalidCharLength,
    InvalidEscape,
};
fn to_string(s: CompilerError) []const u8 {
    return switch (s) {
        .InvalidDeclarationToken => "Invalid declaration token",
        .InvalidFunctionBodyToken => "Invalid function body token",
        .InvalidOperatorToken => "Invalid operator token",
        .AtLeastOneExpressionExpected => "At least one expression expected",
        .InvalidElseBodyMarker => "Invalid else body marker",
        .InvalidPostDotExpression => "Invalid post dot expression",
        .InvalidPrefixExpression => "Invalid prefix expression",
        .InvalidDotMemberExpression => "Invalid dot member expression",
        .UnexpectedToken => "Unexpected token",
        .InvalidLiteral => "Invalid literal",
        .ExpectedStringForUsePath => "Expected string for use path",
        .InvalidCharacter => "Invalid character",
        .InvalidCharLength => "Invalid char length",
        .InvalidEscape => "Invalid escape",
    };
}
