# Syntax

## Comments

`// This is a comment`

```dyn
/* Block
   comment
   here
   multiple
   lines */
```

## Keywords

Dyn has the following keywords:

```dyn
break comp continue defer enum fn for if inline match mut or pub struct type use
```

## Terminators

Dyn supports the following terminators for statements: `'\n'`, `';'` (required if you want to separate multiple statements on one line), `'\0'`

## Operator Precedence

| Prec | Operator               | Description                    | Associates |
|------|------------------------|--------------------------------|------------|
| 1    | () [] .                | Grouping, Subscript, Method Call | Left       |
| 2    | - ! ~                  | Negate, Not, Complement         | Right      |
| 3    | * / %                  | Multiply, Divide, Modulo        | Left       |
| 4    | + -                    | Add, Subtract                   | Left       |
| 5    | .. ..=                  | Range, Inclusive Range          | Left       |
| 6    | << >>                  | Shift Left, Shift Right          | Left       |
| 7    | &                      | Bitwise And                     | Left       |
| 8    | ^                      | Bitwise Xor                     | Left       |
| 9    | \|                     | Bitwise Or                      | Left       |
| 10   | < <= > >=              | Comparison                      | Left       |
| 11   | == !=                  | Equals, Not Equals              | Left       |
| 12   | &&                     | Logical And                     | Left       |
| 13   | \|\|                   | Logical Or                      | Left       |
| 14   | =                      | Assignment, Setter              | Right      |
