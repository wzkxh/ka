# Kota - release notes (newest first)
What changed in which version; the reasons and details are in IMPLEMENTATION.txt. Old entries are history: they keep the names of their time (`ka.py`, `.ka`, old test numbers).

## Current state (version 7.4)
- Kota compiles to a Windows x64 console `.exe` (PE written directly, pure Python 3, no dependencies). The version is the `VERSION` constant in `kota.py`.
- Language: 64-bit ints and floats, byte strings (`str`) and unicode strings (`text`), first-class functions and closures, static type inference, constants, `assert`, time, random numbers. Definition: LANGUAGE.md.
- Tests: 253 programs in `tests/`, expected results in `tests/results/`. All pass on real Windows (the user's run of 7.4). Under the emulator on Linux all pass except `78_primes` (it needs more instructions than the emulator's limit).
- Known limits: IMPLEMENTATION.txt section 16.

## Version 7.4
- Unary `*n`: the prime test (1 or 0, ints only).
- Tests: `77_prime`, `78_primes`, `err_type_prime_float`, `err_type_prime_text`; tools `tools/int_rt.asm`, `tools/fuzz_prime.py`.
- Test numbers 63..75 renumbered (65..77), no duplicates.
- Documents reorganised: LANGUAGE.md only for the language user, IMPLEMENTATION.txt sections renumbered 1-16 and holding all decisions, LIBRARY.txt completed (strings, time, prime test, memory errors), NOTES.md and this file shortened.

## Version 7.3
- Unary `|x`: absolute value of an int or float, length of a `str` (bytes) or a `text` (characters).
- Tests: `err_type_arg_*` (one function called with arguments of different types), `73_oop_counter`, `74_abs_length`, `err_type_abs_function`.

## Version 7.2
- `assert condition[, report]`; compiler constant `CHECK_ASSERTS`; `assert` is a keyword.
- Tests: `72_assert`, `rt_assert_*`, `err_type_assert_function`.

## Version 7.1
- Command line: `-e` (compile, run, delete the .exe), `-k` (keep .exe), `-c "text"` (compile source text from the command line, run & delete .exe).
- Dev test `tools/test_cli.py`.

## Version 7.0
- The language is renamed Ka -> Kota: files `.ko`, compiler `kota.py`, module `kota`; docs, sources, tools, tests and benchmarks renamed. Nothing else changed.

## Version 6.9
- `?1` is the time in microseconds since 1970 (UTC); it was a runtime error in earlier versions.
- `?'format'` and `?"format"`: the local time as a `str` / `text` (codes `y2 y4 m1 m2 d1 d2 H1 H2 M1 M2 S1 S2 F1 F2 F3 w1 w2 w3`).
- So `?` accepts strings; `?x` has the type of `x`.
- Tests: `71_time`; `rt_rand_one` removed. New: `tools/time_rt.asm`, `tools/fuzz_time.py`; the build script handles several asm files.

## Version 6.8.1
- Printing a `text` uses a buffer (one `WriteFile` per buffer, not per character). Test `70_long_text_print`.

## Version 6.8
- Strings are values: `str` (`'...'`) and `text` (`"..."`): assignment, parameters, results, closures, constants, `print`, `+` / `+=`, comparisons (also chained); the empty string is false in conditions.
- `rt_alloc` checks `HeapAlloc`: runtime error `out of memory`.
- `print 'a' + x` works (a print item can be any expression).
- Strings by Gemini on top of 6.3, merged into 6.4. Tests: Gemini's `63`-`68` and its string `err_*`, `69_string_truth_and_more`; `err_string_value` removed.

## Version 6.4
- A variable must be assigned before it is read: a compile error when certainly wrong, a runtime error `variable 'x' is not initialized` in the unclear cases. Variables do not start as 0.
- Constants (upper-case letters) are variables assigned once where written (any expression); named functions are constants.
- `!` ends a one-line function body inside `c ? a ! b`.
- `?1`, `?0.0`, negative floats and NaN are runtime errors. The "value not used" warning is off by default.
- New `LIBRARY.txt` (the runtime as C). Tests: 13 more.

## Version 6.3
- Random numbers: unary `?x`. Tests `62_random`, `err_const_random`, `err_type_random_function`.

## Version 6.2.1 (no change to the compiler)
- `tests/` holds only the programs; expected results are in `tests/results/`.
- `tools/annotate_tests.py --check` verifies the `-- =>` comments.
- `performance/cs.ka` fixed (`n \ 2`).

## Version 6.2
- Floored division and modulo: `a \ b` is floor(a / b), `a % b` has the sign of `b` (incompatible for negative operands).
- Fixed: float `\` was off by one in rare cases.
- `# ` comments and `0x` literals documented as compatibility forms. `--version` removed.

## Version 6.1
- Hex literals `0xFF`; comments `# text`; clearer error messages for ill-formed numbers. Tests: 10 more.

## Version 6
- `/` is always float division; `\` is integer division (incompatible: old int divisions must use `\`); `\=` added.
- A negative shift count shifts the other way.
- Constants may be defined inside function bodies.
- `\` is no longer a statement boundary.
- All tests got `-- =>` comments; `tools/annotate_tests.py`; docs split into LANGUAGE, IMPLEMENTATION, NOTES, RELEASE_NOTES, README.

## Version 5 - floats
- 64-bit floats: literals, `+ - * / % ^`, comparisons, truth values, `?:`, mixing with ints inside operators, `print` with 15 significant digits.
- Float runtime in machine code (`tools/float_rt.asm`, `tools/fuzz_float.py`). Runtime errors for float division by zero and negative base with a fractional exponent. Tests: 169.

## Version 4
- Binary literals `2#0001_1011`; compound assignments; shifts and rotates `<< >> +> <* *>`; constants (capital names, top level). Tests: 133.

## Version 3
- `function` keyword and synonym `\`; one parameter without parentheses; `@x`; `{ ... }` as a statement; `skip`; conditional `c ? a ! b`; unary operators tighter than `^`; bit operators between `+` and comparisons;
  2-space indentation. Tests: 107.

## Version 2 - Ka
- Renamed Tiny -> Ka (`ka.py`, `.ka`); the language reworked by the user (comments `--`, `elif`, `&& || !`, globals `^x`, string literals with `^` escapes, `_` in numbers, `#hex`, static types, bit operators,
  chained comparisons, `=` as `return`). Tests: 95.

## Version 1 - Tiny
- The first language "Tiny" (`.tiny`), compiled to a PE `.exe` by `tinyc.py`; closures. Tests: 49.
