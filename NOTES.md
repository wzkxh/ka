# NOTES for Claude (working notes on the Ka compiler)

Read this first in every new session, then LANGUAGE.md (the language), then skim `ka.py`.
Reasons behind decisions: IMPLEMENTATION.txt. History and state: RELEASE_NOTES.md. Plans of the owner: PLANS.md; the next tasks are given in the chat.
(The language was called "Tiny" with extension `.tiny` until version 2, when it became Ka / `.ka`.)

## 0. Working agreement and rules for the files
- The user designs the language, runs `python rt.py` on real Windows and pastes failures. Claude cannot run Windows; Claude checks code with the
  Unicorn emulator (`tools/emu.py`; `pip install unicorn pefile`, `python rt.py --emu`). Keystone (`pip install keystone-engine`) is only needed to rebuild the float runtime.
- The compiler stays a single file, pure Python 3, no dependencies, emitting the PE itself.
- Every language change = `ka.py` + `LANGUAGE.md` + tests, and a line in `RELEASE_NOTES.md`; decisions and their reasons go to `IMPLEMENTATION.txt`.
- **Document split:** LANGUAGE.md = short exact definition, no "why". IMPLEMENTATION.txt = decisions, reasons, alternatives, issues. NOTES.md = this file, how the
  code works. RELEASE_NOTES.md = versions, newest first, with the current state. PLANS.md = the owner's list of plans and ideas (the user maintains it; the next tasks come in the chat).
  README.md = what the files are and how to run.
- **Version:** the `VERSION` constant in `ka.py` (no command line option for it, the user asked for none). Bump it for every delivery to the user and add an entry on top of RELEASE_NOTES.md.
- **Style:** 2 spaces per indentation level in `.py` and `.ka` files (also continuation lines). Tests carry `-- =>` comments with the result of a statement
- **Brackets (user, 6.3):** blanks between arguments -> blanks also after `(` and before `)`: `f( first, second )`; short cases (a few arguments, short names) -> no blanks: `f(a,b)`, `fn(T1,T2)->R`.
  Same for `[]`. Use it in new code and docs; fix old code only when it is free.
  (`python tools/annotate_tests.py [names] [--whole-output]` adds them from the real behaviour, `--check` verifies that the existing ones still tell the truth: run it after a change of behaviour; read the result critically) and `-- ERROR: ...` at the failing line of `err_*` tests.
- Expected outputs are derived by hand or by an independent reference (Python), not copied from the compiler: a wrong expectation was found several times.
- The user thinks in small steps, wants "as simple as you can", accepts pragmatic limits and says what may be skipped. Ask before big redesigns; do the whole job of a
  requested feature (parser, checker, codegen, docs, tests). Keep answers short: what changed, notable behaviour/limits, open questions, how it was verified.
- End of a session: update docs and tests, bump version, zip (`ka.zip`, not 7z), present it.

## 1. Pipeline (ka.py)
`strip_comments` -> `tokenize` -> `Parser` (AST of tuples + `Scope` objects) -> `Checker` (static types) -> `InitCheck` (assigned before use) -> `CodeGen.analyze` (captures) -> `CodeGen` (x86-64 bytes via `Asm`)
-> `build_pe` (PE32+ writer). `compile_source(src, warnings=None)` does it all; `CompileError` carries messages `line N: ...`; warnings are collected, never fatal.

### Source preparation and lexer
- No TAB check: the lexer simply has no rule for it (error outside strings/comments).
- `strip_comments` replaces comments by spaces (newlines kept; line numbers and columns survive). It is string-aware. `--[[ ... ]]--` if the closer is on the same line
  (and before any `--]]`), else `--[[ ... --]]` blanked to the end of the closing line. Unclosed -> error. `# ` (hash + space, or hash at the end of a line, not right after a digit) comments to the end of the line;
  the scan loop for plain text stops at `#` as well as at quotes and `-`.
- Token = `(kind, value, line)`; kinds `num hex flt id kw str op nl indent dedent eof`. `hex` tokens (also binary literals) carry the value wrapped to signed 64 bit; `flt` carries a
  Python float; `str` carries `(bytes, 'b'|'u')`. Strings are scanned by hand (`lex_string`). Numbers: `flt` regex first (`digits[.digits][e..]`), else `\d\w*(?:#\w*)?` is taken whole and validated: binary `2#...`, hex `0x...` (same `hex` token as `#ff`), decimal; the error message depends on the shape.
- `nl` is emitted only when the line is finished: not while paren depth > 0, not after a continuation operator (`CONT_OPS`: operators, `op=` forms, `\`, `,`, `?`, `!`).
- Indentation: spaces only; one indent stack per open `{`; INDENT only if the previous line ended with `:`; a line starting with `}` skips indentation processing.
- Operators are matched longest first (3-char forms, then 2-char, then single). `^ \ @ ?` are plain `op` tokens; the parser decides (`^`: power vs. global prefix; `\`: function
  start vs. integer division; `@`: enclosing-function variable; `?`: conditional).

### Parser
- Recursive descent. `end_stmt()` accepts `;`, nl, a closing `)`/`,` (only when the innermost open bracket is `(`, tracked in `self.ctx`), `}`, `{`, eof/dedent, `else`/`elif`, or a
  statement keyword (`STMT_KW`, `function`). `\` is NOT a statement boundary any more (it is a binary operator after an operand).
- `closed_at`: a nested body may already have consumed the line end; `end_stmt` returns at once when `self.i == self.closed_at`.
- `!` ends a one-line body when the innermost open construct is the middle part of `c ? a ! b`: `cond()` pushes `?` on `ctx` around the middle expression, `end_stmt()` and `at_end()` accept `!` when `?` is on top.
- `block(allman=True)`: brace block / `:`-indented / `:`-one-line (`stmt()` repeated while `body_continues()`). `{...}` is a statement (`("block", stmts)`). `block()` counts `self.nblock`.
- `if_stmt`: after the then-block skip newlines and look for `elif`/`else` (restore if none): dangling else binds to the nearest `if`.
- `=` at statement start is `return`. `skip` is the empty statement. Compound assignment: `assign()` takes `=` or an `op=` and desugars `x op= e` to `x = x op e` (`&&=`/`||=` -> and/or nodes).
- Functions: `function`/`\` + `name (` or `name param` = definition (`fn_def`, two tokens of lookahead in `stmt()`), else a literal. Parameters `(a, b)` or one bare name (`parse_function`).
  `parse_function` saves and resets `self.nblock` (a function body starts counting again).
- Expression levels low to high: `cond` `or_` `and_` `eq` `cmp` `bor` `bxor` `band` `shift` `add` `mul` (`* / % \`) `power` `unary` `postfix`. `chain()` builds `("cmp", ops, operands)` for 2+
  comparisons of one level. `power()` = `unary ['^' power]`; `-5`/`-1.5` are folded into literals.
- Print items: `string_item()` collects adjacent literals or a parenthesised group of them; if more follows (`'a' + 'b'`) the parser goes back and parses an expression. A string literal elsewhere is a value:
  `("bstr", i)` / `("btext", i)` indexing `Parser.byte_strings` (bytes) / `Parser.text_strings` (lists of code points); adjacent literals are joined in `primary`.
- AST (line last): statements `("assign",name,expr,line,mode[,True])` (6th element = constant definition) `("print",items,line) ("if",c,then,else,line) ("while",c,body,line) ("exit",e,line)
  ("exprstmt",e,line) ("return",e|None,line) ("fn",Scope) ("block",stmts) ("skip",) ("break",) ("continue",)`; expressions `("num",n) ("flt",x) ("var",name,line,mode) ("call",callee,args,line)
  ("fnlit",Scope) ("bin",op,l,r) ("cmp",ops,xs) ("cond",c,a,b) ("and"|"or",l,r) ("neg"|"not"|"bnot",e)`. `mode`: None, `^` (global), `@` (enclosing function).
- Scopes: `Scope` per function plus the global scope (`parent is None`). `declare(name, mode, line)` registers assigned names; `globals_decl` / `nonlocal_decl` record names used as `^x` / `@x`
  (a name cannot be both local and marked). `^x` in a function also creates the global slot and adds it to `fn_globals`.
- **Constants:** `is_const_name` (capitals/digits/`_`, one capital). `assign()` calls `define_const()`: allowed when `self.nblock == 0` at program level or `== 1` in a function body (the body is one block),
  once per scope (`Scope.consts`: name -> line), never as `^X`/`@X` in a function. The value is any expression and the assignment runs in place (the 6th element of the assign node only marks the definition).
  Parameters with constant-like names are rejected in `parse_function`.
- No warnings by default: `WARN_UNUSED_VALUE` (module constant, False) switches the "expression statement that is not a call" warning on; options and pragmas will control it later.

### Name resolution (`Resolver.lookup`)
Shared by Checker and CodeGen. `lookup(name, scope, line, mode)` -> `("g",name)` | `("l",scope,name)` | `("f",owner,name)`. `^` -> global; `@` -> nearest enclosing function owning the name;
plain names follow `globals_decl` / `nonlocal_decl`, then local, then enclosing functions, then globals.

### Type checker (`Checker`)
- Monomorphic unification. `Ty` kinds `int`, `float`, `str`, `text`, `fn(params, ret)`, `var`. Variables keyed `("g",name)` or `(scope,name)`; every function has a type with a fresh variable per parameter and result (`fn_ty`);
  bodies are checked once (`check_body`). No occurs check; `unify_raw` skips pairs already being compared; `show()` cuts cycles.
- Operators whose result type depends on operand types that may be unknown yet (`+ - * % ^`, `== !=`, `?:`) are constraints (`arith`, `eq`, `order`, `cond`, `num` in `Checker.pending`), settled by `step()` /
  `solve()`; `finish()` makes what is still unknown int. `/` (float result) and `\` (int result) only need numeric operands (`need_num`; `need_num(..., True)` also accepts `str`/`text`: truth values and `print`). `+` on strings is in `arith`, string comparisons in `eq`/`order` (both sides the same string type, `same_string`). Assignments, arguments, returns use plain `unify` (strict).
- `Checker.types` maps `id(expression node)` to its `Ty` (the AST must stay alive; `compile_source` keeps it). Bare `return` / falling off the end are not unified.

### Assignment before use (`InitCheck`) and function names
- `InitCheck` (after the Checker, before the code generator) is the definite-assignment analysis described in IMPLEMENTATION.txt section 12: phase 1 collects the scopes and `ext` (keys assigned from another scope),
  phase 2 walks every scope in execution order with `InitState(must, may)` (None = unreachable) and records call sites and exits; reads of variables of other scopes are decided at the end (`deferred`).
  Results: `check_reads` (ids of var nodes whose read must check the flag) and `flagged` (keys of the variables that need a flag). A read that is certainly wrong is a compile error with the old messages.
  Keys are `("g", name)` for globals and `(scope, name)` otherwise, as in `Checker.key`.
- A name defined with `function` cannot be assigned: `Checker.stmt` (assign) looks up the scope of the target and rejects names in its `named_fns`.

### Code generation
- Values are 64-bit words; a float is a double's bit pattern. Expression result in **rax**. Binary ops: eval left, `push rax`, eval right, `mov rcx,rax`, `pop rax`. Generated code uses only rax/rcx/rdx as
  scratch (xmm0-xmm2 for floats); runtime routines may clobber rcx, rdx, r8-r11, rsi, rdi, rbx, r12-r15, rax, xmm0-xmm3 and preserve rbp/rsp. No value stays in a register across a call.
- `CodeGen.tk(e)` gives the type of a node (`int`/`float`/`fn`; unknown = int). Float arithmetic: `load_xmm` (movq for floats, cvtsi2sd for ints), `addsd` ... ; `/` and `%` and `\` check the divisor bits
  (`shl 1` ignores the sign) and jump to `rt_divzero`. `fcmp_false(op, label)` compares with `ucomisd` (nan-correct); `test_rax(kind)` is the truth test (floats: `shl rcx,1`).
  Int `\` and `%` are floored: `cqo; idiv`, then if the remainder is not 0 and its sign differs from the divisor's (`xor` of the two, `jns`), `dec rax` (for `\`) or `add rdx,rcx` (for `%`).
  Float `%`: `call rt_fmodfloor` (in `runtime()`: calls `rt_fmod`, then adds `y` if the remainder is not 0 and its sign differs from `y`'s; a zero becomes +0.0; returns the plain fmod in xmm4 and a 0/1
  flag in edx). Float `\`: `movapd xmm2,xmm0; call rt_fmodfloor; subsd xmm2,xmm4; divsd xmm2,xmm1; cvtsd2si rax,xmm2; sub rax,rdx`. The division result is only nearly an integer (`a - fmod` can be rounded:
  13276.999999999998), so it is rounded to nearest (`cvtsd2si`), not truncated.
- Shifts: count `< 0` -> negate and use the opposite shift; `> 63` (unsigned compare) -> 0 (`+>`: sign fill; negative: 0); rotates: `rol/ror rax,cl` (count modulo 64 by the hardware).
- Chained comparison: the previous operand lives at `[rsp]`; each link jumps to a fail label (`FAIL_CC`, or `fcmp_false` for floats). Int power: square-and-multiply loop inline.
- Runtime routines (`rt_print_str`, `rt_print_int`, `rt_print_float`, `rt_alloc`, `rt_divzero`, `rt_notfn`, `rt_negexp`, `rt_badpow`) set up their own aligned frame; `exit_process` aligns too.
- `Asm.rip(opcode_bytes, symbol)`: instruction whose last 4 bytes are the rip-relative disp32. `call/jmp/jcc` take labels (rel32). `lea rax,[rip+label]` = `48 8D 05` + `_ref`.
- **Calling convention (own):** caller pushes arguments left to right, evaluates the callee (closure pointer) into rax, null check (`rt_notfn`), `push rax`, `call [rax]`. Callee: `push rbp; mov rbp,rsp;
  push 0 * nlocals`, `ret 8*(nparams+1)`. Frame: `[rbp+16]` closure pointer, params above, locals below.
- **Closure object:** `[code address, nparams (unused), box ptr 0, ...]`. Closures without free variables share one static 16-byte object in `.data`; others are `rt_alloc`ed.
  Locals/params captured by nested functions live in 8-byte heap boxes (`analyze` finds them); free variables are reached through the closure.
- **Scope entry:** `hoist(scope)` creates the closures of all `named_fns`. Constants and variables are assigned where their statements are. `alloc_flags()` gives every variable in `InitCheck.flagged` a hidden flag
  (a data slot for a global, a frame slot for a local, the second quadword of its 16-byte box for a captured variable); `var_store` sets it, `var_load(check=True)` tests it and jumps to a per-name stub
  (`stub_label`, `emit_uninit_stubs`) that prints `runtime error: variable 'x' is not initialized`. `CHECK_INIT = False` removes the flags.
- Random numbers: `("rand", e)` -> `rt_rand_int` / `rt_rand_float` (operand in rax; `rt_next_u64` is SplitMix64 on the 8 bytes at `state`; a float that is not above 0.0 and NaN end in `rt_badrand`; `?1` jumps to `rt_time_us`; a str/text operand calls `rt_time_str`/`rt_time_text`, see Time below); written in `runtime()` with the compact bracket style.
- Program start: GetStdHandle(stdout), `SetConsoleOutputCP(65001)`, GetProcessHeap.
- **Float runtime** (`FLOAT_RT` between the BEGIN/END markers in ka.py): machine code generated from `tools/float_rt.asm` by `tools/build_float_rt.py` (Keystone assembles single instructions; the script does labels
  and rel32 jumps). `rt_fmt_float` (rax = bits, rdx = buffer -> rax = length), `rt_fpow` (xmm0, xmm1 -> xmm0, edx = error code), `rt_fmod` (exact integer algorithm). They set the x87 control word themselves.
  `rt_print_float` (in `runtime()`) calls `rt_fmt_float` and `rt_print_str`. Edit the .asm, run `python tools/build_float_rt.py` (rewrites ka.py between the markers), then `python tools/fuzz_float.py`.

### PE writer (`build_pe`)
- Sections `.text` (RX) at 0x1000, `.idata` (RW), `.data` (RW). ImageBase 0x140000000, no relocs, console subsystem, 1 MB stack. kernel32 imports (`IMPORTS`): GetStdHandle, WriteFile, SetConsoleOutputCP,
  ExitProcess, GetProcessHeap, HeapAlloc.
- `.data`: 0 stdout handle, 8 unused, 0x10 `written`, 0x18 heap handle, 0x20..0x40 number buffer, 0x40 random generator state (the initial value is written by `build_pe`), 0x48..0x80 unused, then globals (8 bytes each), static closures (16 each), then the print/error strings (lengths are explicit; NUL
  inside strings is fine). String objects of the program (`bstr:i`, `btext:i`, 8-aligned, `[u64 length][bytes or u32s]`) follow them; the empty string has no object. Strings 0..6 are reserved for the runtime (newline, division by zero, unset function, negative exponent, bad power, bad `?` argument, out of memory); the "not initialized" messages are appended by the code generator.

## 2. Testing and tools
- `python rt.py [-k name] [-v] [--emu] [--keep]`; the programs are `tests/NAME.ka`, what they must give is in `tests/results/` (`NAME.expected/.exit/.warn`, `err_NAME.error`); see the header of rt.py. Output is compared as raw bytes.
- The emulator fakes kernel32 and asserts 16-byte stack alignment at every API call. It starts with a 64-bit x87 precision (real Windows: 53); QEMU's x87 transcendental functions are only ~4e-15 accurate.
- When adding a feature add tests for normal use, interaction with blocks/continuation lines, error messages, and a regression for every bug found. Write `-- =>` comments (or run tools/annotate_tests.py).
- **Time runtime** (`TIME_RT` between its markers in ka.py): `rt_utf8_to_text`, `rt_text_to_utf8`, `rt_time_format` from `tools/time_rt.asm` (same build script, `python tools/build_float_rt.py` does both files);
  `rt_time_us`, `rt_time_text`, `rt_time_str` (Windows calls, allocation) are in `runtime()`. `python tools/fuzz_time.py` checks the formatting at fixed times; `emu.run_pe(..., now=datetime, unix_us=n)` fixes the clock.
- `tools/fuzz_float.py [count]` checks the float routines; `tools/annotate_tests.py` adds result comments; `tools/build_float_rt.py` rebuilds the float runtime.

## 3. Session checklist
1. The user uploads the zip/folder. Unzip; read NOTES.md, RELEASE_NOTES.md, LANGUAGE.md, PLANS.md; `pip install unicorn pefile keystone-engine`; run `python rt.py --emu`.
2. Implement the requested changes; run all tests; add/adjust tests (with comments) and docs (see 0); bump `VERSION`.
3. Re-zip (`ka.zip`), present it, summarise what to check on Windows and any open question.
