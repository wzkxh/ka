# Ka - language reference

Ka is a small imperative language with 64-bit integers, first-class functions and
closures, statically type-checked. `ka.py` compiles a `.ka` source file straight into a
Windows x64 console `.exe`. This file describes the language; every rule here is meant to be
covered by a test in `tests/`.

## 1. Lexical structure
- Source is UTF-8 text. Line endings `\n` or `\r\n`.
- A **TAB character is an error everywhere** (also inside strings and comments); use spaces
  (and `^t` inside strings).
- **Comments:**
  - `--` to the end of the line. (`#` and `//` are *not* comments.)
  - `--[[ ... ]]--` inside one line; code continues after it: `print 1 --[[ one ]]-- + 2`.
  - `--[[ ... --]]` over several lines. Everything up to the end of the line that holds the
    closing `--]]` is ignored. (If `--[[` is followed on the same line by `]]--`, it is the
    inside-line form.)
  - An unclosed `--[[` is an error. `--` inside a string literal is just text.
- **Identifiers:** ASCII letters, digits, `_`; not starting with a digit.
- **Keywords:** `if elif else while break continue print exit fn return`.
  (`and or not let global nonlocal input` are *not* keywords; they are ordinary names.)
- **Integer literals:** decimal digits, range -9223372036854775808 .. 9223372036854775807
  (a literal larger than the maximum is a compile error; `-9223372036854775808` is fine).
  `_` may separate digits for readability: `1_000_000` (not at the start or the end, not doubled).
  Hexadecimal literals start with `#` (digits `0-9 a-f A-F`, `_` between digits too): `#ff`, `#FF_FF`.
  They may use all 64 bits: `#ffffffffffffffff` is -1, `#8000000000000000` is the smallest integer.
  (`#'...'` is reserved for hex byte strings later.)
- **String literals:** `'...'` is a *byte string*, `"..."` is a *unicode string*. For now they
  are used the same way (see below); later they will differ. A string cannot contain a raw newline.
  - Escape character is `^`: `^n` newline, `^t` TAB, `^r` CR, `^^` caret, `^"` quote, `^'` apostrophe
    (both quotes may be escaped in both kinds of strings).
  - `^XX` two hex digits, e.g. `^e9`, `^E9`, `^00`: in a byte string it is that **byte**; in a unicode
    string it is the character with that code (U+00E9 for `^e9`).
  - `^uXXXX` (4 hex digits) and `^UXXXXXX` (6 hex digits): a Unicode character (up to 10FFFF, no
    surrogates). In a byte string it is written as its UTF-8 bytes.
  - Other characters stand for themselves; non-ASCII text in the source becomes UTF-8 bytes.
  - Any other escape (`^q`, `^e` without two digits, ...) is a compile error.
  - Strings may contain the byte 0 (`^00`); strings are not NUL-terminated.
  - **Concatenation:** string literals written one after another form one string:
    `'a' 'b' 'c'`. A newline ends a statement as usual, so for a string on several lines put it
    in parentheses (newlines inside parentheses are ignored): `print ("one" NEWLINE "two")`, or end
    the line with `,`. `'...'` and `"..."` cannot be joined with each other.
  - Strings exist **only as items of `print`** (no string values or variables yet).
  - Currently both kinds are stored as UTF-8 bytes and printed as such. The generated program
    switches the console to UTF-8 (`SetConsoleOutputCP(65001)`) at start, so Unicode text shows
    correctly; the console keeps that code page after the program ends.
- **Operators / punctuation:** `+ - * / % ^ & | ~ == != < <= > >= && || ! = ( ) { } ; , : \`
  (`^` is also the prefix of a global variable, `\` the prefix of an enclosing function's variable; see 7.)

## 2. Values and types
Two types:
- **int** - 64-bit signed integer (two's complement, arithmetic wraps on overflow);
- **function** - a pointer to a closure object, written `fn(T1, T2) -> R` in messages.

Types are checked **at compile time** and never written in the program; they are inferred:
- A variable gets the type of the first value assigned to it and keeps it: `x = 1` then
  `x = fn(): =1` is an error.
- A parameter gets its type from how it is used in the body and from the calls of the function:
  `fn f(a): print "x"` called as `f(1)` makes `f(int)`, then `f(f)` is an error.
  One function has one signature, not one per call.
- A function's result has the type of its `return` expressions, which must all agree.
  (`return` without a value and falling off the end give the integer 0; that is not checked yet.)
- Calls check the number and the types of the arguments. Calling an int is an error.
- Operators `+ - * / % ^ & | ~ && || !`, unary `-` `~`, `<` `<=` `>` `>=`, conditions of `if` and
  `while`, the value of `exit`, and items of `print` need ints.
  `==` and `!=` accept two values of the *same* type (two ints or two functions of the same
  signature); functions are equal when they are the same function object.
- A function cannot contain itself in its own signature (`fn f(a): return a(a)` is an error).

Truth: `0` is false, any other value is true. Comparison and logical operators yield `0` or `1`.

## 3. Statements and lines
- A statement ends at the **end of the line**, at `;`, at a closing `)` or `}`, at `else`/`elif`, or
  where another statement starts with a keyword (`if while break continue print exit return fn`).
  So `;` is really needed only to separate statements on one line where the next one does not
  start with a keyword: `a = 1; b = 2`. Several statements starting with keywords can follow each other:
  `i = i + 1 if i == 2: print i`.
- A statement **continues on the next line** if
  - the line ends with a binary/unary operator, `=` or `,`:
    `+ - * / % ^ & | ~ ! == != < <= > >= && || = ,`   (`x = 1 +`, `print "a",`, `ok = a &&`), or
  - a `(` is still open (a newline inside parentheses is ignored).
  Inside `{ ... }` newlines count again, even if the braces are inside parentheses.
- Blank lines and comment-only lines are ignored everywhere.
- A statement that only computes a value (anything but a call) is allowed, but the compiler
  warns: `the value of this expression is not used` (typical mistake: `{m = 2*n; m}`, which does
  not return `m`; write `=m`).

## 4. Blocks
A block is a list of statements. There are three ways to write one (after `if cond`,
`elif cond`, `else`, `while cond`, `fn name(...)`, `fn(...)`):

1. **Braces** `{ ... }` - everything inside is one block; layout is free. The `{` may be on the
   next line (Allman style). `:` directly before `{` is accepted: `if a: {b; c} else: d`.
2. **Indented block** - `:` at the end of the line, then more-indented lines. The block ends when
   the indentation returns to the previous level. Extra indentation on a line that does not
   follow a `:` is an error; so is a dedent to a column that matches no open level.
3. **One-line body** - `:` followed by statements on the same line. The body runs to the end of
   the line (or to a closing `)` / `}` / `,` that belongs to something around it) and may contain
   several statements:
   `if a: b; c` means `if a {b; c}`.
   `if a: b; else: c; d` - `else` and `elif` may follow on the same line (the `;` before them is
   optional), and `d` belongs to the else-body.
   One-line bodies nest:
   `if a: b; while c: d; if e: g else: h; i` means `if a {b; while c {d; if e {g} else {h; i}}}`.
   They also end at `)` (a function literal inside a call) or `}`:
   `(fn(a): if a: =2*a; else: =0)(1)`, `apply(fn(x): =x*2, 5)`. Mixtures work: `if a{b();c()}else:d();e()`.
   An indented block may follow a one-line prefix: `if a: while c:` + indented lines.

`else`/`elif` may also be on the line after the closing `}` / after the dedent.
**Dangling else:** an `else`/`elif` belongs to the nearest `if` that can still take one, also
across lines: `if a: if b: c` + newline + `else: d` gives the `else` to `if b`. Use braces to say
otherwise. Blocks do **not** create variable scopes.

## 5. Expressions
Precedence, lowest to highest (binary operators are left-associative, except `^`):

| level | operators |
|---|---|
| 1 | `\|\|` |
| 2 | `&&` |
| 3 | `==` `!=` (chained) |
| 4 | `<` `<=` `>` `>=` (chained) |
| 5 | `+` `-` `\|` `~` |
| 6 | `*` `/` `%` `&` |
| 7 | unary `-` `~` `!` |
| 8 | `^` power (right-associative: `a^b^c` is `a^(b^c)`), operand on the right may be unary: `2^-1` |
| 9 | call `f(args)`, then primary: number, variable, `(expr)`, `fn` literal |

- `&&` / `||` short-circuit and yield 0 or 1.
- `/` truncates toward zero; `%` takes the sign of the left operand (`-7 / 2 == -3`, `-7 % 3 == -1`).
  Division or modulo by zero stops the program with a runtime error.
  (`-9223372036854775808 / -1` raises a hardware exception - not handled.)
- `&` `|` `~` are bitwise and, or, xor; unary `~` is bitwise not. They work on the 64 bits as they are
  (as unsigned bits): `~0` is -1, `-1 & #ff` is 255. All other operations, including comparisons
  `< > <= >=`, treat integers as signed. There is no shift yet.
- `a ^ b` is `a` to the power `b` (wraps like `*`). A negative exponent is a runtime error.
  Power binds tighter than unary minus: `-2^2` is -4.
- `|` has the level of `+` and `&` the level of `*`: `1 | 2 + 4` is `(1|2)+4`. Use parentheses when mixing.
- **Chained comparisons:** `a < b <= c` means `a < b && b <= c` with `b` evaluated once; evaluation
  stops at the first false link. Chains form within level 3 (`==` `!=`) or within level 4
  (`<` `<=` `>` `>=`), e.g. `1 < 2 > 1` is fine. The two levels are not mixed:
  `a < b == c` is `(a < b) == c`.
- **`^` after an operand is the power operator; `^name` where an operand is expected is a global
  variable** (see 7). `print a ^b` is a power; `print a, ^b` prints a and the global b.

## 6. Statements
| statement | meaning |
|---|---|
| `name = expr` | assign (creates the variable if needed) |
| `^name = expr`, `\name = expr` | assign a global / an enclosing function's variable (see 7) |
| `print a, b, "text", ...` | print the items one after another (no separators added), then a newline. `print` alone prints an empty line. Items are int expressions or string literals |
| `if cond block [elif cond block]... [else block]` | conditional (`else if` also works) |
| `while cond block` | loop |
| `break`, `continue` | only inside a `while` of the same function |
| `exit expr` | end the program with that exit code (reaching the end of the file exits with 0) |
| `return [expr]` or `= expr` | only inside a function (see below). `=` needs a value |
| `fn name(params) body` | named function definition |
| `expr` | an expression as a statement (typically a call); its value is discarded |

## 7. Functions and scope
```
fn f1(a, b) { print a, b }
fn f2(x) { return 2*x }
fn f3(x) { = 2*x }            -- the same as f2
fn f4(x): return 2*x          -- the same as f2
fn f5(x):=2*x                 -- the same as f4
fn baz():
  a = 2; b = 3
  return a + b

foo = fn(){ =10 }             -- function literals have the same body forms
bar = fn(): =10
baz = fn(a,b): return a+b
xyz = fn(n): m = 2*n; return m  -- one-line block
abc = fn(n){m=2*n;=m}           -- the same as xyz
big = fn(n):
    m = n * n
    return m
print (fn(a,b): =a*b)(6,7)
```
- **Body forms** after `fn name(...)` / `fn(...)`: a block (`{ }`, `:`-indented, `:`-one-line).
  There are no expression bodies and no implicit result: a function returns only through
  `return` / `=`.
- **Result:** `return expr` (or `= expr`) returns a value; `return` or falling off the end returns 0.
- **Calls:** any expression can be called: `f(x)`, `f(x)(y)`, `(fn(a): =a)(1)`. Arguments are
  evaluated left to right, then the callee. At most 20 parameters / arguments.
  Types and the number of arguments are checked at compile time. The only call failure left at
  run time is a function variable that was never set (see 8).
- **Definitions are hoisted:** all `fn name` definitions of a scope are created when the scope is
  entered (program start / function entry), so they can be used before the definition. A `fn`
  inside an `if`/`while` block still belongs to the enclosing function/global scope and is not
  conditional. A named function is simply a variable holding a function value, so it can be
  passed around or reassigned to a function of the same signature (`say = hello`, `hello = world`).
  Defining the same name twice with `fn` in one scope is an error. A function cannot be defined
  as global from inside another function (`fn ^name` does not exist).
- **Recursion** works (also mutual, and through variables holding literals).

### Scope
- Outside functions variables are **global**. Inside a function, parameters and every name
  that is assigned in the function by a plain `name = ...` are **local** (decided for the whole
  function body). Blocks (`{}`, indentation) do not create scopes.
- A function may **read** globals and variables of the functions it is nested in, by plain name,
  without any declaration. Using a local name before its first assignment is a compile error
  (the message suggests `^name` to refer to the global one).
- **`^name`** is the global variable `name`. `^name = e` assigns it (and creates it if needed),
  `^name` in an expression reads it. At the top level `^name` is the same as `name`.
  Inside a function, once `^name` is used, the plain `name` in that function is the global too.
  A name cannot be both a local variable (or parameter) and `^name` in the same function: compile error.
  So there is no way to have a local `x` and read the global `x` in the same function; rename one.
- **`\name`** (draft, may change) is the variable `name` of the nearest enclosing *function* that has it
  as a local or parameter: `\name = e` assigns it, `\name` reads it, and the plain name in this
  function then means the same. It is an error if there is no such enclosing function variable, and a
  name cannot be both local and `\name` in one function. (`^name` is the outermost level, `\name` the nearest.)
- **Closures:** a function value keeps the variables it uses alive and shares them by reference
  with the creating function and with other closures; this also holds after the creating
  function has returned (`make_counter`, `adder(n)`). Captured variables and closures live on the
  heap and are never freed (no garbage collection yet).
- Top-level code that reads a global before assigning it is an error unless some function
  assigns to it with `^var` (then it is assumed to be set by a call).

## 8. Runtime errors
Printed to standard output, exit code 1:
`runtime error: division by zero`,
`runtime error: negative exponent`,
`runtime error: call of an unset function` (a function variable that is only assigned by a function that has not run yet).
Very deep recursion overflows the 1 MB stack and crashes (about 10 000 levels are fine).

## 9. Compile errors and warnings
All are `file: error: line N: message` (warnings: `file: warning: line N: message`). The exact texts
are pinned by the `tests/err_*.ka` / `.error` pairs (and `.warn` for warnings). Groups:
- *lexical:* `TAB character is not allowed`, `string is not closed`, `bad escape ^q`, `bad unicode escape`,
  `cannot join '...' and "..." strings`, `comment '--[[' is never closed`, `bad number '1__0'`,
  `bad hex literal`, `hex literal too large`, `integer literal too large`, `unexpected character`.
- *layout / syntax:* `unexpected indentation`, `inconsistent indentation`, `expected an indented block after ':'`,
  `'(' is never closed`, `'{' is never closed`, `unmatched '}'`, `unmatched ')'`,
  `expected end of statement, found ...`, `unexpected end of line in expression`, `unexpected 'else'`,
  `expected '{' or ':' after the parameters`, `a string can only be printed (it is not a value)`,
  `'break' outside of a loop`, `'return' outside of a function`, `'=' (return) needs a value`,
  `duplicate parameter 'a'`, `too many parameters (at most 20)`, `function 'f' is already defined in this scope`.
- *names:* `undefined variable 'x'`, `undefined global variable 'x'`, `variable 'x' used before assignment`,
  `variable 'x' is local to function 'f' and used before assignment (use '^x' ...)`,
  `'x' is already local to 'f', it cannot also be used as '^x'`, `'x' is used as '^x' in 'f', so it cannot
  also be a local variable there`, `'\x' needs an enclosing function`, `'\x': no variable 'x' in an enclosing function`.
- *types:* `type mismatch <where>: expected T, found U` (where: `in assignment to 'x'`, `in argument 2 of the call`,
  `left operand of '+'`, `in the condition of 'if'`, `in 'print' (only integers can be printed)`,
  `in 'return' (all returns of a function must agree)`, ...), `wrong number of arguments: the function takes N,
  called with M`, `an int is not a function`, `a function would have to take itself as an argument`.
- *warning:* `the value of this expression is not used`.

## 10. Not in the language (yet)
Strings (bytes and unicode) as values, floats, arrays (lists), dictionaries, `for` loops,
`else` on loops, modules, a garbage collector, integer overflow detection, big integers,
shift ops, string ops, other integer and float types, named and optional arguments, input (no way
to read a value yet), standard library - file i/o, strings, math, time, etc.
Checking that every path of a function returns a value of the declared kind.
