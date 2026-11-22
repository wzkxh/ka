# Ka - a small language compiled to Windows .exe

```
python ka.py program.ka            # -> program.exe
python ka.py program.ka -o p.exe   # -> p.exe

python rt.py                # on Windows: compiles and RUNS every test
python rt.py -k closure -v  # subset, verbose
python rt.py --emu          # Linux/macOS: run tests in an emulator (pip install unicorn pefile)
```

| file | purpose |
|---|---|
| `ka.py` | the compiler (comment stripper, lexer, parser, type checker, x86-64 codegen, PE writer) |
| `LANGUAGE.md` | the language definition (short and exact) |
| `IMPLEMENTATION.txt` | decisions, reasons, alternatives, known issues |
| `NOTES.md` | how the code works, rules for the files (mainly for Claude) |
| `RELEASE_NOTES.md` | versions, newest first, current state |
| `PLANS.md` | the development path (the owner's list) |
| `tests/` | the test programs, only `.ka` files; `err_*.ka` must not compile |
| `tests/results/` | what a test must give: `NAME.expected` (stdout), `NAME.exit`, `NAME.warn`, `err_NAME.error` (text of the error) |
| `rt.py` | test runner (run_tests) |
| `performance/` | some benchmarks vs Python 3.3; 5x to 16x faster |
| `tools/emu.py` | Unicorn-based `.exe` emulator used for checking without Windows |
| `tools/float_rt.asm`, `tools/build_float_rt.py` | source of the float runtime machine code embedded in `ka.py` (dev only, needs `keystone-engine`) |
| `tools/fuzz_float.py` | fuzz test of the float runtime routines in Unicorn against Python (dev only) |
| `tools/annotate_tests.py` | adds `-- =>` result comments to the tests from the real behaviour; `--check` verifies the existing ones (dev only) |

## Resuming work in a new Claude chat
Upload this folder (or the zip) and write, for example:

> We continue the Ka compiler. Read NOTES.md, LANGUAGE.md, IMPLEMENTATION.txt and RELEASE_NOTES.md first,
> then let's work on: \<what you want\>.
> At the end update the docs and run the tests (`python rt.py --emu`) and give me a new zip.

After that, run `python rt.py` on Windows and send Claude the failing output (use `-v`).

