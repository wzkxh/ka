# NOTES for Claude (working memory of the Ka compiler project)

Read this first in every new session, then LANGUAGE.md, then skim `ka.py`.
The user cannot be assumed to remember details; this file is the source of truth for *how* and *why*.
(The language was called "Tiny" with extension `.tiny` until the rename to Ka / `.ka`.)
**Code style (user decision): 2 spaces per indentation level in `.py` and `.ka` files.**

## 0. Working agreement with the user
- The user writes the language design, tests on real Windows (`python run_tests.py`) and pastes failures.
  Claude cannot run Windows; Claude checks code with the Unicorn emulator (`tools/emu.py`,
  `python run_tests.py --emu` after `pip install unicorn pefile`).
- Every language change = update `ka.py` + `LANGUAGE.md` + tests (+ this file if the design changes).
  Tests are the language definition: expected outputs are derived by hand/by reasoning, not copied blindly
  (a wrong hand-computed expectation was found twice this way: always re-check which side is wrong).
- Keep the compiler a **single file, pure Python 3, no dependencies**, emitting the PE directly.
- The user thinks in small incremental steps, wants "as simple as you can", accepts pragmatic limits and says
  explicitly what may be skipped ("it is not that Microsoft will adopt this language instead of C++").
  Ask before big redesigns, but do the whole job of a requested feature (parser, analysis, codegen, docs, tests).
- Keep answers short: what changed, notable behaviour/limits, open questions, how it was verified.
- End of session: update LANGUAGE.md, NOTES.md, tests; zip; tell the user to download.

## 1. Pipeline (ka.py)
`strip_comments` -> `tokenize` -> `Parser` (AST of tuples + `Scope` objects) ->
`Checker` (static types) -> `CodeGen.analyze` (captures) -> `CodeGen` (x86-64 bytes via `Asm`) ->
`build_pe` (PE32+ writer). `compile_source(src, warnings=None)` does it all; `CompileError` carries
messages `line N: ...`; warnings (list of strings) are only collected, never fatal.

### Source preparation
- No TAB check (user decision): TAB is a character like ESC or `$`: plain text inside strings/comments, an
  `unexpected character` error elsewhere (the lexer simply has no rule for it).
- `strip_comments` runs before the lexer and replaces comments by spaces (newlines kept, so line numbers and
  columns survive). It is string-aware (`"..."`, `'...'`, `^` escapes). Forms: `--` line; `--[[ ... ]]--` if the
  closer is on the same line (and before any `--]]`); otherwise `--[[ ... --]]` multi-line, blanked up to the
  end of the closing line (rest of that line is ignored). Unclosed -> error.

### Lexer
- Token = `(kind, value, line)`; kinds: `num hex id kw str op nl indent dedent eof`. `hex` tokens carry the
  value already wrapped to signed 64 bit; `str` tokens carry `(bytes, 'b'|'u')`.
- Strings are scanned by hand (`lex_string`), not by regex. Escapes: `^n ^t ^r ^^ ^" ^'`, `^XX` (byte in `'..'`,
  code point U+00XX in `".."`), `^uXXXX`, `^UXXXXXX`. Both string kinds are stored as UTF-8 bytes for now
  (the user plans: `'..'` bytes, `".."` array of 32-bit code points later; print must then encode).
- Numbers: `\d\w*` is taken whole and validated (`\d+(_\d+)*`), so `1_`, `1__0`, `12ab` are one clear error.
  Hex: `#\w*` validated against `#hex(_hex)*`; `#'...'` is reserved (currently "bad hex literal").
- Emits NEWLINE (`nl`) only when the line is *finished*: suppressed if paren depth > 0 or if the previous
  token is a continuation operator (`CONT_OPS`: `+ - * / % == != < <= > >= && || ! = , & | ~ ^ ?`).
- Indentation: spaces only. One indent stack per open `{` (`stacks`), parens saved/reset per `{`.
  INDENT only if the previous line ended with `:` (`colon_pending`). Lines starting with `}` skip indentation
  processing; `}` emits DEDENTs for blocks still open inside that brace.
- `^ \ @ ?` are plain `op` tokens; the parser decides (`^`: power vs. global prefix; `\`: `function` synonym; `@`: prefix of
  an enclosing function's variable; `?`: conditional). Keywords: `if elif else while break continue print exit function return skip`.

### Parser
- Recursive descent. `end_stmt()` accepts `;`, nl, a closing `)`/`,` (only when the innermost open bracket is `(`,
  tracked in `self.ctx`), `}`, `{`, `\`, eof/dedent, `else/elif`, or a statement keyword (`STMT_KW` and `function`) -
  that is the "`;` optional where clear" rule.
- **`closed_at` trick:** a nested body (indented block, or one-line body) may already have consumed the line
  terminator; `end_stmt` then returns immediately when `self.i == self.closed_at`.
- `block(allman=True)`: brace block / `:`-indented / `:`-one-line. A `{...}` after `:` is NOT special: it is a
  statement (`("block", stmts)`, see `stmt()`) that happens to be the first one of a one-line body. A one-line body is
  `stmt()` repeated while `body_continues()` (previous token was not nl/dedent and either a statement keyword or
  something that is not an end follows). Nested one-line bodies fall out of the recursion.
- `if_stmt`: after the then-block skip newlines and look for `elif` / `else` (restore position if none). This is
  what makes dangling else bind to the nearest `if` that has no else yet, also across lines.
- `=` at statement start is a `return` (needs an expression); `return` may be bare. `skip` is the empty statement.
- Functions: `function`/`\` followed by `name (` or `name param` is a definition (`fn_def`, lookahead of two tokens
  in `stmt()`); anything else (`function (`, `function x:`) is a literal used as a statement. Parameters: `(a, b)` or one bare
  name (`parse_function`).
- Expression levels (low to high): `cond` (`c ? a ! b`, right assoc) `or_ and_ eq cmp bor bxor band add mul power unary postfix`.
  Bit operators sit between `+` and the comparisons (Python-like, NOT C-like; user said "like in C, I guess" - the order
  `& > ~ > |` is C's, the position relative to `==` is a deliberate deviation: tell the user if it matters).
  `chain()` builds `("cmp", ops, operands)` for 2+ comparisons on the same level, a plain `("bin",..)`
  for one. `power()` = `unary ['^' power]` gives right associativity; unary operators bind tighter than `^`
  (`-2^2 = (-2)^2`, user decision), so `-5` is always folded into a literal.
- Print items: `string_item()` collects adjacent string tokens, or a parenthesised group of them (so newlines
  inside parentheses concatenate). Mixed `'`/`"` -> error. Strings elsewhere -> error.
- Scopes: `Scope` per function + the global scope (`parent is None`). `declare(name, mode, line)` registers
  assigned names (`mode`: None / `^` / `\`). Function-level sets `globals_decl` / `nonlocal_decl` record names used
  as `^x` / `@x`; a name may not be both local and marked in one function (decision: no shadowed globals).
  `^x` in a function also creates the global slot and adds it to `fn_globals` (so top-level reads before the
  assignment are allowed).
- AST (line last): `("assign",name,expr,line,mode) ("print",items,line) ("if",c,then,else,line)
  ("while",c,body,line) ("exit",e,line) ("exprstmt",e,line) ("return",e|None,line) ("fn",Scope) ("break",)
  ("continue",)`; expressions `("num",n) ("var",name,line,mode) ("call",callee,args,line) ("fnlit",Scope)
  ("bin",op,l,r) ("cmp",ops,xs) ("cond",c,a,b) ("and"|"or",l,r) ("neg"|"not"|"bnot",e)`;
  statements also `("block",stmts)` and `("skip",)`.
- Warning: expression statements that are not calls ("the value of this expression is not used").

### Compound assignment, shifts, binary literals, constants
- Lexer: `num` regex is `\d\w*(?:#\w*)?`; a `#` inside means a binary literal `2#0001_1011` (base 2 only, wrapped to signed
  like hex, emitted as a `hex` token). Operators are matched longest first: 3-char forms (`&&= ||= <<= >>= +>= <*= *>=`), then
  2-char (`<< >> +> <* *> += -= *= /= %= ^= &= |= ~=` plus the old ones). `COMPOUND` maps `op=` to `op`; both it and `SHIFT_OPS`
  are in `CONT_OPS` (a line ending with them continues).
- Parser: `assign()` takes `=` or a compound operator and desugars `x op= e` to `x = x op e` (`&&=`/`||=` become `and`/`or`
  nodes, so they short-circuit); targets may be `name`, `^name`, `@name`. Shifts are one left-associative level (`shift()`)
  between `band` and `add`.
- Codegen: `<< >> +>` compare the count with 63 (unsigned `ja`) and give 0 / sign fill beyond that (this also covers negative
  counts); `<* *>` are plain `rol/ror rax,cl` (hardware takes the count modulo 64, so negative counts rotate the other way).
- **Constants** (name matches `[A-Z0-9_]*[A-Z][A-Z0-9_]*`, see `is_const_name`): `assign()` / `fn_def()` call `define_const()`
  (only at top level with `self.nblock == 0`, only once - `self.consts` maps name to line), `const_problem()` checks the initializer
  (numbers, earlier constants, operators, `?:`, function literals; no variables or calls), and the assign node gets a 6th element
  `True`. `parse_function` rejects constant-looking parameter names. In `CodeGen.program()` all such assignments are emitted right
  after `hoist(g)` (before the other statements) and skipped at their textual place, so constants can be read anywhere, even above
  their definition. `nblock` is incremented in `block()` and `brace_block()` (any `if`/`while`/`{}`/function body).

### Floats (iteration 5)
- Value representation: every value is still one 64-bit word; a float is the bit pattern of a double (`mov rax, imm64` for literals).
  Variables, arguments, results and closures need no change. Only operators and `print` care about the type.
- Lexer: `flt` token (`digits[.digits][e[+-]digits]` with `_` inside digit groups, Python `float()` for the value, `inf` -> error);
  `1.`, `.5`, `1.5abc`, `1.5.2` give specific errors. Parser: `("flt", x)` nodes, `-1.5` is folded like `-5`.
- **Type checker** (`Checker`): types are `int`, `float`, `fn`, `var`. Operators that mix int and float cannot be typed by plain unification
  (an operand may be a parameter whose type is only fixed by a later call), so `+ - * / % ^`, `== !=` and `?:` are recorded as
  constraints (`arith`, `eq`, `cond`, `num` in `Checker.pending`) and settled by `step()`/`solve()` when their operand types are known
  (`arith`: float if either side is float, int if both are int). `finish()` makes whatever is still unknown int, then solves again.
  Assignments, arguments and returns stay strict (plain unify), by design: no implicit int->float outside operators.
  `Checker.types` maps `id(expression node)` to its Ty; the AST must stay alive (it does, compile_source keeps it).
- **CodeGen** reads those types (`tk(e)`: int/float/fn; unknown counts as int). Float arithmetic: operands are put in xmm0/xmm1
  (`load_xmm`: `movq` for a float, `cvtsi2sd` for an int), then `addsd/subsd/mulsd/divsd`; `/` and `%` check the divisor bits
  (`shl 1` ignores the sign) and jump to `rt_divzero`. Comparisons use `ucomisd` through `fcmp_false(op, label)` (nan-correct:
  false for everything except `!=`); chains convert per link. Truth tests use `test_rax(kind)` (floats: `shl rcx,1` so -0.0 is false).
  Unary minus on a float flips the sign bit (`btc rax,63`). `?:` converts an int branch when the result is float.
- **Runtime blobs** (`FLOAT_RT` in ka.py between BEGIN/END markers) are machine code generated from `tools/float_rt.asm` by
  `tools/build_float_rt.py` (needs `pip install keystone-engine`; Keystone assembles single instructions, the script does labels and
  rel32 jumps itself because Keystone hung on larger label-heavy input). Routines: `rt_fmt_float` (rax = bits, rdx = buffer -> rax = length;
  15 significant digits via x87 extended precision: N = round(x * 10^(14-e10)) with 10^k by repeated squaring, then layout), `rt_fpow`
  (integral exponent: x87 square-and-multiply in extended precision; fractional: `fyl2x`/`f2xm1`/`fscale`; edx = error code),
  `rt_fmod` (exact integer shift-and-subtract, like musl; replaces `fprem` because QEMU emulates fprem inexactly). The routines set the x87
  control word themselves (Windows starts processes with 53-bit precision, which would break the digit generation). They may clobber
  every register except rbp/rsp. `rt_print_float` (hand-written in `runtime()`) calls `rt_fmt_float` and `rt_print_str`.
- `tools/fuzz_float.py [count]` runs the three routines in Unicorn on many values against Python (`'%.14e'` reference for the format, `math.fmod`,
  `math.pow`). Last result: formatting 0 differences on ~3000 values (random bit patterns, denormals, boundaries); fmod 0; integral pow within 1 ulp.
  Fractional pow in the emulator is only ~4e-15 accurate because QEMU computes `fyl2x`/`f2xm1` in double precision; the real FPU is better,
  so tests with fractional exponents use values whose 15-digit result agrees (e.g. `2 ^ 0.5`, `4.0 ^ 0.5`).
- Output format decision: 15 significant digits (APL-like, hides binary noise: `0.1 + 0.2` prints `0.3`), Python-like layout (`1e-05`, `1.5e+300`,
  `100.0`). A shortest-round-trip (Python repr) printer needs bignum or Ryu tables and was judged too much for now. Known limitation: the 15th
  digit may be off by one in roughly 1 case in 10 000 (extended-precision rounding), none seen in the fuzz run.
- Decisions: float `/` or `%` by zero is a runtime error (like ints; no INF/NAN literals yet, but overflow can still produce inf/nan);
  comparisons are exact; truthiness of numbers works for floats; `^` with float operands needs a positive base for fractional exponents.

### Name resolution (`Resolver.lookup`)
Shared by Checker and CodeGen. `lookup(name, scope, line, mode)` -> `("g",name)` | `("l",scope,name)` |
`("f",owner,name)`. `mode` `^` -> global; `@` -> nearest enclosing function that owns the name; plain names
follow `globals_decl` / `nonlocal_decl` first, then local, then enclosing functions, then globals.

### Type checker (`Checker`)
- Monomorphic unification (Hindley-Milner without generalisation). `Ty` kinds: `int`, `fn(params, ret)`, `var`.
  Variables are keyed `("g",name)` or `(scope,name)`. Every function gets a type with a fresh variable per
  parameter and for the result (`fn_ty`); bodies are checked once (`check_body`).
- Function types may be recursive (user decision; `fn(T) -> T`): there is no occurs check, `unify_raw` skips pairs of
  function types already being compared (`seen`), `show()` cuts cycles with `...`.
- Conditional `c ? a ! b`: `c` int, both branches unified.
- Fixed by decision: variable keeps the type of its first value; one signature per function; `==`/`!=` need equal
  types; everything else needs int. Bare `return` / falling off the end are NOT unified (user: "don't deal with it").
- Unresolved variables at the end are simply ignored (they cannot change code generation: both types are one word).
- Because of the checks, runtime arity/not-a-function errors are gone; only the null check of a call remains
  (a function variable assigned only inside a function that has not run).

### Code generation conventions
- Expression result in **rax**. Binary ops: eval left, `push rax`, eval right, `mov rcx,rax`, `pop rax`.
  Only rax/rcx/rdx are used by generated code as scratch; runtime routines clobber
  rcx, rdx, r8-r11, rsi, rax and preserve rbp. No value is ever kept in a register across a call.
- Chained comparison: the previous operand lives at `[rsp]` while the next one is evaluated; each link
  jumps to a fail label when false (`FAIL_CC`).
- Power: square-and-multiply loop inline; negative exponent -> `rt_negexp`.
- Runtime routines (`rt_print_str`, `rt_print_int`, `rt_alloc`, `rt_divzero`, `rt_notfn`, `rt_negexp`)
  set up their own aligned frame, so callers never worry about 16-byte alignment. `exit_process` aligns too.
- `Asm.rip(opcode_bytes, symbol)`: instruction whose **last 4 bytes** are the rip-relative disp32.
  `Asm._ref(label)` + `call/jmp/jcc` for rel32 to labels. `lea rax,[rip+label]` is `48 8D 05` + `_ref`.
- **Calling convention (own):** caller pushes args left->right, evaluates the callee value (closure
  pointer) into rax, checks null (`rt_notfn`), `push rax`, `call [rax]`. Callee: `push rbp; mov rbp,rsp;
  push 0 * nlocals`, `ret 8*(nparams+1)`. Result in rax. Frame: `[rbp+16]` = closure ptr, params above, locals below.
- **Closure object:** `[code address, nparams, box ptr 0, box ptr 1, ...]` (`nparams` is no longer used at run
  time). Closures without free variables use one static 16-byte object in `.data`; others are `rt_alloc`ed.
- **Boxed variables:** locals/params captured by nested functions live in 8-byte heap boxes; free variables are
  reached through the closure.
- **Hoisting:** `hoist(scope)` creates closures of all `named_fns` at scope entry.
- Use-before-assignment is checked textually in codegen (`scope.defined`).
- Program start: GetStdHandle(stdout), `SetConsoleOutputCP(65001)`, GetProcessHeap. (Side effect: the console
  keeps UTF-8 afterwards; restoring the old code page was judged not worth it.)

### PE writer (`build_pe`)
- Sections `.text` (RX) at 0x1000, `.idata` (RW), `.data` (RW). ImageBase 0x140000000, no relocs, console
  subsystem, 1 MB stack. kernel32 imports (list `IMPORTS`): GetStdHandle, WriteFile, SetConsoleOutputCP,
  ExitProcess, GetProcessHeap, HeapAlloc.
- `.data` layout: 0 stdout handle, 8 (unused), 0x10 `written`, 0x18 heap handle, 0x20..0x40 number buffer
  (`numbuf_end`), 0x40..0x80 unused (was the input buffer), then globals (8 bytes each), static closures
  (16 each), then strings (a NUL byte is appended but lengths are always explicit, so NUL inside strings is fine).
  Strings 0..3 are reserved for the runtime (newline, division by zero, unset function, negative exponent).

## 2. Decision log (why things are the way they are)
- Direct PE output instead of assembler/linker: no dependencies, user asked for "compiler in Python".
- Comments `--`, `--[[ ]]--`, `--[[ --]]`; newline-terminated statements, `;` optional where clear.
- One-line bodies run to the end of the line and nest; dangling else binds to the nearest `if`.
- Globals via `^x`, enclosing-function variables via `@x` (draft, user expects to redo it). No shadowing of a
  global by a local with the same name in one function (user: "forget shadowed global vars").
- Types: int and function only, inferred, checked statically; no annotations; falling off the end not checked.
- Signed ints everywhere except `& | ~` which just see 64 bits; hex literals wrap to signed.
- `'..'` byte string vs `".."` unicode string differ only in the meaning of `^XX` for now.
- Power operator `^`: right associative, BELOW unary operators (`-2^2 = 4`), negative exponent is a runtime error (simplest).
- Closures capture by reference via heap boxes; no GC (leak) accepted.
- Keyword `function` with synonym `\`; `fn` is gone. One parameter may be written without parentheses. `@x` replaced `\x`
  as the enclosing-function variable ("temporary", user). `{...}` is an ordinary statement; `skip` the empty statement.
- All variables start as 0 (frames are zeroed, `.data` is zero, boxes are `HEAP_ZERO_MEMORY`); a function variable that is
  still 0 gives `runtime error: call of an unset function`.
- Archive: a `.zip` is delivered, not 7z (7-Zip is not installed in the sandbox and would have to be installed each session).
- `input` was removed on purpose (no way to read values for now).
- Expression-bodied functions (`function f(x) x*x`) and the "last expression is the result" rule were removed.

## 3. Known limitations / ideas for later
- (floats are done, see above; open: INF/NAN, tolerance, formatting, conversions)
- Strings as values, unicode strings as 32-bit arrays, hex byte strings `#'..'`, input, arrays, `for`, GC,
  overflow checks, `INT_MIN / -1`, shifts, generalised (polymorphic) function types, checking returns on all
  paths, better error recovery (the compiler stops at the first error), `@x` at more than one level.
- The unused-expression warning is intentionally simple (any non-call expression statement).
- Not verified on real Windows in this session: the x87/SSE float routines (verified in Unicorn only), `SetConsoleOutputCP` (faked in the emulator) and the UTF-8
  console output. Everything else is exercised through the emulator. (User added: all tests passed on real Windows.)

## 4. Testing
- `python run_tests.py [-k name] [-v] [--emu] [--keep]`; see the header of run_tests.py for file conventions
  (`NAME.ka/.expected/.exit/.warn`, `err_NAME.ka/.error`). Expected output is compared as raw bytes.
- The emulator fakes kernel32 and asserts 16-byte stack alignment at every API call.
- When adding a feature add tests for: normal use, interaction with blocks/continuation lines,
  error messages, and at least one regression for any bug found.

## 5. Session checklist
1. User uploads the zip/folder. Unzip, read NOTES.md, LANGUAGE.md; `pip install unicorn pefile`; run `python run_tests.py --emu`.
2. Implement the requested change; run all tests; add/adjust tests and docs.
3. Re-zip (`ka.zip`) and present it; summarise what to test on Windows.
