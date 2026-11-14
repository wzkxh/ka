# Ka - language reference

Ka is a small imperative language with 64-bit integers and floats, first-class functions and
closures, statically type-checked. `ka.py` compiles a `.ka` source file straight into a
Windows x64 console `.exe`. This file describes the language; every rule here is meant to be
covered by a test in `tests/`.

## 1. Lexical structure
- Source is UTF-8 text. Line endings `\n` or `\r\n`.
- TAB is not special: like ESC, BEL or `$` it is just a character. Inside strings and comments it is ordinary
  text; anywhere else it is an `unexpected character` error. Indentation consists of spaces only
  (convention in this project: 2 spaces per level, in `.ka` and `.py` files).
- **Comments:**
  - `--` to the end of the line. (`#` and `//` are *not* comments.)
  - `--[[ ... ]]--` inside one line; code continues after it: `print 1 --[[ one ]]-- + 2`.
  - `--[[ ... --]]` over several lines. Everything up to the end of the line that holds the
    closing `--]]` is ignored. (If `--[[` is followed on the same line by `]]--`, it is the
    inside-line form.)
  - An unclosed `--[[` is an error. `--` inside a string literal is just text.
- **Identifiers:** ASCII letters, digits, `_`; not starting with a digit.
- **Keywords:** `if elif else while break continue print exit function return skip`.
  `\` is a synonym of `function`. (`fn and or not let global nonlocal input` are *not* keywords; they are
  ordinary names.)
- **Float literals** (64-bit): `digits.digits`, `digits.digits e sign digits`, `digits e sign digits`, where digits are
  one or more of 0-9 (with `_` between digits), `e` is `e` or `E` and the sign is `+`, `-` or nothing: `1.5`, `2.0`,
  `1_000.25`, `6.02e23`, `1E-9`, `5e3` (that is the float 5000.0, not an integer). There is no `.5`, no `1.` (write `0.5`, `1.0`)
  and no literal for infinity or NaN (yet). A literal that is too large for a double is an error; one that is too small becomes 0.0
  or a denormal number.
- **Integer literals:** decimal digits, range -9223372036854775808 .. 9223372036854775807
  (a literal larger than the maximum is a compile error; `-9223372036854775808` is fine).
  `_` may separate digits for readability: `1_000_000` (not at the start or the end, not doubled).
  Hexadecimal literals start with `#` (digits `0-9 a-f A-F`, `_` between digits too): `#ff`, `#FF_FF`.
  They may use all 64 bits: `#ffffffffffffffff` is -1, `#8000000000000000` is the smallest integer.
  (`#'...'` is reserved for hex byte strings later.)
  **Binary literals** are written `2#0001_1011` (the digits `0` and `1`, `_` between digits; the `2` is the base,
  other bases do not exist). They may use all 64 bits as well: 64 ones are -1.
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
- **Operators / punctuation:** `+ - * / % ^ & | ~ << >> +> <* *> == != < <= > >= && || ! ? = ( ) { } ; , : \ @`
  and the assignment forms `= += -= *= /= %= ^= &= |= ~= &&= ||= <<= >>= +>= <*= *>=`
  (`^` is also the prefix of a global variable and `@` the prefix of an enclosing function's variable, see 7;
  `\` is a synonym of `function`; `?` and `!` make the conditional expression `c ? a ! b`, see 5.
  `!` directly followed by `=` is always `!=`.)

## 2. Values and types
Three types:
- **int** - 64-bit signed integer (two's complement, arithmetic wraps on overflow);
- **float** - 64-bit IEEE 754 floating point number (a double);
- **function** - a pointer to a closure object, written `fn(T1, T2) -> R` in compiler messages (that notation is only used there).

Types are checked **at compile time** and never written in the program; they are inferred:
- A variable gets the type of the first value assigned to it and keeps it: `x = 1` then
  `x = \(): =1` is an error.
- A parameter gets its type from how it is used in the body and from the calls of the function:
  `function f(a): print "x"` called as `f(1)` makes `f(int)`, then `f(f)` is an error.
  One function has one signature, not one per call.
- A function's result has the type of its `return` expressions, which must all agree.
  (`return` without a value and falling off the end give the integer 0; that is not checked yet.)
- Calls check the number and the types of the arguments. Calling an int is an error.
- **Numbers** (int and float) are accepted by `+ - * / % ^`, unary `-`, `< <= > >=`, `== !=`, `&& || !`, conditions of `if`
  and `while` and of `?:`, and by `print`. Only **ints** are accepted by `& | ~ << >> +> <* *>`, unary `~`, and `exit`.
  Functions are accepted by `==` and `!=` (two functions of the same signature; equal when they are the same function object).
- **Int and float mix inside operators:** `+ - * / % ^` give a float if either side is a float (the other side is
  converted to float first), otherwise an int. In a comparison (`< <= > >= == !=`) both sides are converted to float when
  one of them is a float. `1 + 0.5` is 1.5, `7 / 2` is 3 (int division) but `7 / 2.0` is 3.5, `1 == 1.0` is 1.
- **There are no other implicit conversions** (yet): assigning, passing or returning a float where an int variable, parameter
  or result is expected is an error, and the other way round too. `x = 0` and later `x = 0.5` is an error, write `x = 0.0`.
  A parameter has one type: `function f(a): return a` called as `f(1)` and as `f(1.5)` is an error.
  (An int converted to float loses precision beyond 2^53.)
- The two branches of a conditional `c ? a ! b` must have the same type, but int and float mix like in an operator
  (`c ? 1 ! 2.5` is a float whichever branch is taken); `c` is a number.
- Function types may refer to themselves. With `function q(x): return x`, `function f(a): return a(a)` and
  `d = f(q)` the call executes as `q(q)`, which is `q`, so the type of `q` is `T = fn(T) -> T`. That is safe
  (an int is never called) and costs nothing at run time, so the compiler accepts it. It does not warn about
  calls that never finish (`function w(x): return x(x)`, then `w(w)` recurses forever like any endless recursion).

Truth: `0` and `0.0` (also `-0.0`) are false, any other number is true (NaN is true). Comparison and logical operators yield the
int `0` or `1`.

## 3. Statements and lines
- A statement ends at the **end of the line**, at `;`, at a closing `)` or `}`, at `else`/`elif`, or
  where another statement starts with a keyword (`if while break continue print exit return skip function`),
  with `\` (a function) or with `{` (a block).
  So `;` is really needed only to separate statements on one line where the next one does not
  start like that: `a = 1; b = 2`. Several statements starting with keywords can follow each other:
  `i = i + 1 if i == 2: print i`.
- A statement **continues on the next line** if
  - the line ends with a binary/unary operator, `=` or `,`:
    `+ - * / % ^ & | ~ << >> +> <* *> ! ? == != < <= > >= && || = ,` or any `op=` form (`x +=`),   (`x = 1 +`, `print "a",`, `ok = a &&`), or
  - a `(` is still open (a newline inside parentheses is ignored).
  Inside `{ ... }` newlines count again, even if the braces are inside parentheses.
- Blank lines and comment-only lines are ignored everywhere.
- A statement that only computes a value (anything but a call) is allowed, but the compiler
  warns: `the value of this expression is not used` (typical mistake: `{m = 2*n; m}`, which does
  not return `m`; write `=m`).

## 4. Blocks
A block is a list of statements. There are three ways to write one (after `if cond`,
`elif cond`, `else`, `while cond`, `function name(...)`, `function(...)`):

1. **Braces** `{ ... }` - everything inside is one block; layout is free. The `{` may be on the
   next line (Allman style).
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
   `(\(a): if a: =2*a; else: =0)(1)`, `apply(\x: =x*2, 5)`. Mixtures work: `if a{b();c()}else:d();e()`.
   An indented block may follow a one-line prefix: `if a: while c:` + indented lines.

**A block is a statement.** `{ ... }` stands anywhere a statement can: `a(); {b(); c()}; d()`,
`a() {b(); c()} d()`, `a(){b()}c(){d()}`, inside a one-line body between `if cond:` and `elif cond:`
(`if a: b(); {c()} elif d: e()`), and as the first statement of a one-line body (`if a: {b} c`). No `;` is
needed next to `{` or `}`. Such a block creates no scope. A one-line body runs to the end of the line, so in
`if a: {b} c()` the `c()` belongs to the body, but in `if a {b} c()` it does not.
The empty statement is `skip`: `if a: skip else: b()`.

`else`/`elif` may also be on the line after the closing `}` / after the dedent.
**Dangling else:** an `else`/`elif` belongs to the nearest `if` that can still take one, also
across lines: `if a: if b: c` + newline + `else: d` gives the `else` to `if b`. Use braces to say
otherwise. Blocks do **not** create variable scopes.

## 5. Expressions
Precedence, lowest to highest (binary operators are left-associative, except `^`):

| level | operators |
|---|---|
| 1 | `c ? a ! b` conditional (right-associative: `c ? a ! d ? e ! f` is `c ? a ! (d ? e ! f)`) |
| 2 | `\|\|` |
| 3 | `&&` |
| 4 | `==` `!=` (chained) |
| 5 | `<` `<=` `>` `>=` (chained) |
| 6 | `\|` bitwise or |
| 7 | `~` bitwise xor |
| 8 | `&` bitwise and |
| 9 | `<<` `>>` `+>` `<*` `*>` shifts and rotates |
| 10 | `+` `-` |
| 11 | `*` `/` `%` |
| 12 | `^` power (right-associative: `a^b^c` is `a^(b^c)`) |
| 13 | unary `-` `~` `!` |
| 14 | call `f(args)`, then primary: number, variable, `(expr)`, `function` / `\` literal |

- `&&` / `||` short-circuit and yield 0 or 1.
- **Float arithmetic** follows IEEE 754 double arithmetic. Results that are too large become `inf`/`-inf` and `inf - inf` is `nan` (they
  are printed like that; there are no literals for them yet). Division or modulo by zero (also `0.0`, `-0.0`) is a runtime error
  for floats as for ints, so `1.0 / 0` does not produce `inf`.
- Float `%` is the C `fmod`: exact, the result has the sign of the left operand (`-7.5 % 2` is `-1.5`).
- Float `^`: with an integer-valued exponent (`2.5 ^ 3`, `10.0 ^ -2`) the result is computed in extended precision and rounded once; the
  base may be negative. With a fractional exponent the base must be positive (`(-8.0) ^ (1/3.0)` is a runtime error) and the result is
  `exp(y * ln x)` evaluated by the FPU. `0.0 ^ negative` is division by zero; `x ^ 0` is 1.0. Int `^` int stays an int (see below).
- **Comparisons of floats are exact** (no tolerance): `0.1 + 0.2 == 0.3` is 0. Comparing with NaN is false, except `!=`.
- `/` of two ints truncates toward zero; int `%` takes the sign of the left operand (`-7 / 2 == -3`, `-7 % 3 == -1`).
  Division or modulo by zero stops the program with a runtime error.
  (`-9223372036854775808 / -1` raises a hardware exception - not handled.)
- `&` `|` `~` are bitwise and, or, xor; unary `~` is bitwise not. They work on the 64 bits as they are
  (as unsigned bits): `~0` is -1, `-1 & #ff` is 255. All other operations, including comparisons
  `< > <= >=`, treat integers as signed.
- `a ^ b` is `a` to the power `b` (wraps like `*`). A negative exponent is a runtime error.
  Unary operators bind tighter than any binary one, `^` included: `-2^2` is `(-2)^2` = 4 (write `-(2^2)` for -4).
- The bit operators and shifts sit between `+` and the comparisons, in the order of C (`&` over `~` over `|`), but unlike C
  they bind tighter than `==` and `<`: `a & 1 == 0` is `(a & 1) == 0`, and `1 | 1 + 1` is `1 | (1 + 1)`.
- **Shifts and rotates** (left operand shifted by the right one, 64-bit):
  `x << n` shift left (zeros come in; the same bits as an arithmetic shift left, which therefore has no operator),
  `x >> n` logical shift right (zeros come in, the number is taken as unsigned bits: `-1 >> 60` is 15),
  `x +> n` arithmetic shift right (the sign bit is copied in: `-16 +> 2` is -4),
  `x <* n` and `x *> n` rotate left / right (bits that fall out on one side come in on the other).
  For `<<`, `>>`, `+>` a count of 64 or more, or a negative count, shifts everything out: the result is 0
  (`+>`: 0 or -1 by the sign). A rotate takes the count modulo 64 (`x <* -1` is `x *> 1`).
  Shifts bind tighter than `&` and looser than `+`: `1 << 2 + 1` is `1 << 3`, `6 & 3 << 1` is `6 & (3 << 1)`.
- **Conditional expression** `c ? a ! b`: `c` is evaluated first, then only `a` or only `b` (as in C, but `!`
  instead of `:`). It has the lowest precedence; `a` may be any expression, `b` is parsed as a conditional again.
  A function literal with a one-line body must be put in parentheses inside it: `c ? (\x: =x+1) ! (\x: =x-1)`.
  A line may end with `?` or `!` to continue.
- **Chained comparisons:** `a < b <= c` means `a < b && b <= c` with `b` evaluated once; evaluation
  stops at the first false link. Chains form within one level, `==` `!=` or `<` `<=` `>` `>=`,
  e.g. `1 < 2 > 1` and `1 <= 2 >= 2` are fine. The two levels are not mixed:
  `a < b == c` is `(a < b) == c`.
- **Power operator `^`:** after an operand (i.e. as a binary operator) is the power operator;
  although `^name` where an operand is expected is a global variable (i.e. it serves as an unary
  operator) - see 7. `print a ^b` is a power; `print a, ^b` prints a and the global b.

## 6. Statements
| statement | meaning |
|---|---|
| `name = expr` | assign (creates the variable if needed) |
| `name op= expr` | `name = name op expr` for `+ - * / % ^ & \| ~ && \|\| << >> +> <* *>`, e.g. `c += 1`, `x <<= 2`, `ok &&= f()` (`&&=` and `\|\|=` short-circuit). Also `^name op= expr` and `@name op= expr` |
| `^name = expr`, `@name = expr` | assign a global / an enclosing function's variable (see 7) |
| `print a, b, "text", ...` | print the items one after another (no separators added), then a newline. `print` alone prints an empty line. Items are numbers or string literals; floats are written as described in the next paragraph |
| `if cond block [elif cond block]... [else block]` | conditional (`else if` also works) |
| `while cond block` | loop |
| `break`, `continue` | only inside a `while` of the same function |
| `exit expr` | end the program with that exit code (reaching the end of the file exits with 0) |
| `return [expr]` or `= expr` | only inside a function (see below). `=` needs a value |
| `function name(params) body` | named function definition; `\name(params) body` is the same; with one parameter the parentheses may be left out: `function name p body` |
| `skip` | the empty statement, does nothing |
| `{ ... }` | a block used as a statement (see 4) |
| `expr` | an expression as a statement (typically a call); its value is discarded |

### Printing floats
`print` writes a float with at most **15 significant digits**, trailing zeros removed, always with a `.0` if it would otherwise look like
an int: `1.5`, `100.0`, `0.1`, `0.3` (for `0.1 + 0.2`), `0.333333333333333`. Numbers from 1e-4 up to (not including) 1e15 are written
in fixed notation, others as `d.ddde+XX` / `d.ddde-XX` with at least two exponent digits (`1e+15`, `1.5e-07`, `5e-324` is
`4.94065645841247e-324`). Special values: `0.0`, `-0.0`, `inf`, `-inf`, `nan`. The digits are computed in extended precision, so the last
digit can be wrong by one unit in about one case of ten thousand (values whose 16th digit is very close to 5). This format is
provisional: no control of precision or layout exists yet.

## 7. Functions and scope
```
function f1(a, b) { print a, b }
function f2(x) { return 2*x }
function f3(x) { = 2*x }            -- the same as f2
function f4(x): return 2*x          -- the same as f2
function f5(x):=2*x                 -- the same as f4
function f6 x: return 2*x           -- one parameter: no parentheses needed
function f7 x {=2*x}
\f8 x: =2*x                         -- '\' is a short 'function'
\f9(a, b) {=a+b}
function baz():
  a = 2; b = 3
  return a + b

foo = function(){ =10 }             -- function literals have the same body forms
bar = \(): =10
baz = function(a,b): return a+b
xyz = \n: m = 2*n; return m         -- one-line block, one parameter without ()
abc = \(n){m=2*n;=m}                -- the same as xyz
big = function(n):
  m = n * n
  return m
print (\(a,b): =a*b)(6,7)
```
- **Parameters:** `(a, b)` in parentheses, or a single name without them (`function f x: ...`, `\x: =x+1`).
  `function name x ...` is a definition (a name and a parameter), `function x ...` is a literal with parameter `x`.
- **Body forms** after the parameters: a block (`{ }`, `:`-indented, `:`-one-line).
  There are no expression bodies and no implicit result: a function returns only through
  `return` / `=`.
- **Result:** `return expr` (or `= expr`) returns a value; `return` or falling off the end returns 0.
- **Calls:** any expression can be called: `f(x)`, `f(x)(y)`, `(\a: =a)(1)`. Arguments are
  evaluated left to right, then the callee. At most 20 parameters / arguments.
  Types and the number of arguments are checked at compile time. The only call failure left at
  run time is a function variable that was never set (see 8).
- **Definitions are hoisted:** all `function name` definitions of a scope are created when the scope is
  entered (program start / function entry), so they can be used before the definition. A `function`
  definition inside an `if`/`while` block still belongs to the enclosing function/global scope and is not
  conditional. A named function is simply a variable holding a function value, so it can be
  passed around or reassigned to a function of the same signature (`say = hello`, `hello = world`).
  Defining the same name twice with `function` in one scope is an error. A function cannot be defined
  as global from inside another function (`function ^name` does not exist).
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
- **`@name`** (draft, may change) is the variable `name` of the nearest enclosing *function* that has it
  as a local or parameter: `@name = e` assigns it, `@name` reads it, and the plain name in this
  function then means the same. It is an error if there is no such enclosing function variable, and a
  name cannot be both local and `@name` in one function. (`^name` is the outermost level, `@name` the nearest.)
- **Initial value:** every variable (global, local, captured) starts as 0, so a variable assigned only on a path that
  was not taken has the value 0: after `if a: v = 1` the `v` is 0 when `a` is 0. For a variable that is
  meant to hold a function, 0 means "unset"; calling it is a runtime error (see 8).
- **Closures:** a function value keeps the variables it uses alive and shares them by reference
  with the creating function and with other closures; this also holds after the creating
  function has returned (`make_counter`, `adder(n)`). Captured variables and closures live on the
  heap and are never freed (no garbage collection yet).
- Top-level code that reads a global before assigning it is an error unless some function
  assigns to it with `^var` (then it is assumed to be set by a call).

### Constants
A name made of capital letters, digits and `_` with at least one letter (`MAX_SPEED`, `WIDTH`, `X2`, `_N`) is a
**constant**: it gets its value where it is defined and can never be assigned again. Any name with a lowercase letter
is an ordinary variable.
- **Where:** a constant is defined by `NAME = expr` (or `function NAME(...)`) directly at the **top level**: not inside a
  function, `if`, `elif`, `else`, a loop, or a `{ }` block. This is the usual rule of languages with constants (C, Go,
  Rust, Pascal `const`): a constant is defined once, unconditionally. Parameters cannot have such names either.
- **Once:** a second `NAME = ...`, `NAME += ...` (any assignment) anywhere is a compile error.
- **Value:** it must be a constant expression: numbers, constants defined *above* it, operators (also `?:`), and function
  literals (so a constant can be a function; it may call itself by its own name). Variables and calls are not allowed
  (`WIDTH = 80`, `AREA = WIDTH * HEIGHT`, `FLAG_B = FLAG_A << 1`, `FACT = \n: =n < 2 ? 1 ! n * FACT(n-1)`).
- **When:** all constants are created at program start, in the order written, before any other statement (as the named
  `function` definitions are), so they can be read anywhere, also in functions that run early and above the line that
  defines them (`print LATER` then `LATER = 7`).
- Reading is the same as for any global: by name, or `^NAME`.

## 8. Runtime errors
Printed to standard output, exit code 1:
`runtime error: division by zero` (int and float `/` `%`, and `0 ^ negative` for floats),
`runtime error: negative exponent` (int `^`),
`runtime error: power of a negative number with a fractional exponent`,
`runtime error: call of an unset function` (a function variable that is only assigned by a function that has not run yet).
Very deep recursion overflows the 1 MB stack and crashes (about 10 000 levels are fine).

## 9. Compile errors and warnings
All are `file: error: line N: message` (warnings: `file: warning: line N: message`). The exact texts
are pinned by the `tests/err_*.ka` / `.error` pairs (and `.warn` for warnings). Groups:
- *lexical:* `unexpected character '\t'` (TAB, like `$`, outside strings and comments), `string is not closed`, `bad escape ^q`, `bad unicode escape`,
  `cannot join '...' and "..." strings`, `comment '--[[' is never closed`, `bad number '1__0'`,
  `bad hex literal`, `hex literal too large`, `bad binary literal`, `binary literal too large`, `bad number '1.5abc...'`, `a float needs digits after the dot` / `before the dot`,
  `float literal too large`, `integer literal too large`, `unexpected character`.
- *layout / syntax:* `unexpected indentation`, `inconsistent indentation`, `expected an indented block after ':'`,
  `'(' is never closed`, `'{' is never closed`, `unmatched '}'`, `unmatched ')'`,
  `expected end of statement, found ...`, `unexpected end of line in expression`, `unexpected 'else'`,
  `expected '{' or ':' after the parameters`, `expected '(' or a parameter name`, `expected '!'` (conditional expression), `a string can only be printed (it is not a value)`,
  `'break' outside of a loop`, `'return' outside of a function`, `'=' (return) needs a value`,
  `duplicate parameter 'a'`, `too many parameters (at most 20)`, `function 'f' is already defined in this scope`.
- *names:* `undefined variable 'x'`, `undefined global variable 'x'`, `variable 'x' used before assignment`,
  `variable 'x' is local to function 'f' and used before assignment (use '^x' ...)`,
  `'x' is already local to 'f', it cannot also be used as '^x'`, `'x' is used as '^x' in 'f', so it cannot
  also be a local variable there`, `'@x' needs an enclosing function`, `'@x': no variable 'x' in an enclosing function`.
- *constants:* `constant 'X' can only be defined directly at the top level (not inside a function, ...)`,
  `constant 'X' is already defined (line N)`, `constant 'X' cannot be changed`,
  `parameter 'N' looks like a constant`, `the value of constant 'X' must be a constant expression (...): it uses the variable 'a'`
  (or `it calls a function`, `it uses 'B', which is defined later`).
- *types:* `type mismatch <where>: expected T, found U` (where: `in assignment to 'x'`, `in argument 2 of the call`,
  `left operand of '+'`, `in the condition of 'if'`, `in 'print' (only numbers can be printed)`,
  `in 'return' (all returns of a function must agree)`, ...), `wrong number of arguments: the function takes N,
  called with M`, `an int is not a function` (or `a float ...`), `the result is float, expected int`, `expected a number, found fn()`, `in '?!' (both branches must have the same type)`, `in the condition of '?'`.
- *warning:* `the value of this expression is not used`.

## 10. Not in the language (yet)
- function f(x):y === f=\(x):y. stackless?
- strings (bytes and unicode) as values;
- a garbage collector;
- call syntax: f a; f a,b,c; etc;
- multi-value assignment, returns;
- floats: **yet to do:** more float literals (pi-based), `INF` and `NAN` (literals, tests, and `0.0/0.0`-like
  results are only reachable through overflow now), comparison with tolerance (comparisons are exact for now),
  (**pragma** tolerance?), output formatting (**pragma** precision? proper formatting: precision, width, layout;
  the 15-digit format is provisional), explicit conversion int <-> float (`int(x)`, `float(i)`, rounding,
  floor/ceil), implicit conversion on assignment (strict now), math functions (sqrt, sin, ...);
- many ints and floats (other sizes), arrays (lists), dictionaries, sets, tuples, enums;
- big integers;
- `for` loops;
- `until cond loop`;
- `else` on loops;
- `break 2` or `break break`
- fix: constants (MAX_LEN) inside fns (ifs, loops, etc); constant expression;
- fix: shift ops -- negative counts;
- radix 3..36 literals 3#122 8#377 36#zzz;
- modules, import;
- integer overflow detection (as **pragma** intoverflow? other checks as pragmas);
- named and optional arguments;
- input (no way to read a value yet);
- operations on strings (+ etc), numbers (?);
- standard library:
  - file system, i/o;
  - strings;
  - math;
  - time, etc;
- checking that every path of a function returns a value of the declared kind;
- optimization.
- if it's not too much work (≈10%), make an option to print out AST. This is rather optional.
- if it's not too much work (≈10%), make an option to print out Assembler listing. This is VERY optional.
- like in PL/I, dump vars with their types. Very optional too.

## 11. Characters (JFYI)
| char | usage |
|---|---|
| ! | unary not, conditional ops, != - not equal |
| ? | conditional `c ? a ! b` |
| ' | byte string |
| " | unicode string |
| # | hex literal `#ff`, binary literal `2#101` |
| / | unary - nothing, float division; /= |
| % | unary - nothing, modulo; %= |
| & | unary - nothing, bitwise and, && - logical and; &= &&= |
| \| | unary - nothing, bitwise or, \|\| - logical or; \|= \|\|= |
| ~ | bitwise not, xor; ~= |
| * | unary - nothing (scatter?), multiply; \*= ; `<*` `*>` rotate |
| + | identity, plus; += ; `+>` arithmetic shift right |
| - | negative, minus; -= |
| < | unary - nothing, less; <= - le; `<<` shift left, `<*` rotate left |
| > | unary - nothing, greater; >= - ge; `>>` shift right, `+>` `*>` |
| = | return, assignment, == - equal |
| , | separate parameters, arguments |
| : | start block, unary - nothing |
| ; | separate statements, unary - nothing |
| \\ | function (synonym of `function`), binary - todo: int.div.; \\= |
| ^ | global variable (prefix), power (binary); ^= |
| _ | 'blank' in ids and numbers, ids can start/end with it |
| @ | upper-level variable |
| () | expressions, parameters, arguments |
| {} | block |
| [] | - |
| . | - |
| ` | - |
| $ | - |
