# Ka - release notes (newest first)

## Current state (version 6.5.2)
## Version 6.5.1
- Fixed chained byte-string comparisons: the comparison helper clobbered `rdx`, and the chain code incorrectly reused it to preserve the middle operand. The current string operand is already saved before calling the helper; do not overwrite it afterward.
- Extended the byte-string comparison test with successful and failing chains of three comparisons.

Ka compiles to a Windows x64 console `.exe` (PE written directly, pure Python 3, no dependencies). The version is the `VERSION` constant in `ka.py`.
- **Language:** 64-bit ints and floats, first-class functions and closures (shared by reference, never freed), static type inference, constants, byte-string (`str`) values, content comparisons and concatenation, and byte/unicode string literals for `print`.
  Details: LANGUAGE.md. Reasons: IMPLEMENTATION.txt.
- **Tests:** 201 programs in `tests/`, including byte-string values, comparisons and concatenation. The complete suite should be run on Windows; the development environment used for this release has no Windows runtime or Unicorn emulator.
- **Checked on real Windows by the user:** all 198 tests of version 6.4 passed.
- **Known limits:** see IMPLEMENTATION.txt section 9 (float printing last digit, fractional float powers checked only in an emulator, no unicode `text` values, no input, no GC).

## Version 6.5
- Byte strings (`str`) support `==`, `!=`, `<`, `<=`, `>`, `>=` by content. Ordering is lexicographical over unsigned bytes; embedded zero bytes are ordinary data.
- `+` concatenates two byte strings; `+=` concatenates and reassigns. A new immutable object is allocated for a non-empty result; old objects are not freed.
- Numeric arithmetic and comparisons retain their existing behavior. Mixed `str`/numeric operations are compile-time errors.
- Added runtime helpers `rt_strcmp` and `rt_strcat`, plus tests for comparisons, chained comparisons, concatenation, compound assignment, functions and type errors.

## Version 6.4
- **Byte strings as values (`str`):** assign literals to variables, copy values, pass/return them through functions, capture them in closures, and print variables. Strings are immutable; variables copy a 64-bit pointer. Empty string is null; non-empty literals use static `[u64 length][bytes]` objects in `.data`. No allocation or freeing is needed yet.
- Unicode (`text`) literals remain printable only, not values. Unicode (`text`) values, operations, and GC are not implemented.
- 1 runtime test and 3 type-error tests added.

## Version 6.3
- **Random numbers:** the unary operator `?x`; int/float: `?n -> 0..n-1`, `?x -> [0.0..x)`.
- 3 new tests: `62_random`, `err_const_random`, `err_type_random_function`.

## Version 6.2.1 (no change to the compiler)
- **Tests:** `tests/` holds only the `.ka` programs now; the expected output, exit codes, warnings and expected errors are in `tests/results/` (`run_tests.py` and `tools/annotate_tests.py` updated).
- `tools/annotate_tests.py --check`: verifies that every `-- =>` comment tells what the program really prints (the annotator used to skip lines that already had a comment, so a comment could become stale
  after a change of behaviour: test 48 had one after 6.2, fixed by the user). All comments agree now.
- `performance/cs.ka` fixed: `n = n / 2` is a float division since version 6 (the program no longer compiled); it is `n \ 2` now, as `//` in the Python version. All eight benchmarks were compared with their Python versions at reduced sizes: same results. The timings in `performance/benchmarks.txt` are older; `%` and `\` on ints cost a few instructions more since 6.2 (floor correction), so `cs` and `prime` may be a little slower.
- Docs: `PLANS.md` replaces `TODO.txt` (README, NOTES, IMPLEMENTATION updated; README said `PLANS.txt`); a missing parenthesis in LANGUAGE.md.

## Version 6.2
- **Floored division and modulo** (incompatible for negative operands): `a \ b` is floor(a / b) (toward minus infinity) and `a % b` has the sign of `b`, for ints and floats, so `-7 \ 3` is -3,
  `-7 % 3` is 2, `7 % -3` is -2, and `a \ b * b + a % b == a` holds for ints (for floats up to rounding). Before, both truncated toward zero (`-7 % 3` was -1). A zero float remainder is `+0.0`.
- **Fixed: float `\`** was off by one in rare cases (the intermediate quotient was truncated instead of rounded; versions 6 and 6.1: `6049232.4789095735 \ 455.61461813570327` gave 13276, the right answer is 13277).
- `# ` comments and `0x` literals are documented as compatibility forms (for migrating and copying from other languages), discouraged in new programs.
- `ka.py --version` removed (the `VERSION` constant is enough).
- 1 new test (191 total); the expectations of 3 tests with negative operands changed (02, 48, 56).

## Version 6.1
- **Hex literals `0xFF`** (also `0XFF`, `0xFF_FF`) in addition to `#FF`; 64 bits, wrap to signed (`0xFFFFFFFFFFFFFFFF` is -1).
- **Comments `# text`** (a hash followed by a space or by the end of the line, not directly after a digit) in addition to `--`. `err_hash_comment` is valid syntax now.
- **Error message for ill-formed numbers:** `bad number '12ab'` no longer claims that `_` is the problem; the `_` hint appears only when there is a `_`; `0b101` gets a hint (`2#101`);
  bad `0x` forms give `bad hex literal`.
- 10 new tests and 1 removed (190 total): 0x literals, hash comments, and the number error messages. (The first draft of the `#` rule made `x = 2#` a valid statement; a test caught it, see IMPLEMENTATION.txt.)

## Version 6
- **Division:** `/` is now always float division (`7 / 2` is `3.5`); the new `\` is integer division, always an int, also for floats (`7.5 \ 2` is 3); `\=` added. `/=` on an int variable is therefore
  a type error, use `\=`. **Incompatible change:** old programs that divided ints with `/` must use `\`.
- **Shifts:** a negative count shifts the other way (`1 >> -3` is 8); rotates by negative counts already rotated the other way.
- **Constants inside functions:** a capital-named `NAME = constant expression` (or `function NAME`) may be defined directly in a function body; its scope is that function and the functions nested
  in it; created at function entry; may shadow a global constant. Errors for definitions inside `if`/loops/blocks, `^X`/`@X`, second definitions.
- `\` is no longer a statement boundary: after a complete statement, `\` is the division operator, so a function definition starting with `\` needs `;` or a new line.
- `ka.py --version`; `VERSION` in ka.py.
- **Tests:** 12 new tests (division, negative shift counts, function constants, runtime errors), several migrated to `\`. All tests got `-- =>` comments with the results (and `-- ERROR:` at the failing
  line of `err_*` tests); the 1-space indents are 2 spaces now. New tool `tools/annotate_tests.py`.
- **Docs:** split into LANGUAGE.md (short definition), IMPLEMENTATION.txt (decisions, reasons, issues), NOTES.md (for Claude), RELEASE_NOTES.md (this file), TODO.txt (next steps), README.md.

## Version 5 - floats
- **64-bit floats:** literals `1.5`, `1_000.25`, `6.02e23`, `1E-9`, `5e3`; no `.5`, `1.`, INF, NAN.
- Operators `+ - * / % ^` and unary `-` on floats, exact comparisons (also chained), truth values, `?:`; bit operators, shifts and `exit` need ints. Int and float mix inside operators (the int is
  converted); assignment, arguments and `return` are strict.
- `print` of floats: 15 significant digits, Python-like layout (`0.1 + 0.2` prints `0.3`, `100.0`, `1e-05`, `inf`, `nan`).
- Float runtime in machine code (print, power, fmod) built from `tools/float_rt.asm`; `tools/fuzz_float.py` checks it in the emulator. Checker: constraints for operators with mixed types.
- Float division/modulo by zero is a runtime error; new runtime error for a negative base with a fractional exponent. 36 new tests (169 total).
- Documented "yet to do": more literals, INF, NAN, comparison tolerance, formatting, explicit conversion.

## Version 4
- **Binary literals** `2#0001_1011`.
- **Compound assignment** `+= -= *= /= %= ^= &= |= ~= &&= ||=` and the shift forms.
- **Shifts and rotates** `<<  >>  +>  <*  *>` (arithmetic left shift = `<<`, no separate operator).
- **Constants:** names in capitals, defined once at the top level with a constant expression, created at program start. 133 tests.

## Version 3
- **`function` keyword with the synonym `\`**; one parameter without parentheses;
- `fn` removed (now it's `function` or `\` (looks like **λ**));
- recursive function types allowed;
- documented that **variables start as 0**;
- `@x` for variables of the enclosing function (replaced `\x`);
- `{ ... }` as an ordinary statement;
- **empty statement** `skip`;
- **conditional expression** `c ? a ! b`; unary operators bind tighter than `^` (`-2^2` is 4); bit operators between `+` and comparisons; TAB no longer special; 2-space indentation in code and tests;
- 107 tests.

## Version 2 - Ka
- Rename Tiny -> Ka (`ka.py`, `.ka`). Language reworked by the user: comments `--`, `--[[ ]]--`, `--[[ --]]`; `elif`; removed `let input and or not global nonlocal`; `&& || !`; globals `^x`;
  strings `'...'` / `"..."` with `^` escapes and joining; `_` in numbers; `#hex`; static types (int, function); bit operators `& | ~`; chained comparisons; `=` as `return`; nested one-line bodies;
  `\x` for enclosing-function variables (draft); max 20 parameters. Compiler, type checker and tests rebuilt (95 tests).

## Version 1 - Tiny
- The first language "Tiny" (`.tiny`): `let`, `input`, `global`, `nonlocal`, `and/or/not`, expression-bodied functions, first-class functions with closures, compiled to a PE `.exe` by `tinyc.py`; 49 tests. (I just asked Claude 'can you write a compiler ...' and expected 'I can' or some conditions etc, but in 3 minutes it just returned the first version of compiler, quite capable!)

## Version 6.5.2
- **Tests:** 202 programs (201 existing plus the empty-string regression test).
- Fixed `rt_strcmp` null-left handling: the pointer-null test was followed by `cmp`, which overwrote the condition flags before the branch. Empty-left comparisons such as `'' < 'a'` could dereference address zero.
- Added regression coverage for empty-string comparisons in both operand positions and chained comparisons.
