# Kota - language reference

Kota is a small imperative language with 64-bit integers and floats, first-class functions and closures, checked by static types.
`kota.py` compiles a `.ko` source file into a Windows x64 console `.exe` (the version is the `VERSION` constant at the top of `kota.py`).
This file defines the language; the reasons behind the decisions are in IMPLEMENTATION.txt, the history in RELEASE_NOTES.md.

## 1. Lexical structure
- Source is UTF-8 text. Line endings `LF` or `CR LF`.
- `TAB` is like any other control (e.g. BEL, ESC, HT) or unexpected (`\``,`½`,`∞`) character: just text inside strings and comments,
  *unexpected character* anywhere else. Indentation consists of spaces only. And better use 2 spaces.
- **Comments:**
  - `--` to the end of the line.
  - `# ` to the end of the line: a hash followed by a space or by the end of the line, but not directly after a digit (`2#` starts a binary literal).
  - `--[[ ... ]]--` inside one line; code continues after it: `print 1 --[[ one ]]-- + 2`.
  - `--[[ ... --]]` over several lines; the rest of the line that holds the closing `--]]` is ignored.
    If `]]--` follows `--[[` on the same line, it is the inside-line form.
  - An unclosed `--[[` is an error. `--` inside a string is text.
- **Identifiers:** ASCII letters, digits, `_`; not starting with a digit.
- **Keywords:** `if elif else while break continue print exit function return skip assert`. `\` is a synonym of `function` where
  an operand or statement is expected.
- **Integer literals:** decimal digits, -9223372036854775808 .. 9223372036854775807. `_` may separate digits (`1_000_000`), not at the
  start or the end and not doubled.
  Hexadecimal `#ff`, `#FF_FF` or `0xff`, `0XFF_FF` (digits `0-9 a-f A-F`, `_` between digits) and binary `2#0001_1011` (base 2 only) may use all 64 bits:
  `#ffffffffffffffff`, `0xFFFFFFFFFFFFFFFF` and 64 binary ones are -1.
- **Float literals** (64-bit): `digits.digits`, `digits[.digits]e|E[sign]digits`; digits are 0-9 with optional `_` between digits:
  `1.5`, `1_000.25`, `6.02e23`, `1E-9`, `5e3` (the float 5000.0).
  No `.5`, no `1.`, no infinity or NaN literal (yet). Too large for a double is an error, too small gives 0.0 or a denormal.
- **String literals:** `'...'` is a byte string (`str`), `"..."` a unicode string (`text`). A string cannot contain a raw newline.
  - Escape character `^`: `^n` newline, `^t` TAB, `^r` CR, `^^` caret, `^"` quote, `^'` apostrophe (both quotes in both kinds).
  - `^XX` (two hex digits, `^e9`, `^E9`, `^00`): the byte XX in a byte string; the character U+00XX in a unicode string.
  - `^uXXXX` (4 hex digits), `^UXXXXXX` (6 hex digits): a Unicode character (to 10FFFF, no surrogates); in a byte string its UTF-8 bytes.
  - Other characters stand for themselves; non-ASCII source text becomes UTF-8 bytes in a `str`, code points in a `text`. Any other escape is an error.
  - A string may contain the byte 0 (a `text` may contain U+0000).
  - String literals written one after another are joined: `'a' 'b' 'c'`. A string over several lines is written in parentheses
    (`print ("one" NEWLINE "two")`) or with a line ending in `,`. `'...'` and `"..."` cannot be joined.
  - A literal is a value: `s = 'abc'`, `NAME = "text"`, `f('x')`. `''` and `""` are the empty string.
  - Output is written as UTF-8 bytes (a `str` as it is, a `text` encoded); the program sets the console code page to UTF-8 at start.
- **Compatibility forms:** `# ` comments and `0x` hex literals exist only to ease the migration of existing sources and programs from other languages, and for the
  ease of copying code and constants between them. They are not Kota style and are discouraged in new programs: write `--` comments and `#ff` / `2#...` literals.
- **Operators / punctuation:** `+ - * / \ % ^ & | ~ << >> +> <* *> == != < <= > >= && || ! ? = ( ) { } ; , : @`
  and the assignment forms `= += -= *= /= \= %= ^= &= |= ~= &&= ||= <<= >>= +>= <*= *>=`.

## 2. Values and types
Five types:
- **int** - 64-bit signed integer (two's complement, arithmetic wraps);
- **float** - 64-bit IEEE 754 number;
- **str** - immutable byte string; the value is a 64-bit address of `[u64 length in bytes][bytes]` (no terminator), 0 for the empty string;
- **text** - immutable Unicode string; the value is an address of `[u64 length in characters][u32 code points]`, 0 for the empty string;
- **function** - a closure; written `fn(T1,T2)->R` in compiler messages.

Types are checked at compile time, never written, and inferred:
- A variable has the type of the first value assigned to it; later values must have the same type.
- A parameter gets its type from its use in the body and from the calls; a function has one signature.
  `function f(a): print "x"` called as `f(1)` is `f(int)`; `f(f)` is then an error.
- A function's result type is the type of its `return` expressions, which must agree.
  `return` without a value and falling off the end give the int 0 (not checked).
- Calls check the number and types of the arguments. Calling a number is an error.
- Function types may refer to themselves (`function f(a): return a(a)` with `d = f(q)`, `function q(x): return x`).
- **Numbers** (int, float) are accepted by `+ - * / \ % ^`, unary `-` `?` `|`, `< <= > >= == !=`, `&& || !`, conditions of `if`, `while`, `?!`, and `print`.
  **Ints only** are accepted by `& | ~ << >> +> <* *>`, unary `~` `*` and `exit`.
  Functions are accepted by `==` and `!=` (equal if they are the same function; same signature).
- **Strings** (`str`, `text`) are accepted by unary `|` (the length), `+` (concatenation), `+=`, `== != < <= > >=` (by contents; `str` by unsigned bytes, `text` by code points; chains work too),
  `&& || !`, conditions of `if`, `while`, `?!`, and `print`. Both operands must have the same string type: `str` and `text` do not mix and do not convert.
  Assignment, passing, returning and closures copy the address; strings are never changed, `+` makes a new one. Memory is not freed.
- **Int and float mix inside operators:** `+ - * % ^` give a float if either side is a float (the other side is converted), else an int.
  `/` always gives a float, `\` always an int. A comparison with a float operand is done on floats.
  `1 + 0.5` is 1.5, `7 / 2` is 3.5, `7 \ 2` is 3, `1 == 1.0` is 1.
- There is no other implicit conversion: assigning, passing or returning a float where an int is expected is an error, and vice versa
  (`x = 0` then `x = 0.5` is an error; `f(1)` and `f(1.5)` cannot both be called).
- The branches of `c ? a ! b` have the same type, int and float mix as in an operator; `str` and `text` branches must match exactly.
- Truth: `0`, `0.0` and `-0.0` are false, any other number (also NaN) is true; the empty string is false, any other string is true. Comparisons and logical operators give the int `0` or `1`.

## 3. Statements and lines
- A statement ends at the end of the line, at `;`, at a closing `)` or `}`, at `else`/`elif`, or where another statement starts with a
  keyword (`if while break continue print exit return skip assert function`) or with `{`. So `;` is needed only to separate statements
  on one line when the next one starts otherwise: `a = 1; b = 2`; `i = i + 1 if i == 2: print i` needs none.
- A statement continues on the next line if the line ends with `+ - * / \ % ^ & | ~ << >> +> <* *> ! ? == != < <= > >= && || = ,` or an `op=` form,
  or while a `(` is open (newlines inside parentheses are ignored; inside `{ }` they count again).
- Blank lines and comment-only lines are ignored.

## 4. Blocks
A block follows `if cond`, `elif cond`, `else`, `while cond`, `function name(...)`, `function(...)`. Three forms:
1. **Braces** `{ ... }`; layout is free; the `{` may be on the next line. These blocks are mainly for usage in one line.
2. **Indented:** (like Python) `:` at the end of the line and more-indented lines. The block ends when the indentation returns. Extra indentation
   after a line not ending in `:` and a dedent to an unknown column are errors.
3. **One-line:** `:` followed by statements on the same line, up to the end of the line or to the end of the construct around it: a closing `)`, `}` or `,`, or the `!` of `c ? a ! b` when the body is in its middle part.
   `if a: b; c` is `if a {b; c}`. `else` and `elif` may follow on the same line. One-line bodies nest:
   `if a: b; while c: d; if e: g else: h; i` is `if a {b; while c {d; if e {g} else {h; i}}}`.
   `(\(a): if a: =2*a; else: =0)(1)` and `apply(\x: =x*2, 5)` end the body at `)` / `,`.
   An indented block may follow a one-line prefix: `if a: while c:` + indented lines.

`{ ... }` is a statement and may stand anywhere a statement can: `a(); {b(); c()}; d()`, `a(){b()}c(){d()}`, `if a: b(); {c()} elif d: e()`,
`if a: {b} c`. In a one-line body the rest of the line belongs to the body: in `if a: {b} c()` the `c()` is in the body, in `if a {b} c()` it is not.
`skip` is the empty statement.
`else`/`elif` may be on the line after the closing `}` or after the dedent. An `else`/`elif` belongs to the nearest `if` that can take one,
also across lines. Blocks do not create scopes.

## 5. Expressions
Precedence, highest to lowest; binary operators are left-associative except `^`:

| level | operators |
|---|---|
| 14 | call `f(args)`; primary: number, variable, `(expr)`, function literal |
| 13 | unary `-` `~` `!` `?` `\|` `*` |
| 12 | `^` power (right-associative) |
| 11 | `*` `/` `\` `%` |
| 10 | `+` `-` |
| 9 | `<<` `>>` `+>` `<*` `*>` shifts and rotates |
| 8 | `&` bitwise and |
| 7 | `~` bitwise xor |
| 6 | `\|` bitwise or |
| 5 | `<` `<=` `>` `>=` (chained) |
| 4 | `==` `!=` (chained) |
| 3 | `&&` logical and |
| 2 | `\|\|` logical or |
| 1 | `c ? a ! b` conditional (right-associative) |

- `&&` and `||` short-circuit and give 0 or 1.
- **Division and modulo are mathematical (floored).** `a / b` is float division, always a float (ints are converted). `a \ b` is integer division:
  `a \ b` is floor(a / b), it rounds toward minus infinity and is always an int. `a % b` has the sign of `b` (it is 0 if `b` divides `a`) and `|a % b| < |b|`.
  For ints always `a \ b * b + a % b == a`.
  Floats follow the same definitions (the identity holds for floats up to rounding: `(-7 \ 3.2) * 3.2 + -7 % 3.2` is `-7.000000000000001`).
  Division or modulo by zero (also `0.0`, `-0.0`) is a runtime error for ints and floats. `-9223372036854775808 \ -1` raises a hardware exception.
- **Float arithmetic** is IEEE 754 double arithmetic; too large results become `inf`/`-inf`, `inf - inf` is `nan`. Float comparisons are exact;
  a comparison with NaN is false except `!=`.
- **Power** `a ^ b`: int ^ int is an int (wraps); a negative exponent is a runtime error. If an operand is a float the result is a float:
  with an integer-valued exponent any base is allowed (`10.0 ^ -2`, `(-2.0) ^ 3`); with a fractional exponent the base must be positive
  (otherwise a runtime error). `0.0 ^ negative` is division by zero; `x ^ 0` is 1.
  Unary operators bind tighter than `^`: `-2^2` is `(-2)^2` = 4.
- **Bit operators** `& | ~` (xor) and unary `~` (not) work on the 64 bits as unsigned bits (`~0` is -1, `-1 & #ff` is 255). Comparisons treat ints as signed.
  They bind tighter than comparisons: `a & 1 == 0` is `(a & 1) == 0`; `1 | 1 + 1` is `1 | (1 + 1)`.
- **Shifts and rotates:** `x << n` left, `x >> n` logical right, `x +> n` arithmetic right (sign bit copied), `x <* n` rotate left, `x *> n` rotate right.
  For `<< >> +>` a count of 64 or more shifts everything out (result 0; `+>` gives 0 or -1 by the sign).
  A negative count shifts the other way: `x >> -n` is `x << n`, `x << -n` is `x >> n`, `x +> -n` is `x << n`.
  A rotate takes the count modulo 64: `x <* -n` is `x *> n`, `x *> -n` is `x <* n`.
- **Absolute value and length**, unary `|x` (after an operand `|` is bitwise or): for an int or a float the absolute value, of the same type (the smallest int stays as it is, `|-0.0` is `0.0`, the sign of NaN is cleared);
  for a `str` the number of bytes, for a `text` the number of characters, an int (0 for the empty string). `|x + 1` is `(|x) + 1`, `|(a - b)` needs the parentheses. Not for functions.
- **Prime test**, unary `*n` (after an operand `*` is multiplication): for an int `n` the int 1 if `n` is a prime number, else 0 (`*-3`, `*0`, `*1` are 0, `*2` is 1). Ints only.
- **Random numbers**, unary `?x`: for an int `n > 1`, `?n` is an int in `0 .. n-1`; `?0` is the next raw 64 bits as an int; for an int `m < 0`, `?m` sets the state of the
  generator to `-m` and gives 0; for a float `x > 0.0`, `?x` is a float in `[0, x)`. `?1` is the current time (below). `?0.0`, a negative float and NaN are runtime errors.
  `?x` has the type of `x`; the operand may be any int, float, str or text expression.
- **Time**, `?1`: the current UTC time as an int, in microseconds since 1970-01-01 (`GetSystemTimePreciseAsFileTime`).
  `?'format'` and `?"format"`: the current local time (`GetLocalTime`) as a `str` or as a `text`, made by the format. A format code is a letter and a digit; any other character,
  also an unknown code such as `y3`, is copied as it is (a `str` format: byte by byte, also bytes that are not UTF-8).

  | code | result |
  |---|---|
  | `y2` `y4` | year, last two digits (00..99) / four digits |
  | `m1` `m2` | month 1..12 / 01..12 |
  | `d1` `d2` | day 1..31 / 01..31 |
  | `H1` `H2` | hour 0..23 / 00..23 |
  | `M1` `M2` | minute 0..59 / 00..59 |
  | `S1` `S2` | second 0..59 / 00..59 |
  | `F1` `F2` `F3` | fraction of a second: tenths 0..9, hundredths 00..99, thousandths 000..999 |
  | `w1` `w2` `w3` | weekday: 1..7 (Monday is 1) / `Mo`..`Su` / `Mon`..`Sun` |

  `?'Now: y4/m2/d2 H2:M2:S2.F3'` is `Now: 2026/11/26 23:35:58.296`. The result has at most 64 characters (a code that does not fit ends it); an empty result is the empty string.
- **Conditional** `c ? a ! b`: `c` is evaluated, then only `a` or only `b`. A one-line function body in the middle part ends at the `!`: `c ? \x:=x+1 ! \x:=x-1`.
  A line may end with `?` or `!` (expression continues on the next line).
- **Chained comparisons:** `a < b <= c` is `a < b && b <= c` with `b` evaluated once; evaluation stops at the first false link.
  Chains form within `== !=` or within `< <= > >=`; `a < b == c` is `(a < b) == c`.

## 6. Statements
| statement | meaning |
|---|---|
| `name = expr`, `^name = expr`, `@name = expr` | assign, creates a variable / a global / an enclosing function's variable (see 7) |
| `name op= expr` | `name = name op expr` for `+ - * / \ % ^ & \| ~ && \|\| << >> +> <* *>`; `&&=` and `\|\|=` short-circuit; also `^name op= expr`, `@name op= expr` |
| `print a, b, "text", ...` | print the items one after another, then a newline; `print` alone prints an empty line. Items are numbers or strings |
| `if cond block [elif cond block]... [else block]` | conditional (`else if` also works) |
| `while cond block` | loop |
| `break`, `continue` | only inside a `while` of the same function |
| `exit expr` | end the program with that exit code (the end of the file exits with 0) |
| `assert cond[, report]` | if `cond` is false (`0`, `0.0`, `''`, `""`; any int, float, str or text expression) print `assertion failed (line N): ` and the report, and exit with code 1. The report is one item as in `print` (evaluated only on failure); without it the text of the condition is printed. The compiler constant `CHECK_ASSERTS = False` removes all asserts |
| `return [expr]`, `= expr` | only inside a function; `=` needs a value |
| `function name(params) body`, `\name(params) body` | named function definition; one parameter needs no parentheses: `function name p body` |
| `skip` | the empty statement |
| `{ ... }` | a block as a statement (see 4) |
| `expr` | an expression as a statement; the value is discarded; usually a call |

### Printing floats
At most 15 significant digits, trailing zeros removed, `.0` if the number would look like an int: `1.5`, `100.0`, `0.1`, `0.3` (for `0.1 + 0.2`).
From 1e-4 up to (not including) 1e15 fixed notation, otherwise `d.ddde+XX` / `d.ddde-XX` with at least two exponent digits (`1e+15`, `1.5e-07`).
Special values: `0.0`, `-0.0`, `inf`, `-inf`, `nan`.

## 7. Functions and scope
```
function f1(a,b) { print a, b }
function f2(x) { return 2*x }
function f3(x) { = 2*x }            -- the same as f2
function f4(x): return 2*x          -- the same as f2
function f5(x):=2*x                 -- the same as f4
function f6 x: return 2*x           -- one parameter: no parentheses
\f7 x:=2*x                          -- '\' is a short 'function'
\f8(a,b){=a+b}
foo = function(){ =10 }             -- function literals have the same body forms
bar = \():=10
xyz = \n: m = 2*n; return m         -- one-line block, one parameter without ()
print (\(a,b):=a*b)(6,7)
```
- A function returns only through `return` / `=`; there are no expression bodies and no implicit result. `return` or the end of the body gives 0.
- Any expression can be called: `f(x)`, `f(x)(y)`, `(\a:=a)(1)`. Arguments are evaluated left to right, then the callee. At most 20 parameters or arguments.
- `function name` definitions of a scope are created when the scope is entered (hoisting), so they can be used before the definition. A definition inside an
  `if` or loop still belongs to the enclosing scope and is not conditional. A name defined with `function` is a constant: it is defined once in its scope
  and cannot be assigned (`f = ...`, `^f = ...`, `f += ...` are errors); the function can be passed around and assigned to other variables.
  `function ^name` does not exist.
- Recursion works, also mutual and through variables holding literals.

### Scope
- Outside functions variables are global. Inside a function, parameters and every name assigned by a plain `name = ...` are local for the whole body.
- A function reads globals and variables of the functions around it by plain name.
- `^name` is the global variable `name`, mainly for assignment: `^name = e` assigns it (creating it), `^name` reads it; at the top level it equals `name`.
  Once `^name` is used in a function, the plain `name` there is the global too. A name cannot be both local (or parameter) and `^name` in one function.
- `@name` (draft, like `nonlocal` in Python) is the variable `name` of the nearest enclosing function that has it as local or parameter: `@name = e` assigns, `@name` reads; the plain
  name then means the same. A name cannot be both local and `@name` in one function; without such a variable it is an error.
- A function value shares the variables it uses with its creator and other closures, also after the creator has returned. Captured variables and closures are never freed.
- **A variable must be assigned before it is read.** Variables and constants exist from the moment execution reaches their assignment; only `function name`
  definitions exist from the start of their scope. A read that no assignment can precede is a compile error. A read that every path prepares needs nothing.
  In the unclear cases the variable gets a hidden flag that its assignments set; the read checks it and stops the program with a runtime error
  `variable 'x' is not initialized` if the variable was never assigned. The unclear cases are:
  - an assignment only on some paths (one branch of an `if`, the body of a loop, which may not run);
  - after a call, a variable that some function can assign (`^x`, `@x`);
  - a global read in a function, unless it is assigned before every call in the top-level code;
  - a variable of an enclosing function read in a nested function, unless it is assigned before every call in the enclosing function and at every exit of it.

  Parameters are assigned when the function starts.

### Constants
A name of capital letters, digits and `_` with at least one letter (`MAX_SPEED`, `X2`, `_N`) is a constant; a name with a lowercase letter is a variable.
- A constant is a variable that is assigned once: by `NAME = expr` directly in the statements of the program or of a function body (not inside `if`, `elif`, `else`,
  a loop or a `{ }` block), and nowhere else. The value may be any expression: `WIDTH = 80`, `AREA = WIDTH * HEIGHT`, `SIZE = f(3)`, `SEED = ?100`.
  It exists from the line where it is assigned; reading it earlier is an error, as for every variable.
- Its scope is the program or that function (also the functions nested in it). A function may define a constant of the same name as a global one.
  A constant cannot be written as `^NAME` or `@NAME` inside a function. Parameters cannot have such names.
- Any second assignment (`NAME = ...`, `NAME += ...`) is an error.

## 8. Runtime errors
Written to standard output, exit code 1:
`runtime error: division by zero` (`/ \ %` with a zero divisor, `0.0 ^ negative`),
`runtime error: negative exponent` (int `^`),
`runtime error: power of a negative number with a fractional exponent`,
`runtime error: bad argument of '?'` (`?0.0`, a float that is not above 0.0, NaN),
`runtime error: variable 'x' is not initialized` (see 7),
`runtime error: call of an unset function` (a function that ended without a result),
`runtime error: out of memory` (`HeapAlloc` failed: a closure or a string could not be allocated).
A failed `assert` prints `assertion failed (line N): ...` (not a runtime error, same exit code 1).
Very deep recursion overflows the 1 MB stack and crashes.

## 9. Compile errors and warnings
`file: error: line N: message`, `file: warning: line N: message`. The texts are fixed by `tests/err_*.ko` and their `tests/results/err_*.error` files (`.warn` for warnings).
- *lexical:* `unexpected character '\t'`, `string is not closed`, `bad escape ^q`, `bad unicode escape`, `cannot join '...' and "..." strings`,
  `comment '--[[' is never closed`, `bad number '12ab'` (with a hint for `1__0` and `0b101`), `bad hex literal` (`#` and `0x` forms), `hex literal too large`, `bad binary literal`, `binary literal too large`,
  `bad number '1.5abc...'`, `a float needs digits after the dot` / `before the dot`, `float literal too large`, `integer literal too large`.
- *layout / syntax:* `unexpected indentation`, `inconsistent indentation`, `expected an indented block after ':'`, `'(' is never closed`, `'{' is never closed`,
  `unmatched '}'`, `unmatched ')'`, `expected end of statement, found ...`, `unexpected end of line in expression`, `unexpected 'else'`,
  `expected '{' or ':' after the parameters`, `expected '(' or a parameter name`, `expected '!'`,
  `'break' outside of a loop`, `'return' outside of a function`, `'=' (return) needs a value`, `duplicate parameter 'a'`,
  `too many parameters (at most 20)`, `function 'f' is already defined in this scope`.
- *names:* `undefined variable 'x'`, `undefined global variable 'x'`, `variable 'x' used before assignment`,
  `variable 'x' is local to function 'f' and used before assignment (use '^x' ...)`, `'x' is already local to 'f', it cannot also be used as '^x'`,
  `'x' is used as '^x' in 'f', so it cannot also be a local variable there`, `'@x' needs an enclosing function`, `'@x': no variable 'x' in an enclosing function`, `'f' is a function (defined with 'function') and cannot be assigned`.
- *constants:* `constant 'X' can only be defined directly at the top level of the program or of a function (not inside an 'if', a loop or another block)`,
  `constant 'X' cannot be written as ^X (a constant belongs to the scope where it is defined)`, `constant 'X' is already defined (line N)`,
  `constant 'X' cannot be changed`, `'@X': a constant cannot be an enclosing function's variable`, `parameter 'N' looks like a constant`,
- *types:* `type mismatch <where>: expected T, found U` (`in assignment to 'x'`, `in argument 2 of the call`, `in left operand of '+'`,
  `in the condition of 'if'`, `in 'print' (only numbers, str and text can be printed)`, `in 'return' (all returns of a function must agree)`, ...),
  `the result is float, expected int`, `wrong number of arguments: the function takes N, called with M`, `an int is not a function` (or `a float ...`),
  `expected a number, found fn()`, `cannot mix text and str`, `cannot compare str and int`, `in '?!' (both branches must have the same type, or both be numbers)`, `in the condition of '?'`.


## 10. Characters (JFYI)
| char | usage |
|---|---|
| ' | byte string `str` |
| " | unicode string `text` |
| # | hex literal `#ff`, binary literal `2#101`; `# ` comment |
| ! | unary not, conditional `c ? a ! b`, != - not equal |
| ? | unary random and time, conditional `c ? a ! b` |
| / | unary - nothing, float division; /= |
| % | unary - nothing, modulo (floored); %= |
| & | unary - nothing, bitwise and, && - logical and; &= &&= |
| \| | unary absolute value / length, bitwise or, \|\| - logical or; \|= \|\|= |
| ~ | unary bitwise not, xor; ~= |
| * | unary prime test, multiply; \*= ; `<*` `*>` rotate |
| + | identity, plus; += ; `+>` arithmetic shift right |
| - | negative, minus; -= |
| < | unary - nothing, less; <= - le; `<<` shift left, `<*` rotate left |
| > | unary - nothing, greater; >= - ge; `>>` shift right, `+>` `*>` |
| = | return, assignment, == - equal |
| , | separate parameters, arguments |
| : | start block, unary - nothing |
| ; | separate statements, unary - nothing |
| \\ | function (synonym of `function`) where an operand or statement is expected; integer division (binary); \\= |
| ^ | global variable (prefix), power (binary); ^= |
| _ | 'blank' in ids and numbers, ids can start/end with it |
| @ | upper-level variable |
| () | expressions, parameters, arguments |
| {} | block |
| [] | - |
| . | - |
| ` | - |
| $ | - |
