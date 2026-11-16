## Not in the language (yet)
- `f(1)` and `f(1.5)` cannot both be called in this order, but the reverse is ok: convert int to float.
- function f(x):y === f=\(x):y. stackless?
- strings (bytes and unicode) as values; then with ops (|x x+y x*n n*x etc); short strings 0-7 chars kept in 64-bit words;
- a garbage collector;
- call syntax: f a; f a,b,c; etc;
- multi-value assignment, returns;
- floats: **yet to do:** more float literals (pi-based), `INF` and `NAN` (literals, tests, and `0.0/0.0`-like
  results are only reachable through overflow now), comparison with tolerance (comparisons are exact for now),
  (**pragma** tolerance?), output formatting (**pragma** precision? proper formatting: precision, width, layout;
  the 15-digit format is provisional), explicit conversion int <-> float (`int(x)`, `float(i)`, rounding,
  floor/ceil), implicit conversion on assignment (strict now), math functions (sqrt, sin, ...);
- INF, NAN -- #inf -#inf #nan
- many int and float types (other sizes)
- arrays (lists), dictionaries, sets, tuples;
- enums;
- big integers;
- `assert` expr [, str]
- `for` loops;
- `until cond loop`;
- `else` on loops;
- `swich` or `case` statement;
- `break 2` or `break break`
- radix 3..36 literals 3#122 8#377 36#zzz;
- modules, import;
- integer overflow detection (as **pragma** intoverflow? other checks as pragmas);
- named and optional arguments;
- input (no way to read a value yet);
- operations on strings (+ etc), numbers (?);
- `#'...'` hex strings
- `"^ctrl..."` multi-line strings, with/without indents, with/without interpretation, etc.
- standard library (functions and/or operators):
  - file system, i/o;
  - strings;
  - math;
  - time, etc;
- checking that every path of a function returns a value of the declared kind;
- optimization;
- void; fns returning void; warning about calls whose value is not used;
- if it's not too much work (≈10%), make an option to print out AST. This is rather optional;
- if it's not too much work (≈10%), make an option to print out Assembler listing. This is VERY optional;
- like in PL/I, dump vars with their types. Very optional too;
- ops:

| ch | unary | binary | others |
|---|---|---|---|
| !  | not              | ?!          |                                 |
| ?  | random?          | ?!          |                                 |
| \\ | function         | int div, drop?      |                         |
| /  | strip?           | float div, take?    |                         |
| %  |                  | modulo, split?      |                         |
| \| | abs, len?        | bitwise or, cut?       | \|\| logical or      |
| &  |                  | bitwise and, contains? | && logical and       |
| ~  | bitwise not      | bitwise xor, match? |                         |
| *  | scatter?         | multiply, repeat    |                         |
| +  | identity, upper? | plus, concat        |                         |
| -  | negate,   lower? | minus       |                                 |
| <  |                  | less        | << shift left   <\* rotate left |
| >  |                  | greater     | >> shift right  \*> +> ...      |
| =  | return           | assignment  | == equal                        |
| :  |                  | block       |                                 |
| ;  |                  | statements  |                                 |
| ^  | global var       | power       |   ..starts with                 |
| @  | upper-level var  | char-at     |                                 |
| \` |                  |             |                                 |
| $  |                  |             |   ..ends with                   |
| .  |                  | floats      |                                 |

