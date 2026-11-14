# Ka - a small language compiled to Windows .exe

```
python ka.py program.ka                 # -> program.exe   (pure Python 3, runs on any OS)
python run_tests.py                     # on Windows: compiles and RUNS every test
python run_tests.py -k closure -v       # subset, verbose
python run_tests.py --emu               # Linux/macOS: run tests in an emulator (pip install unicorn pefile)
```

| file | purpose |
|---|---|
| `ka.py` | the compiler (comment stripper, lexer, parser, type checker, x86-64 codegen, PE writer) |
| `LANGUAGE.md` | language reference (for humans and Claude) |
| `NOTES.md` | architecture, conventions, decisions, TODO (mainly for Claude) |
| `tests/` | `.ka` programs + `.expected` output (+ `.exit`, `.warn`); `err_*.ka` + `.error` = must not compile |
| `run_tests.py` | test runner |
| `tools/emu.py` | Unicorn-based `.exe` emulator used for checking without Windows |
| `tools/float_rt.asm`, `tools/build_float_rt.py` | source of the float runtime machine code embedded in `ka.py` (dev only, needs `keystone-engine`) |
| `tools/fuzz_float.py` | fuzz test of the float runtime routines in Unicorn against Python (dev only) |

## Resuming work in a new Claude chat
Upload this folder (or the zip) and write, for example:

> We continue the Ka compiler. Read NOTES.md and LANGUAGE.md first, run the tests
> (`python run_tests.py --emu`), then let's work on: <what you want>.
> At the end update the docs and tests and give me a new zip.

After a change, run `python run_tests.py` on Windows and send Claude the failing output (use `-v`).
