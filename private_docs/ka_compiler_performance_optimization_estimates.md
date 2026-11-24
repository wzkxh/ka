# Ka Compiler (`ka.py` v6.5.2) — Performance Optimization Estimates

Because `CodeGen` currently uses a **pure stack-based accumulator model**—evaluating every expression into `rax`, pushing every intermediate binary operand onto the stack (`push rax` / `pop rax`), storing all variables in memory (`[rbp+off]` or `[rip+var]`), and performing indirect closure calls for every function—there is **substantial room for optimization**.

---

## 1. Realistic Performance Gain Estimate

* **Overall expected speedup on compute-heavy benchmarks (`fib`, `prime`, `mb`, `crc64`, `cs`, `sim`, `e_pi`, `fin`):** **35% to 70% faster** (roughly **1.5x–3x** throughput on tight loops), depending on how branch- vs. ALU-bound each benchmark is.
  * **Loop/expression-heavy integer & bitwise code (`crc64`, `prime`, `cs`):** **50–80% gain**. Eliminating stack `push`/`pop` on every operator and keeping hot locals in registers removes a large fraction of memory traffic and instruction count.
  * **Recursive / call-heavy code (`fib`):** **25–45% gain**. Direct calls for non-reassigned named functions plus leaner stack frames cut call overhead significantly.
  * **Float-heavy code (`mb`, `e_pi`, `sim`, `fin`):** **30–50% gain**. Currently, every float operation moves bits between XMM and GPRs (`movq rax, xmm0` → `push rax` → `pop rax` → `movq xmm0, rax`), adding round-trip latency on every `+`, `-`, `*`, `/`.

---

## 2. Concrete Optimizations Ranked by Impact vs. Effort

| Optimization | Est. Gain | Effort (in `ka.py`) | Risk / Drawbacks |
| :--- | :--- | :--- | :--- |
| **1. RHS-Immediate / Right-Operand Bypass** (avoid `push rax` / `pop rax` when the right operand of `+ - * & \| ~ << >> == <` is a literal, local/global variable, or simple leaf expression) | **15–25%** | **Low** (~80–120 lines) | **Very low.** Currently `a + 1` or `x & y` emits `eval a; push rax; eval 1; mov rcx, rax; pop rax; add rax, rcx`. Emitting `add rax, 1` or `add rax, [rbp-8]` directly cuts instruction count in half for simple expressions with zero ABI risk. |
| **2. Register Allocation for Hot Locals & Parameters** (assign non-boxed, non-captured locals/params in leaf or loop-heavy functions to callee-saved registers `rbx, r12, r13, r14, r15` or scratch `r8–r11` between calls) | **20–35%** | **Medium** (~200–300 lines) | **Medium.** Runtime helpers (`rt_print_*`, `rt_strcat`, `rt_strcmp`, `rt_alloc`) currently clobber `rbx, r12–r15`. Either save/restore used callee-saved regs in function prologues/epilogues, or allocate only across call-free regions (loops without calls). |
| **3. Keep Floats in `xmm0`/`xmm1` Across Compound Expressions** (avoid `movq rax, xmm0` + `push rax` + `movq xmm0, rax` between nested float ops) | **10–20%** (on float code) | **Low–Medium** (~100 lines) | **Low.** XMM-to-GPR transitions have a 1–3 cycle latency penalty on x64; keeping intermediate float AST subtrees in `xmm` registers eliminates the round-trips. |
| **4. Direct Calls for Unmodified Named Functions** (skip closure allocation/null-check/indirect `call [rax]` when a `function foo` is never reassigned and has no `free` variables) | **10–20%** (on call-heavy code) | **Low** (~50–80 lines) | **Very low.** Already noted as an open idea in `IMPLEMENTATION.txt` §7. If `foo` is a constant (`FOO`) or never assigned after `hoist`, `call fn1_foo` replaces `mov rax, [var]; test rax, rax; jz rt_notfn; push rax; call [rax]`. |
| **5. Constant Folding & Strength Reduction** (fold constant AST subtrees at compile time; replace `* 2^k` with `shl`, `\ 2^k` with arithmetic shift + bias, `% 2^k` with `and` for positive divisors) | **5–10%** | **Low** (~80–100 lines) | **Low.** Must preserve exact Ka semantics (e.g., 64-bit two's-complement wrapping and floored division/modulo signs). |
| **6. Peephole Pass on Bytecode / Instruction Buffer** (strip `push rax; pop rax`, `mov reg, 0` → `xor reg, reg`, redundant `mov rcx, rax` before commutative ops) | **3–8%** | **Low–Medium** (~120 lines) | **Medium.** Because `Asm` emits raw machine bytes directly without an intermediate instruction list, a peephole pass requires either a small structured IR list before encoding or careful instruction-boundary tracking. |

---

## 3. Main Trade-offs & Architectural Drawbacks

1. **Compiler Complexity & Size:** `ka.py` is clean and readable at ~1,050 lines (~105 KB). Adding full register allocation and an IR layer would add ~400–600 lines and make debugging code generation harder.
2. **Runtime Register Clobbering Contract:** Right now, runtime helpers (`rt_print_*`, `rt_strcat`, etc.) freely clobber `rbx, rsi, rdi, r12–r15` because no value lives in a register across statements. Before keeping any variable in `rbx` or `r12–r15`, either the runtime functions must preserve them (standard Windows x64 ABI) or user functions must save/restore them around calls.
3. **Compile Speed:** Virtually unaffected—even with all optimizations above, compiling a `.ka` file will still take only a few milliseconds.

---

## 4. Recommended Starting Point

If you want the **highest speedup for the least code and lowest bug risk**, start with:

1. **#1 — Leaf/RHS-operand bypass in `CodeGen.expr`**
2. **#4 — Direct calls for constant/unreassigned functions**
3. **#5 — AST constant folding**

Together, those take **~200 lines** of straightforward Python, require **zero** changes to your calling convention or runtime helpers, and will capture roughly **half to two-thirds of the total possible speedup**.