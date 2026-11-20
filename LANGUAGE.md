# Ka - language reference

Ka is a small imperative language with 64-bit integers and floats, first-class functions and closures, checked by static types.
`ka.py` compiles a `.ka` source file into a Windows x64 console `.exe` (the version is the `VERSION` constant at the top of `ka.py`).
This file defines the language; the reasons behind the decisions are in IMPLEMENTATION.txt, the history in RELEASE_NOTES.md.

## 1. Lexical structure
- Source is UTF-8 text. Line endings `\n` or `\r\n`.
- TAB is like any other control (e.g. BEL, ESC, HT) or unexpected (`$`,`½`,`∞`) character: text inside strings and comments,
  `unexpected character` anywhere else. Indentation consists of spaces only.
- **Comments:**
  - `--` to the end of the line.
  - `# ` to the end of the line: a hash followed by a space or by the end of the line, but not directly after a digit (`2#` starts a binary literal).
  - `--[[ ... ]]--` inside one line; code continues after it: `print 1 --[[ one ]]-- + 2`.
  - `--[[ ... --]]` over several lines; the rest of the line that holds the closing `--]]` is ignored.
    If `]]--` follows `--[[` on the same line, it is the inside-line form.
  - An unclosed `--[[` is an error. `--` inside a string is text.
- **Identifiers:** ASCII letters, digits, `_`; not starting with a digit.
- **Keywords:** `if elif else while break continue print exit function return skip`. `\` is a synonym of `function` where
  an operand or statement is expected.
- **Integer literals:** decimal digits, -9223372036854775808 .. 9223372036854775807. `_` may separate digits (`1_000_000`), not at the
  start or the end and not doubled.
  Hexadecimal `#ff`, `#FF_FF` or `0xff`, `0XFF_FF` (digits `0-9 a-f A-F`, `_` between digits) and binary `2#0001_1011` (base 2 only) may use all 64 bits:
  `#ffffffffffffffff`, `0xFFFFFFFFFFFFFFFF` and 64 binary ones are -1.
- **Float literals** (64-bit): `digits.digits`, `digits[.digits]e|E[sign]digits`; digits are 0-9 with optional `_` between digits:
  `1.5`, `1_000.25`, `6.02e23`, `1E-9`, `5e3` (the float 5000.0).
  No `.5`, no `1.`, no infinity or NaN literal (yet). Too large for a double is an error, too small gives 0.0 or a denormal.
- **String literals:** `'...'` is a byte string (`str`), `"..."` a unicode string (`text`). Byte strings can be values; unicode strings are still only printable literals. A string cannot contain a raw newline.
  - Escape character `^`: `^n` newline, `^t` TAB, `^r` CR, `^^` caret, `^"` quote, `^'` apostrophe (both quotes in both kinds).
  - `^XX` (two hex digits, `^e9`, `^E9`, `^00`): the byte XX in a byte string; the character U+00XX in a unicode string.
  - `^uXXXX` (4 hex digits), `^UXXXXXX` (6 hex digits): a Unicode character (to 10FFFF, no surrogates); in a byte string its UTF-8 bytes.
  - Other characters stand for themselves; non-ASCII source text becomes UTF-8 bytes. Any other escape is an error.
  - A string may contain the byte 0.
  - String literals written one after another are joined: `'a' 'b' 'c'`. A string over several lines is written in parentheses
    (`print ("one" NEWLINE "two")`) or with a line ending in `,`. `'...'` and `"..."` cannot be joined.
  - Byte strings (`str`) are immutable values. They can be assigned to variables, copied between variables, passed as function arguments, and returned from functions. Assignment copies a 64-bit pointer; the string data is shared. The empty byte string is represented by a null pointer. Other values point to a static object containing a 64-bit byte length followed by the bytes.
  - Unicode strings (`text`) remain limited to `print` literals; they are not values yet.
  - `print` accepts numbers, byte-string variables, and either kind of string literal.
  - Output is written as UTF-8 bytes; the program sets the console code page to UTF-8 at start.
- **Compatibility forms:** `# ` comments and `0x` hex literals exist only to ease the migration of existing sources and programs from other languages, and for the
  ease of copying code and constants between them. They are not Ka style and are discouraged in new programs: write `--` comments and `#ff` / `2#...` literals.
- **Operators / punctuation:** `+ - * / \ % ^ & | ~ << >> +> <* *> == != < <= > >= && || ! ? = ( ) { } ; , : @`
  and the assignment forms `= += -= *= /= \= %= ^= &= |= ~= &&= ||= <<= >>= +>= <*= *>=`.

## 2. Values and types
Three types:
- **int** - 64-bit signed integer (two's complement, arithmetic wraps);
- **float** - 64-bit IEEE 754 number;
- **function** - a closure; written `fn(T1,T2)->R` in compiler messages.

Types are checked at compile time, never written, and inferred:
- A variable has the type of the first value assigned to it; later values must have the same type.
- A parameter gets its type from its use in the body and from the calls; a function has one signature.
  `function f(a): print "x"` called as `f(1)` is `f(int)`; `f(f)` is then an error.
- A function's result type is the type of its `return` expressions, which must agree.
  `return` without a value and falling off the end give the int 0 (not checked).
- Calls check the number and types of the arguments. Calling a number is an error.
- Function types may refer to themselves (`function f(a): return a(a)` with `d = f(q)`, `function q(x): return x`).
- **Numbers** (int, float) are accepted by `+ - * / \ % ^`, unary `-` `?`, `< <= > >= == !=`, `&& || !`, conditions of `if`, `while`, `?!`, and `print`.
  **Ints only** are accepted by `& | ~ << >> +> <* *>`, unary `~` and `exit`.
  Functions are accepted by `==` and `!=` (equal if they are the same function; same signature).
- **Int and float mix inside operators:** `+ - * % ^` give a float if either side is a float (the other side is converted), else an int.
  `/` always gives a float, `\` always an int. A comparison with a float operand is done on floats.
  `1 + 0.5` is 1.5, `7 / 2` is 3.5, `7 \ 2` is 3, `1 == 1.0` is 1.
- There is no other implicit conversion: assigning, passing or returning a float where an int is expected is an error, and vice versa
  (`x = 0` then `x = 0.5` is an error; `f(1)` and `f(1.5)` cannot both be called).
- The branches of `c ? a ! b` have the same type, int and float mix as in an operator.
- Truth: `0`, `0.0` and `-0.0` are false, any other number (also NaN) is true. Comparisons and logical operators give the int `0` or `1`.

## 3. Statements and lines
- A statement ends at the end of the line, at `;`, at a closing `)` or `}`, at `else`/`elif`, or where another statement starts with a
  keyword (`if while break continue print exit return skip function`) or with `{`. So `;` is needed only to separate statements
  on one line when the next one starts otherwise: `a = 1; b = 2`; `i = i + 1 if i == 2: print i` needs none.
- A statement continues on the next line if the line ends with `+ - * / \ % ^ & | ~ << >> +> <* *> ! ? == != < <= > >= && || = ,` or an `op=` form,
  or while a `(` is open (newlines inside parentheses are ignored; inside `{ }` they count again).
- Blank lines and comment-only lines are ignored.
- An expression statement that is not a call gives the warning `the value of this expression is not used`.

## 4. Blocks
A block follows `if cond`, `elif cond`, `else`, `while cond`, `function name(...)`, `function(...)`. Three forms:
1. **Braces** `{ ... }`; layout is free; the `{` may be on the next line. These blocks are mainly for usage in one line.
2. **Indented:** (like Python) `:` at the end of the line and more-indented lines. The block ends when the indentation returns. Extra indentation
   after a line not ending in `:` and a dedent to an unknown column are errors.
3. **One-line:** `:` followed by statements on the same line, up to the end of the line or to a closing `)`, `}` or `,` of an enclosing construct.
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
| 13 | unary `-` `~` `!` `?` |
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
- **Random numbers**, unary `?x`: for an int `n > 0`, `?n` is an int in `0 .. n-1`; `?0` is the next raw 64 bits as an int;
  for an int `m < 0`, `?m` sets the state of the generator to `-m` (for the smallest int: to itself) and gives 0;
  for a float `x > 0.0`, `?x` is a float in `[0, x)` (for other floats the result is not defined). `?x` has the type of `x`.
- **Conditional** `c ? a ! b`: `c` is evaluated, then only `a` or only `b`. A function literal with a one-line body inside it needs parentheses:
  `c ? (\x:=x+1) ! (\x:=x-1)`. A line may end with `?` or `!` (expression continues on the next line).
- **Chained comparisons:** `a < b <= c` is `a < b && b <= c` with `b` evaluated once; evaluation stops at the first false link.
  Chains form within `== !=` or within `< <= > >=`; `a < b == c` is `(a < b) == c`.

## 6. Statements
| statement | meaning |
|---|---|
| `name = expr`, `^name = expr`, `@name = expr` | assign, creates a variable / a global / an enclosing function's variable (see 7) |
| `name op= expr` | `name = name op expr` for `+ - * / \ % ^ & \| ~ && \|\| << >> +> <* *>`; `&&=` and `\|\|=` short-circuit; also `^name op= expr`, `@name op= expr` |
| `print a, b, "text", ...` | print the items one after another, then a newline; `print` alone prints an empty line. Items are numbers, `str` values, or string literals |
| `if cond block [elif cond block]... [else block]` | conditional (`else if` also works) |
| `while cond block` | loop |
| `break`, `continue` | only inside a `while` of the same function |
| `exit expr` | end the program with that exit code (the end of the file exits with 0) |
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
- `function name` definitions of a scope are created when the scope is entered, so they can be used before the definition. A definition inside an
  `if` or loop still belongs to the enclosing scope and is not conditional. A named function is a variable holding a function value (reassignable
  to a function of the same signature). Defining a name twice with `function` in one scope is an error. `function ^name` does not exist.
- Recursion works, also mutual and through variables holding literals.

### Scope
- Outside functions variables are global. Inside a function, parameters and every name assigned by a plain `name = ...` are local for the whole body.
- A function reads globals and variables of the functions around it by plain name. Using a local name before its first assignment is an error.
- `^name` is the global variable `name`, mainly for assignment: `^name = e` assigns it (creating it), `^name` reads it; at the top level it equals `name`.
  Once `^name` is used in a function, the plain `name` there is the global too. A name cannot be both local (or parameter) and `^name` in one function.
- `@name` (draft, like `nonlocal` in Python) is the variable `name` of the nearest enclosing function that has it as local or parameter: `@name = e` assigns, `@name` reads; the plain
  name then means the same. A name cannot be both local and `@name` in one function; without such a variable it is an error.
- Every variable starts as 0 (yet to decide). A variable assigned only on a path not taken stays 0. A function variable that is 0 is unset; calling it is a runtime error.
- A function value shares the variables it uses with its creator and other closures, also after the creator has returned. Captured variables and closures are never freed.
- Top-level code that reads a global before assigning it is an error unless some function assigns it with `^var`.

### Constants
A name of capital letters, digits and `_` with at least one letter (`MAX_SPEED`, `X2`, `_N`) is a constant; a name with a lowercase letter is a variable.
- A constant is defined by `NAME = expr` or `function NAME(...)` directly in the statements of the program or of a function body: not inside `if`, `elif`,
  `else`, a loop or a `{ }` block. Its scope is the program or that function (also the functions nested in it). A function may define a constant of the
  same name as a global one. A constant cannot be written as `^NAME` or `@NAME` inside a function. Parameters cannot have such names.
- It is defined once: any second assignment (`NAME = ...`, `NAME += ...`) is an error.
- The value must be a constant expression: numbers, constants defined above (in this scope or around it), operators (also `?!`), function literals.
  Variables and calls are not allowed (`WIDTH = 80`, `AREA = WIDTH * HEIGHT`, `FLAG_B = FLAG_A << 1`, `FACT = \n: =n < 2 ? 1 ! n * FACT(n-1)`).
- The constants of a scope are created first, in the order written, when the scope is entered (program start, function entry); they can be read
  anywhere in the scope, also above the definition.

## 8. Runtime errors
Written to standard output, exit code 1:
`runtime error: division by zero` (`/ \ %` with a zero divisor, `0.0 ^ negative`),
`runtime error: negative exponent` (int `^`),
`runtime error: power of a negative number with a fractional exponent`,
`runtime error: call of an unset function`.
Very deep recursion overflows the 1 MB stack and crashes.

## 9. Compile errors and warnings
`file: error: line N: message`, `file: warning: line N: message`. The texts are fixed by `tests/err_*.ka` and their `tests/results/err_*.error` files (`.warn` for warnings).
- *lexical:* `unexpected character '\t'`, `string is not closed`, `bad escape ^q`, `bad unicode escape`, `cannot join '...' and "..." strings`,
  `comment '--[[' is never closed`, `bad number '12ab'` (with a hint for `1__0` and `0b101`), `bad hex literal` (`#` and `0x` forms), `hex literal too large`, `bad binary literal`, `binary literal too large`,
  `bad number '1.5abc...'`, `a float needs digits after the dot` / `before the dot`, `float literal too large`, `integer literal too large`.
- *layout / syntax:* `unexpected indentation`, `inconsistent indentation`, `expected an indented block after ':'`, `'(' is never closed`, `'{' is never closed`,
  `unmatched '}'`, `unmatched ')'`, `expected end of statement, found ...`, `unexpected end of line in expression`, `unexpected 'else'`,
  `expected '{' or ':' after the parameters`, `expected '(' or a parameter name`, `expected '!'`, `a unicode string can only be printed (it is not a value)`,
  `'break' outside of a loop`, `'return' outside of a function`, `'=' (return) needs a value`, `duplicate parameter 'a'`,
  `too many parameters (at most 20)`, `function 'f' is already defined in this scope`.
- *names:* `undefined variable 'x'`, `undefined global variable 'x'`, `variable 'x' used before assignment`,
  `variable 'x' is local to function 'f' and used before assignment (use '^x' ...)`, `'x' is already local to 'f', it cannot also be used as '^x'`,
  `'x' is used as '^x' in 'f', so it cannot also be a local variable there`, `'@x' needs an enclosing function`, `'@x': no variable 'x' in an enclosing function`.
- *constants:* `constant 'X' can only be defined directly at the top level of the program or of a function (not inside an 'if', a loop or another block)`,
  `constant 'X' cannot be written as ^X (a constant belongs to the scope where it is defined)`, `constant 'X' is already defined (line N)`,
  `constant 'X' cannot be changed`, `'@X': a constant cannot be an enclosing function's variable`, `parameter 'N' looks like a constant`,
  `the value of constant 'X' must be a constant expression (...): it uses the variable 'a'` (or `it calls a function`, `it uses 'B', which is defined later`).
- *types:* `type mismatch <where>: expected T, found U` (`in assignment to 'x'`, `in argument 2 of the call`, `in left operand of '+'`,
  `in the condition of 'if'`, `in 'print' (only numbers and byte strings can be printed)`, `in 'return' (all returns of a function must agree)`, ...),
  `the result is float, expected int`, `wrong number of arguments: the function takes N, called with M`, `an int is not a function` (or `a float ...`),
  `expected a number, found fn()`, `in '?!' (both branches must have the same type, or both be numbers)`, `in the condition of '?'`.
- *warning:* `the value of this expression is not used`.


## 10. Characters (JFYI)
| char | usage |
|---|---|
| ' | byte string |
| " | unicode string |
| # | hex literal `#ff`, binary literal `2#101`; `# ` comment |
| ! | unary not, conditional `c ? a ! b`, != - not equal |
| ? | unary random, conditional `c ? a ! b` |
| / | unary - nothing, float division; /= |
| % | unary - nothing, modulo (floored); %= |
| & | unary - nothing, bitwise and, && - logical and; &= &&= |
| \| | unary - nothing, bitwise or, \|\| - logical or; \|= \|\|= |
| ~ | unary bitwise not, xor; ~= |
| * | unary - nothing (scatter?), multiply; \*= ; `<*` `*>` rotate |
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
