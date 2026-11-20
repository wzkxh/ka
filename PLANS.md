## Not in the language (yet)
- str concatenation `x+y`;
- str repetition `x*n` `n*x`;
- `|x` unary abs (numbers) and len (str);
- short strings 0-7 chars kept in 64-bit words; literals - maybe one table;
- a garbage collector;
- unicode string (**text**), assignment, usage, parameter pass, type check;
- text concatenation `x+y`;
- text repetition `x*n` `n*x`;
- `|x` unary len (text);
- call syntax: f a; f a,b,c; etc;
- multi-assignment a=b=c=v;
- multi-value assignment (a,b=x,y); returns;
- multi-value with split (a,b,\*c = x,y,p,q,r);
- float literals: #inf -#inf #nan; #pi, #tau (or like in J?);
- fns floor/ceil;
- implicit conversion on assignment (strict now); on calls; rules;
- `f(1)` and `f(1.5)` cannot both be called in this order, but the reverse is ok;
- explicit conversion int <-> float, rounding; str <-> number; formatting;
- ord/chr, str/text; array <-> str/text; parse, format, 'fmtstr'(args);
- input (no way to read a value yet); get;
- print --> put;
- fn(x,...) <=> x.fn(...);
- many int and float types (other sizes);
- arrays (lists); literals 1 2 3 \_4, 5.0 6 \_7, [5.0,6,\_7], ["s","tt"];
- array generator 0$100, 1.0$10, ""$5
- shape $a;
- dictionaries, sets, tuples;
- structures; classes;
- enums;
- bool?; #true, #false or 0# 1#;
- big integers;
- `assert` expr [, str]
- `for` loops;
- `until cond` loop;
- `else` on loops -- not sure;
- `select` or `switch` or `case` statement;
- `break 2` or `break break`
- radix 3..36 literals 3#122 8#377 36#zzz;
- `function f(x):y` === `f=\(x):y`? stackless?
- modules, import;
- named and optional arguments;
- more operations on strings, numbers;
- `#'...'` hex strings
- `"^ctrl..."` multi-line strings, with/without indents, with/without interpretation, etc.
- standard library (functions and/or operators):
  - os/file system: open/close, read/write, properties, dir, start, current_time;
  - strings: replace, regex;
  - math functions (sqrt, sin, cos, tan, atan (atan2), exp, log);
  - time, date, etc;
- checking that every path of a function returns a value of the declared kind;
- optimization;
- void; fns returning void; warning about calls whose value is not used;
- if it's not too much work (≈10%), make an option to print out AST. This is rather optional;
- if it's not too much work (≈10%), make an option to print out Assembler listing. This is VERY optional;
- like in PL/I, dump vars with their types. Very optional too;
- integer overflow detection (**pragma** OVFL, other checks: INIT, ZDIV, BNDS, NULL, ASRT);
- pragmas & cli options
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
int64_t is_prime(int64_t n)
{
  if( n<4 ) return n>1;
  if( (n & 1) == 0 || n % 3 == 0 ) return 0;
  for( int64_t i = 5; i*i <= n; i += 6 )
  {
    if( n%i == 0 || n%(i+2) == 0 ) return 0;
  }
  return 1;
}
```

| Upper bound of n | Typical time (prime) | Notes |
| --- | --- | --- |
| ≤ 10⁶ – 10⁷ | < 0.001 ms | Instant |
| ≤ 10⁹ | ~ 0.01–0.1 µs | Still essentially free |
| ≤ 10¹¹ | ~ 1–5 µs | Negligible |
| ≤ 10¹² | ~ 0.05–0.2 ms | Fine for most uses (practical limit) |
| ≤ 10¹³ | ~ 0.3–1 ms | Still very usable |
| ≤ 10¹⁴ | ~ 3–10 ms | Acceptable for occasional calls |
| ≤ 10¹⁵ | ~ 30–50 ms | Noticeable but ok |
| ≤ 10¹⁶ | ~ 0.1–0.2 s | Starting to feel slow |
- ops:

| ch | unary | binary | others |
|---|---|---|---|
| !  | not              | ?!          |                                 |
| ?  | random           | ?!          |                                 |
| \\ | function         | int div, drop       |                         |
| /  | sqrt, strip      | float div, take     |                         |
| %  | split_blanks     | modulo, split/join  |                         |
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
| $  | shape/size/dim   | reshape     |   ..ends with                   |
| .  |                  | floats      |                                 |

