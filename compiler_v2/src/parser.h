#pragma once

#include "lexer.h"

class Node {};

class Program : public Node {
public:
  Program() {}
};

inline Program program() { return Program(); }
inline Node parse(std::vector<Token> &tks) { return program(); }

// grammar time

// program -> declaration_list
// declaration_list -> declaration ';' declaration_list | e
// declaration -> enum_declaration | variable_declaration | function_declaration | struct_declaration | type_declaration
// statement_list -> statement statement_list | e
// statement -> if_statement | loop_statement | for_statement | match_statement | break_statement | return_statement | continue_statement | declaration
//
// enum_declaration -> "enum" IDENTIFIER '{' enum_member_list '}'
// enum_member_list -> enum_member enum_member_list | e
// enum_member -> IDENTIFIER enum_partner_list ','
// enum_partner_list -> '(' partner_list ')' | e
// partner_list -> IDENTIFIER partner_list'
// partner_list' -> ',' IDENTIFIER partner_list' | e
//
// variable_declaration -> TYPE IDENTIFIER '=' expr ';' | "mut" TYPE IDENTIFIER '=' expr ';' | "mut" TYPE IDENTIFIER ';'
//
// function_declaration -> TYPE IDENTIFIER '(' parameter_list ')' function_body
// parameter_list -> parameter parameter_list' | e
// parameter_list' -> ',' parameter_list' | e
// parameter -> ("mut" )? TYPE IDENTIFIER ('=' expr)?
// function_body -> '{' statement_list '}' | "=>" expr ';'
// statement_block -> '{' statement_list '}'
//
// struct_declaration -> "struct" IDENTIFIER trait_clause '{' struct_member_list '}'
// struct_member_list -> struct_member struct_member_list | e
// struct_member -> struct_variable_declaration | struct_function_declaration
// struct_variable_declaration -> TYPE IDENTIFIER | TYPE IDENTIFIER '=' expr
// struct_function_declaration -> TYPE IDENTIFIER '(' parameter_list ')' struct_function_body
// struct_function_body -> '{' statement_list '}' | "=>" expr ';' | e
// trait_clause -> ':' traits_list | e
// traits_list -> IDENTIFIER (',' IDENTIFIER)*
//
// if_statement -> "if" conditional_expr statement_block optional_else_block
// optional_else_block -> 'else' else_content | e
// else_content -> if_statement | statement_block
// loop_statement -> "loop" statement_block
// for_statement -> "for" TYPE IDENTIFIER ':' iterable_expr statement_block
// match_statement -> "match" expr '{' match_branches '}'
// match_branches -> 
// break_statement -> "break" ';'
// continue_statement -> "continue" ';'
// return_statement -> "return" ';' | "return" expr ';' 
//
// expr -> term (arithmetic_op term)* | term (binary_op)*
// conditional_expr -> expr
// term -> factor | '(' expr ')' | literal | IDENTIFIER
// factor -> factor comparison_op factor | factor logical_op | factor | IDENTIFIER | literal | '(' expr ')'
// logical_op -> '&&' | '||'  
// comparison_op -> '==' | '!=' | '<' | '>' | '<=' | '>='
// arithmetic_op -> '+' | '-' | '*' | '/' | '%' | '+=' | '-=' | '*=' | '/=' | '%='
// binary_op -> '&' | '|' | '&=' | '|=' 
//
// literal -> NUMBER | STRING | BOOLEAN | CHAR | struct_literal | enum_literal | enum_variant | function_call | function_literal 
// BOOLEAN -> "true" | "false"
// enum_literal -> "enum" '{' enum_member_list '}'
// enum_variant -> 
// function_literal ->
// function_call -> IDENTIFIER '(' arguments ')'
// arguments -> expr argument_list' | e
// argument_list' -> ',' argument_list' | e
// struct_literal -> "struct" trait_clause '{' struct_members '}'
// struct_access -> 
//
// TYPE -> "f64" | "f32" | integer_type
// integer_type -> 'i' DIGIT+ | 'u' DIGIT+
