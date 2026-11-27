# Kota - a small language compiled to Windows .exe

```
kota.py program.ko           # -> program.exe
kota.py program.ko -o p.exe  # -> p.exe
kota.py -e program.ko        # compile, run the .exe, delete it (Windows); -e -k keeps the .exe
kota.py -c "print 1+2"       # compile the text, run & delete .exe; -c … -k keeps yyyymmdd_HHMMSS.exe

rt.py                # on Windows: compiles and RUNS every test
rt.py -k closure -v  # subset, verbose
rt.py --emu          # Linux/macOS: run tests in an emulator (pip install unicorn pefile)
```

| file | purpose |
|---|---|
| `kota.py` | the compiler (comment stripper, lexer, parser, type checker, x86-64 codegen, PE writer) |
| `LANGUAGE.md` | the language as its user sees it (short and exact) |
| `IMPLEMENTATION.txt` | the internals worth knowing: decisions, reasons, memory layouts, algorithms, known issues; completes LANGUAGE.md |
| `LIBRARY.txt` | the runtime routines as readable C code (keep in sync with `kota.py` and `tools/*.asm`) |
| `NOTES.md` | how the code works, rules for the files (mainly for Claude) |
| `RELEASE_NOTES.md` | what changed in each version (a list), newest first, with the current state |
| `PLANS.md` | the owner's list of plans |
| `tests/` | the test programs, only `.ko` files; `err_*.ko` must not compile |
| `tests/results/` | what a test must give: `NAME.expected` (stdout), `NAME.exit`, `NAME.warn`, `err_NAME.error` (text of the error) |
| `rt.py` | test runner (run tests) |
| `performance/` | some benchmarks vs Python 3.3; 5x to 16x faster |
| `tools/emu.py` | Unicorn-based `.exe` emulator used for checking without Windows |
| `tools/float_rt.asm`, `tools/time_rt.asm`, `tools/int_rt.asm`, `tools/build_float_rt.py` | source of the float, time and integer runtime machine code embedded in `kota.py`; the script rebuilds it (dev only, needs `keystone-engine`) |
| `tools/test_cli.py` | test of the command line options `-e -k -c` with the emulator in place of Windows (dev only) |
| `tools/fuzz_float.py`, `tools/fuzz_time.py`, `tools/fuzz_prime.py` | fuzz tests of the float, time-format and prime routines in Unicorn against Python (dev only) |
| `tools/annotate_tests.py` | adds `-- =>` result comments to the tests from the real behaviour; `--check` verifies the existing ones (dev only) |

## Resuming work in a new Claude chat
Upload this folder (or the zip) and write, for example:

> We continue the Kota compiler. Read NOTES.md, LANGUAGE.md, IMPLEMENTATION.txt and RELEASE_NOTES.md first,
> then let's work on: \<what you want\>.
> At the end update the docs, run the tests (`python rt.py --emu`), and give me a new zip.

After that, run `python rt.py` on Windows and send Claude the failing output (use `-v`).

