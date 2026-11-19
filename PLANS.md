## Not in the language (yet)
- strings (bytes and unicode) as values; then with ops (`|x` `x+y` `x*n` `n*x` etc); short strings 0-7 chars kept in 64-bit words;
- a garbage collector;
- call syntax: f a; f a,b,c; etc;
- multi-value assignment, returns; multiple split [with 'rest' \*]
- floats: **yet to do:** more float literals (pi-based), `INF` and `NAN` (literals, tests, and `0.0/0.0`-like
  results are only reachable through overflow now), comparison with tolerance (comparisons are exact for now),
  (**pragma** tolerance - no), output formatting (**pragma** precision? proper formatting: precision, width, layout;
  the 15-digit format is provisional), explicit conversion int <-> float (`int(x)`, `float(i)`, rounding,
  floor/ceil), implicit conversion on assignment (strict now), math functions (sqrt, sin, ...);
- INF, NAN -- #inf -#inf #nan; #pi, #tau
- many int and float types (other sizes)
- arrays (lists); literals 1 2 3 \_4, 5.0 6 \_7, [5.0,6,\_7], ["s","tt"]; gen 0$100, 1.0$10, ""$5
- dictionaries, sets, tuples;
- structures; classes;
- enums;
- big integers;
- `assert` expr [, str]
- `for` loops;
- `until cond loop`;
- `else` on loops;
- `swich` or `case` statement;
- `break 2` or `break break`
- radix 3..36 literals 3#122 8#377 36#zzz;
- `f(1)` and `f(1.5)` cannot both be called in this order, but the reverse is ok: convert int to float --
  implicit conversion; also make general rules of implicit conversion. and make explicit conversion.
- `function f(x):y` === `f=\(x):y`? stackless?
- modules, import;
- named and optional arguments;
- input (no way to read a value yet); get;
- print --> put;
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
- integer overflow detection (as **pragma** int-overflow? other checks as pragmas: OVFL, INIT, ZDIV, BNDS, NULL, ASRT);
- pragmas
```
Checks: OVF, ASSERT, BOUNDS, NULL, INIT, ZERODIV (hardware), FP (produce INF, NAN, UFL)
#-O #+O -- --overflow
#-I #+I -- --initialization
#-A #+A -- --assert
#-B #+B -- --bounds
#-N #+N -- --null
comp.tolerance, output.precision -- not worth, don't do
#CT=0
#CT=n -- digits
#CT=0.0|1e-14 -- tolerance
-- abs(a-b) < CT\*max(abs(a),abs(b))
```
I think at file level it must be this way: when a piece of code is compiled that needs such flag (i.e. int a = b + c;),
a global file flag is set "flag is used" (if it was set as compiler option, fine). naturally, initially it's
"flag not used". then when we see construction #pragma check(ovf,on), we check this flag - if it's not yet used, great,
we just set this option. if it is 'used' - it means that the flag is set later than it should have been.
That "latch" or "seal" mechanism (flag_used state tracking) is a classic, rock-solid compiler design pattern
the moment any code actually consumes it.
OVF.is_locked = true
- is prime fn
```
bool is_prime(int64_t n)
{
  if(n<4) return n>1; // check!
  if((n & 1) == 0 || n % 3 == 0) return false;
  for(int64_t i = 5; i * i <= n; i += 6)
  {
    if(n % i == 0 || n % (i + 2) == 0) return false;
  }
  return true;
}
```
- ops:

| ch | unary | binary | others |
|---|---|---|---|
| !  | not              | ?!          |                                 |
| ?  | random           | ?!          |                                 |
| \\ | function         | int div, drop       |                         |
| /  | strip            | float div, take     |                         |
| %  | split_blanks     | modulo, split       |                         |
| \| | abs, len         | bitwise or, find       | \|\| logical or      |
| &  |                  | bitwise and, contains  | && logical and       |
| ~  | bitwise not      | bitwise xor, match  |                         |
| *  | scatter?         | multiply, repeat    |                         |
| +  | identity, upper  | plus, concat        |                         |
| -  | negate, reverse  | minus       |                                 |
| <  |                  | less        | << shift left   <\* rotate left |
| >  |                  | greater     | >> shift right  \*> +> ...      |
| =  | return           | assignment  | == equal                        |
| :  |                  | block       |                                 |
| ;  |                  | statements  |                                 |
| ^  | global var       | power       |   ..starts with                 |
| @  | upper-level var  | char-at     |                                 |
| \` |                  |             |                                 |
| $  | dim              | reshape     |   ..ends with                   |
| .  |                  | floats      |                                 |

