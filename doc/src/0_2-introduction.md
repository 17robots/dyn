# Introduction
This is a basic introduction to the Dyn programming language.
## Purpose
The purpose
## Goals
Dyn tries to
## Tour Of The Book
### Basic Programming
Chapter 2 covers the basics of programming in Dyn. It covers these topics:

_Variables_: creating variables, constants, and using them in your code.

_Types_: primitive types, builtin collections, enumerations, and types dealing with memory.

_Control Flow_: different structures that dyn employs to help aid with its construction including if statements, loops,
the select keyword, and ranges.

_Functions_: how functions are used, including writing functions, adding arguments and return types, and advanced function usage.

_Error Handling_: how to generate errors, how to handle them, and how to customize the error to fit the needs of the program.

_Documentation_: the different types of comments and how they can help manage and maintain code readability.
### Basic Dyn
Chapter 3 introduces the basics of the dyn compiler and programs used to compile your code. It covers these topics:

_Dyn CLI_: a basic intro into the cli including its basic usage, what it's used for, and how to configure it for your terminal.

_Package Management_: the basics needed for managing and creating your own packages.
### Abstraction
Chapter 4 covers the different mechanisms Dyn uses for abstraction and covers the following topics:

_User-Defined Types_: how to create a type, add methods to it, and extend with other types.

_Operator Overloading_: how to implement different operators on user-defined types.

_Interfaces_: how to create, implement and bind an interface to types and as arguments.

_Type Composition_ how to combine and compose different types to use in different parts of your code.

### Metaprogamming
Chapter 5 goes over the different language support for metaprogramming and using the compiler to help program. It covers these topics:

_Macros_: how to declare and use different macros in your programs

_Generics_: syntax for generics, its usage in functions, user-defined types, and how to bind generics

_Type Aliasing_: creating aliases, using them as arguments, and using them as return types

_The `dyn` Keyword_: overview of the word, use cases, and a practical example

### Advanced Programming
Chapter 6 covers advanced topics that enhance programs for scale and professional use. It covers these topics:

_Testing_: unit tests, integration tests, and how to manage and run them

_Memory Management_: a more in depth look at pointers, void pointers, lifetimes and the manage block

_Concurrency_: running multiple tasks at the same time, getting results, and managing channels

_Multiparadigm Dyn_: writing functional dyn or object oriented dyn, imperative, and declarative

### Advanced Dyn
Chapter 7 goes over the advanced features of the dyn compiler and cli. It covers the following topics:

_Package Management_: advanced package operations, freezing, and custom packages.

_Dyn CLI_: managing dyn builds, dyn repl, AST viewer, and extending dyn builds with runtime flags.

_Dynfile_: an overview, common syntax, pitfalls, how to use workspaces, and package install directories.

_Advanced Compiler Usage_: compiler options, saving options, flag list, different build profiles and files, transpiling, and manual fine tuning.
