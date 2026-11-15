# Ka - release notes (newest first)

## Current state (version 6)
Ka compiles to a Windows x64 console `.exe` (PE written directly, pure Python 3, no dependencies). Run `python ka.py --version`.
- **Language:** 64-bit ints and floats, first-class functions and closures (shared by reference, never freed), static type inference, constants, byte/unicode string literals for `print`.
  Details: LANGUAGE.md. Reasons: IMPLEMENTATION.txt.
- **Tests:** 181 programs in `tests/` (all pass under the emulator on Linux; the user runs them on real Windows). Every test has `-- =>` result comments.
- **Checked on real Windows by the user:** all tests of versions 3, 4, 5 passed (169 tests). Version 6 has been run in the emulator only so far.
- **Known limits:** see IMPLEMENTATION.txt section 9 (float printing last digit, fractional float powers checked only in an emulator, no strings as values, no input, no GC).

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
- 64-bit floats: literals `1.5`, `1_000.25`, `6.02e23`, `1E-9`, `5e3`; no `.5`, `1.`, INF, NAN.
- Operators `+ - * / % ^` and unary `-` on floats, exact comparisons (also chained), truth values, `?:`; bit operators, shifts and `exit` need ints. Int and float mix inside operators (the int is
  converted); assignment, arguments and `return` are strict.
- `print` of floats: 15 significant digits, Python-like layout (`0.1 + 0.2` prints `0.3`, `100.0`, `1e-05`, `inf`, `nan`).
- Float runtime in machine code (print, power, fmod) built from `tools/float_rt.asm`; `tools/fuzz_float.py` checks it in the emulator. Checker: constraints for operators with mixed types.
- Float division/modulo by zero is a runtime error; new runtime error for a negative base with a fractional exponent. 36 new tests (169 total).
- Documented "yet to do": more literals, INF, NAN, comparison tolerance, formatting, explicit conversion.

## Version 4
- Binary literals `2#0001_1011`.
- Compound assignment `+= -= *= /= %= ^= &= |= ~= &&= ||=` and the shift forms.
- Shifts and rotates `<<  >>  +>  <*  *>` (arithmetic left shift = `<<`, no separate operator).
- Constants: names in capitals, defined once at the top level with a constant expression, created at program start. 133 tests.

## Version 3
- `function` keyword with the synonym `\`; one parameter without parentheses; `@x` for variables of the enclosing function (replaced `\x`); `{ ... }` as an ordinary statement; `skip`;
  conditional expression `c ? a ! b`; unary operators bind tighter than `^` (`-2^2` is 4); bit operators between `+` and comparisons; TAB no longer special; 2-space indentation in code and tests;
  `fn` removed; recursive function types allowed; documented that variables start as 0. 107 tests.

## Version 2 - Ka
- Rename Tiny -> Ka (`ka.py`, `.ka`). Language reworked by the user: comments `--`, `--[[ ]]--`, `--[[ --]]`; `elif`; removed `let input and or not global nonlocal`; `&& || !`; globals `^x`;
  strings `'...'` / `"..."` with `^` escapes and joining; `_` in numbers; `#hex`; static types (int, function); bit operators `& | ~`; chained comparisons; `=` as `return`; nested one-line bodies;
  `\x` for enclosing-function variables (draft); max 20 parameters. Compiler, type checker and tests rebuilt (95 tests).

## Version 1 - Tiny
- The first language "Tiny" (`.tiny`): `let`, `input`, `global`, `nonlocal`, `and/or/not`, expression-bodied functions, first-class functions with closures, compiled to a PE `.exe` by `tinyc.py`; 49 tests.
