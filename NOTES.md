# NOTES for Claude (working memory of the Tiny compiler project)

Read this first in every new session, then LANGUAGE.md, then skim `tinyc.py`.
The user cannot be assumed to remember details; this file is the source of truth for *how* and *why*.

## 0. Working agreement with the user
- The user writes the language design, tests on real Windows (`python run_tests.py`) and pastes failures.
  Claude cannot run Windows; Claude checks code with the Unicorn emulator (`tools/emu.py`,
  `python run_tests.py --emu` after `pip install unicorn pefile pefile capstone` as needed).
- Every language change = update `tinyc.py` + `LANGUAGE.md` + tests (+ this file if the design changes).
  Tests are the language definition: expected outputs are derived by hand/by reasoning, not copied blindly.
- Keep the compiler a **single file, pure Python 3, no dependencies**, emitting the PE directly.
- The user thinks in small incremental steps with "huge plans" later. They accept pragmatic limits
  (e.g. `global`/`nonlocal` exist although not originally planned) - ask before big redesigns,
  but do the whole job of a requested feature (parser, analysis, codegen, docs, tests).
- Keep answers short: what changed, notable behaviour/limits, how it was verified.
- End of session: update LANGUAGE.md, NOTES.md, tests; zip; tell the user to download.

## 1. Pipeline (tinyc.py)
`tokenize` -> `Parser` (AST of tuples + `Scope` objects) -> `CodeGen.analyze` (captures) ->
`CodeGen` (x86-64 bytes via `Asm`) -> `build_pe` (PE32+ writer). `compile_source(src)` does it all;
`CompileError` carries messages `line N: ...`.

### Lexer
- Token = `(kind, value, line)`; kinds: `num id kw str op nl indent dedent eof`.
- Emits NEWLINE (`nl`) only when the line is *finished*: suppressed if paren depth > 0 or if the
  previous token is a continuation operator (`CONT_OPS`, `and/or/not`). Duplicated nl are avoided.
- Indentation: one indent stack per open `{` (`stacks`), parens saved/reset per `{` (`paren_saved`).
  INDENT is emitted only if the previous line ended with `:` (`colon_pending`); extra indent otherwise is
  an error. Lines starting with `}` skip indentation processing; `}` emits DEDENTs for blocks still open
  inside that brace. Blank/comment-only lines are skipped. Tab = next multiple of 8.
- Comments are `--`. (`#` and `//` removed on purpose.)

### Parser
- Recursive descent; statements end via `end_stmt()` (accepts `;`, nl, or leaves `}`/dedent/eof/`else`).
- **`closed_at` trick:** a nested body (indented block, or one-line body) may already have consumed the
  line terminator; `end_stmt` then returns immediately when `self.i == self.closed_at`. Needed for
  `x = fn(n):` + indented body, and `xyz = fn(n): a; return a`.
- `block(allman=True)`: brace block / `:`-indented / `:`-one-line (`stmt()` repeated while the previous
  token was `;` and the line is not over / no `else`). Literals call it with `allman=False`.
- `if`: after the then-block, skip newlines and look for `else` (restore position if none).
- Statements starting with an id: `=` -> assignment, otherwise expression statement.
  `fn name` -> definition, `fn (` -> literal expression statement.
- `parse_function`: params, then block or a single expression body (`fn.expr_body`). A final `exprstmt`
  of any function body is rewritten to `return`.
- Scopes: `Scope` per function + the global scope (`parent is None`). `declare()` registers assigned
  names: global scope `slots[name] = index` (data slot); function `slots[name] = rbp offset`
  (params at +24+8*(n-1-i), locals at -8*k). `named_fns` collects `fn name` defs (hoisted).
- Function name vs variable are the **same namespace** (a named fn is a variable holding a closure).
- AST nodes: `("assign",name,expr,line) ("print",items) ("if",c,then,else) ("while",c,body)
  ("break",) ("continue",) ("exit",e) ("return",e|None) ("fn",Scope) ("exprstmt",e) ("pass",)`;
  expressions `("num",n) ("var",name,line) ("call",callee,args,line) ("fnlit",Scope) ("bin",op,l,r)
  ("and"|"or",l,r) ("neg"|"not",e) ("input",)`.

### Analysis (CodeGen.analyze / lookup / capture)
- `lookup(name, scope)` -> `("g",name)` global | `("l",scope,name)` own local | `("f",owner,name)`
  variable of an enclosing function. `global`/`nonlocal` declarations steer it.
- `capture` marks `owner.boxed` and adds `(owner,name)` to `free` of every function between the user
  and the owner (flat closures: each function passes boxes on to the closures it creates).
- Must run over the whole program before any code is generated (`program()` does this).

### Code generation conventions
- Expression result in **rax**. Binary ops: eval left, `push rax`, eval right, `mov rcx,rax`, `pop rax`.
  Only rax/rcx/rdx are used by generated code as scratch; runtime routines clobber
  rcx, rdx, r8-r11, rsi, rax and preserve rbp. No value is ever kept in a register across a call.
- Runtime routines (`rt_print_str`, `rt_print_int`, `rt_read`, `rt_alloc`, `rt_divzero`, `rt_notfn`,
  `rt_badarity`) set up their own aligned frame (`push rbp; mov rbp,rsp; sub rsp,0x30; and rsp,-16`),
  so callers never worry about 16-byte alignment. `exit_process` aligns itself too.
- `Asm.rip(opcode_bytes, symbol)`: instruction whose **last 4 bytes** are the rip-relative disp32
  (do not use for instructions with a trailing immediate). `Asm._ref(label)` + `call/jmp/jcc`
  for rel32 to labels. `lea rax,[rip+label]` is `48 8D 05` + `_ref`.
- **Calling convention (own):** caller pushes args left->right, evaluates the callee value (closure
  pointer) into rax, checks null (`rt_notfn`) and `[rax+8] == nargs` (`rt_badarity`), `push rax`,
  `call [rax]`. Callee: `push rbp; mov rbp,rsp; push 0 * nlocals`, `ret 8*(nparams+1)` pops args and
  closure. Result in rax. Frame: `[rbp+16]` = closure ptr, params above, locals below rbp.
- **Closure object:** `[code address, nparams, box ptr 0, box ptr 1, ...]`. Closures with no free
  variables use one static 16-byte object in `.data` (`clo:<label>`), filled at run time with
  `lea`+`mov` (no absolute addresses anywhere; the image has no relocations and DYNAMIC_BASE is off).
  Others are `rt_alloc`ed (HeapAlloc, zeroed, never freed).
- **Boxed variables:** locals/params captured by nested functions are moved into 8-byte heap boxes
  at function entry (params copied in); their frame slot holds the box pointer. Free variables are
  reached through the closure: `mov rdx,[rbp+16]; mov rdx,[rdx+16+8*i]; mov rax,[rdx]`.
- **Hoisting:** `hoist(scope)` creates closures for all `named_fns` right after box allocation
  (function entry) / after heap init (program start), then the body runs.
- Use-before-assignment is checked textually in codegen (`scope.defined`).
- Globals live at fixed `.data` addresses (`var:<name>`, 8 bytes, zero-initialised).

### PE writer (`build_pe`)
- Sections: `.text` (RX) at 0x1000, `.idata` (RW), `.data` (RW). ImageBase 0x140000000, no relocs,
  console subsystem, 1 MB stack reserve. Imports from kernel32: GetStdHandle, WriteFile, ReadFile,
  ExitProcess, GetProcessHeap, HeapAlloc (list `IMPORTS`; add names there to import more).
- `.data` layout: 0 stdout handle, 8 stdin handle, 0x10 `written`, 0x18 heap handle, 0x20..0x40
  number buffer (end symbol `numbuf_end`), 0x40..0x80 input buffer, then global variables (8 bytes each),
  then static closures (16 each), then string literals (NUL-terminated).
  Strings 0..3 are reserved for the runtime (newline and three error messages).
- Verified with `pefile` (no warnings except the harmless "many 0x00 bytes").

## 2. Decision log (why things are the way they are)
- Direct PE output instead of assembler/linker: no dependencies, user asked for "compiler in Python".
- `--` comments, newline-terminated statements, `;` optional, indentation blocks and braces mixed.
- One-line bodies run to end of line (`if a: b; c` => c inside). User explicitly accepted that this
  cannot express every variant; do not extend it.
- Assignment inside a function always creates a local unless `global`/`nonlocal` (Python rules);
  user accepted this "for now".
- Functions are first-class; named `fn` = hoisted variable. Closures capture variables **by reference**
  via heap boxes (so escaping closures are safe). No GC (leak) accepted.
- Arity and callee checks are at run time (callee is a dynamic value).
- Last bare expression of a function body is returned (any function, not only `{}` literals).
- `input()` is minimal (one `ReadFile` per call, 63 bytes). Known weak spot.

## 3. Known limitations / ideas for later
- Buffered `input()` (several lines from a pipe), string values/variables/concatenation, arrays,
  `for`, GC or arena freeing, integer overflow checks, `INT_MIN / -1`, compile-time arity check when the
  callee is statically known, better error recovery (the compiler stops at the first error),
  `else` on one-line bodies of nested ifs (dangling else binds to the nearest `if`).
- Calling a non-null garbage value (e.g. `5(1)`) crashes with an access violation (not caught).

## 4. Testing
- `python run_tests.py [-k name] [-v] [--emu] [--keep]`; see header of run_tests.py for file conventions
  (`NAME.tiny/.expected/.in/.exit`, `err_NAME.tiny/.error`).
- The emulator fakes kernel32 and asserts 16-byte stack alignment at every API call.
- When adding a feature add tests for: normal use, interaction with blocks/continuation lines,
  error messages, and at least one regression for any bug found.
- `input` tests must use a single `input()` per program (pipe limitation above).

## 5. Session checklist
1. User uploads the zip/folder. Unzip, read NOTES.md, LANGUAGE.md; run `python run_tests.py --emu`.
2. Implement the requested change; run all tests; add/adjust tests and docs.
3. Re-zip (`tiny.zip`) and present it; summarise what to test on Windows.
