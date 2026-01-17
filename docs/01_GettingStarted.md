# Getting Started

## Installation

### Prerequisites

- A C compiler (gcc, clang, or MSVC)
- A build system (make or similar)
- Git (optional, for cloning from source)

### Installing from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/dyn.git
cd dyn

# Build the compiler
make build

# Install (optional)
sudo make install
```

### Verifying Installation

```bash
dyn --version
```

You should see the version number printed.

## Your First Program

Create a file called `hello.dyn`:

```dyn
module main

main := () {
    $println("Hello, World!")
}
```

Compile and run it:

```bash
dyn run hello.dyn
```

Or compile it to an executable:

```bash
dyn build hello.dyn
./hello
```

## Understanding the Program

- `module main` - Declares this file belongs to the `main` module
- `main := () {}` - Creates a function called `main` that takes no parameters and returns nothing
- `$println` - A builtin function that prints to stdout followed by a newline

## Next Steps

- Learn the [Syntax](02_Syntax.md)
- Explore [Types](03_Types.md)
- Understand [Functions](07_Functions.md)
- See [Control Flow](06_ControlFlow.md)
