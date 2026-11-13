# Tiny - language reference

Tiny is a small imperative language with 64-bit integers, first-class functions
and closures. `tinyc.py` compiles a `.tiny` source file straight into a Windows
x64 console `.exe`. This file describes the language; every rule here is meant to
be covered by a test in `tests/`.

## 1. Lexical structure
- Source is UTF-8 text. Line endings `\n` or `\r\n`.
- **Comments:** `--` to the end of the line (`#` and `//` are *not* comments).
  `--` inside a string literal is just text.
- **Identifiers:** letters, digits, `_`; not starting with a digit. (Use ASCII.)
- **Keywords:** `let if else while break continue print input exit and or not fn return global nonlocal`
- **Integer literals:** decimal digits. Range -9223372036854775808 .. 9223372036854775807
  (a literal larger than the maximum is a compile error; `-9223372036854775808` is fine).
- **String literals:** `"..."` with escapes `\n \t \r \\ \" \0`. Strings exist **only as items of
  `print`** (there are no string values or variables yet).
- **Operators / punctuation:** `+ - * / % == != < <= > >= && || ! = ( ) { } ; , :`

## 2. Values and types
Only 64-bit signed integers (two's complement, arithmetic wraps on overflow).
A **function value** is also just an integer-sized value (a pointer to a closure object);
printing one shows a meaningless number. There are no other types, and no type checks.

Truth: `0` is false, any other value is true. Comparison and logical operators yield `0` or `1`.

## 3. Statements and lines
- A statement ends at the **end of the line**. `;` may be used as a separator or terminator
  (`a = 1; b = 2`) but is never required.
- A statement **continues on the next line** if
  - the line ends with a binary/unary operator, `=`, `,`, `and`, `or`, `not`
    (`x = 1 +`, `print "a",`, `ok = a and`), or
  - a `(` is still open (a newline inside parentheses is ignored).
  Inside `{ ... }` newlines count again, even if the braces are inside parentheses.
- Blank lines and comment-only lines are ignored everywhere.

## 4. Blocks
A block is a list of statements. There are three ways to write one (after `if cond`,
`else`, `while cond`, `fn name(...)`, `fn(...)`):

1. **Braces** `{ ... }` - everything inside is one block; layout is free. The `{` may be on the
   next line (Allman style) for `if`, `while`, `else` and named `fn`, but not for `fn` literals.
2. **Indented block** - `:` at the end of the line, then more-indented lines. The block ends when
   the indentation returns to the previous level. A tab counts up to the next multiple of 8.
   Extra indentation on a line that does not follow a `:` is an error; so is a dedent to a column
   that matches no open level.
3. **One-line body** - `:` followed by statements on the same line. The body runs to the end of
   the line and may contain several `;`-separated statements:
   `if a: b; c` means both `b` and `c` are inside the `if`.
   `if a: b; else: c; d` - `else` may follow on the same line (an optional `;` before it is fine),
   and `d` belongs to the else-body.

`else` may also be on the line after the closing `}` / after the dedent, and `else if` chains work.
Braces and indentation can be mixed and nested freely. Blocks do **not** create variable scopes.

## 5. Expressions
Precedence, lowest to highest (all binary operators are left-associative):

| level | operators |
|---|---|
| 1 | `or` `\|\|` |
| 2 | `and` `&&` |
| 3 | `==` `!=` |
| 4 | `<` `<=` `>` `>=` |
| 5 | `+` `-` |
| 6 | `*` `/` `%` |
| 7 | unary `-` `!` `not` |
| 8 | call `f(args)`, then primary: number, variable, `(expr)`, `input()`, `fn` literal |

- `and` / `or` short-circuit and yield 0 or 1.
- `/` truncates toward zero; `%` takes the sign of the left operand (`-7 / 2 == -3`, `-7 % 3 == -1`).
  Division or modulo by zero stops the program with a runtime error.
  (`-9223372036854775808 / -1` raises a hardware exception - not handled.)
- Comparisons are not chained: `1 < 2 == 1` is `(1 < 2) == 1`.
- `input()` reads one line from the console and parses an optional `-` and decimal digits
  (stops at the first other character; leading blanks are not skipped; end of input gives 0).
  Limitation: up to 63 bytes are read per call, so with piped input only one `input()` per run is reliable.

## 6. Statements
| statement | meaning |
|---|---|
| `name = expr` / `let name = expr` | assign (creates the variable if needed; `let` is optional) |
| `print a, b, "text", ...` | print the items one after another (no separators added), then a newline. `print` alone prints an empty line. Items are expressions or string literals |
| `if cond block [else block]` | conditional |
| `while cond block` | loop |
| `break`, `continue` | only inside a `while` of the same function |
| `exit expr` | end the program with that exit code (reaching the end of the file exits with 0) |
| `return [expr]` | only inside a function (see below) |
| `global a, b` / `nonlocal a` | scope declarations, only inside functions (see below) |
| `fn name(params) body` | named function definition |
| `expr` | an expression as a statement (typically a call); its value is discarded |

## 7. Functions
```
fn foo(a, b) { print a, b }            fn bar(a): return 2 * a
fn baz():                              fn sq(x) x * x            -- expression body
    a = 2
    b = 3
    return a + b

foo = fn() { 10 }                      -- function literals have the same body forms
bar = fn() 10
baz = fn(a, b): return a + b
xyz = fn(n): m = 2 * n; return m
abc = fn(n) { m = 2 * n; m }
big = fn(n):
    m = n * n
    return m
print (fn(a, b) a * b)(6, 7)
```
- **Body forms** after `fn name(...)` / `fn(...)`: a block (`{ }`, `:`-indented, `:`-one-line) or,
  if none of `{`, `:` follows, a single expression that is returned (`fn(a) a + 1`; for a named
  function the expression must be on the same line).
- **Result:** `return expr` returns a value; `return` or falling off the end returns 0. If the
  **last statement** of a function body is a bare expression, its value is the result
  (`{ m = 2 * n; m }`). This applies to every function body, named or not.
- **Calls:** any expression can be called: `f(x)`, `f(x)(y)`, `(fn(a) a)(1)`. Arguments are
  evaluated left to right, then the callee. Max 100 parameters / arguments.
  Calling something that is not a function, or with the wrong number of arguments, stops the
  program with a runtime error. (Calling a non-zero number like `5(1)` is not detected and crashes.)
- **Definitions are hoisted:** all `fn name` definitions of a scope are created when the scope is
  entered (program start / function entry), so they can be used before the definition. A `fn`
  inside an `if`/`while` block still belongs to the enclosing function/global scope and is not
  conditional. A named function is simply a variable holding a function value, so it can be
  passed around or reassigned (`say = hello`, `hello = world`). Defining the same name twice
  with `fn` in one scope is an error.
- **Recursion** works (also mutual, and through variables holding literals).

### Scope
- Outside functions variables are **global**. Inside a function, parameters and every name
  that is assigned in the function are **local** (decided for the whole function body).
  Blocks (`{}`, indentation) do not create scopes.
- A function may **read** globals and variables of the functions it is nested in, without any
  declaration. Using a name before its first assignment in the same function is a compile error
  (if the name is a global, the message suggests `global`).
- To **assign** a global, declare `global x` (creates the global if needed) before first use;
  to assign a variable of an enclosing function declare `nonlocal x`.
- **Closures:** a function value keeps the variables it uses alive and shares them by reference
  with the creating function and with other closures; this also holds after the creating
  function has returned (`make_counter`, `adder(n)`). Captured variables and closures live on the
  heap and are never freed (no garbage collection yet).
- Top-level code that reads a global before assigning it is an error unless some function
  declares it `global` (then it is assumed to be set by a call).

## 8. Runtime errors
Printed to standard output, exit code 1:
`runtime error: division by zero`,
`runtime error: call of a value that is not a function`,
`runtime error: wrong number of arguments`.
Very deep recursion overflows the 1 MB stack and crashes (about 10 000 levels are fine).

## 9. Compile errors (selected; all are `file: error: line N: message`)
`undefined variable 'x'`, `variable 'x' used before assignment`, `'break' outside of a loop`,
`'return' outside of a function`, `expected an indented block after ':'`, `unexpected indentation`,
`inconsistent indentation`, `'(' is never closed`, `'{' is never closed`, `unmatched '}'`,
`expected end of statement, found ...`, `unexpected end of line in expression`,
`duplicate parameter 'a'`, `function 'f' is already defined in this scope`,
`'nonlocal' needs an enclosing function`, `integer literal too large`, `bad escape \q`, ...
The exact texts are pinned by the `tests/err_*.tiny` / `.error` pairs.

## 10. Not in the language (yet)
Strings as values, arrays, floats, `for` loops, `else` on loops, modules, a garbage collector,
reliable multi-line piped `input()`, compile-time arity checks, integer overflow detection.
