#!/usr/bin/env python3
"""
ka - a compiler for the language "Ka" that produces a native Windows x64 console
executable (PE32+) directly. Pure Python 3, no dependencies (the compiler runs on any
OS; the produced .exe runs on Windows).

Usage:
    python ka.py program.ka              -> program.exe
    python ka.py program.ka -o out.exe

The language is described in LANGUAGE.md. Pipeline:
    strip comments -> tokenize (NEWLINE/INDENT/DEDENT) -> parse to AST (tuples)
    -> type check (static inference) -> x86-64 code -> PE image
"""
import argparse
import os
import re
import struct
import sys


VERSION = "6.1"                         # see RELEASE_NOTES.md


class CompileError(Exception):
  pass


# ----------------------------------------------------------------------------
# Source preparation: comment removal
# ----------------------------------------------------------------------------
def strip_comments(src):
  """Replace every comment by spaces (newlines are kept, so line numbers stay right).
    Comments:  -- to end of line;   # to end of line (a hash followed by a space or the end of the line, but not right after a
               digit: `2#` starts a binary literal; #ff is a hex literal);
               --[[ ... ]]-- inside one line;   --[[ ... --]]  over several lines (the rest of the closing line is ignored)."""
  out, i, n = [], 0, len(src)

  def blank(text):
    return re.sub(r"[^\n]", " ", text)

  while i < n:
    c = src[i]
    if c in "\"'":                                  # string: copy as is (comments do not start inside)
      j = i + 1
      while j < n and src[j] != c and src[j] != "\n":
        if src[j] == "^" and j + 1 < n and src[j + 1] != "\n":
          j += 1
        j += 1
      end = j + 1 if j < n and src[j] == c else j
      out.append(src[i:end])
      i = end
    elif src.startswith("--", i):
      nl = src.find("\n", i)
      nl = n if nl == -1 else nl
      end = nl
      if src.startswith("--[[", i):
        a, b = src.find("]]--", i + 4), src.find("--]]", i + 4)
        if a != -1 and a < nl and (b == -1 or a < b):      # inline comment
          end = a + 4
        elif b != -1:                                      # multi-line comment
          e = src.find("\n", b + 4)
          end = n if e == -1 else e
        else:
          line = src.count("\n", 0, i) + 1
          raise CompileError(f"line {line}: comment '--[[' is never closed")
      out.append(blank(src[i:end]))
      i = end
    elif c == "#" and src[i + 1:i + 2] in (" ", "\n", "") and not (i > 0 and src[i - 1] in "0123456789"):   # `# comment`
      nl = src.find("\n", i)
      end = n if nl == -1 else nl
      out.append(blank(src[i:end]))
      i = end
    else:
      j = i
      while j < n and src[j] not in "\"'-#":
        j += 1
      if j == i:
        j = i + 1
      out.append(src[i:j])
      i = j
  return "".join(out)


# ----------------------------------------------------------------------------
# Lexer  (produces NEWLINE / INDENT / DEDENT tokens as well)
# ----------------------------------------------------------------------------
KEYWORDS = {"if", "elif", "else", "while", "break", "continue", "print", "exit", "function", "return", "skip"}
STMT_KW = {"if", "while", "break", "continue", "print", "exit", "return", "skip"}

TOKEN_RE = re.compile(r"""
    (?P<ws>[ \r]+)
  | (?P<nl>\n)
  | (?P<hex>\#\w*)
  | (?P<flt>\d+(?:_\d+)*(?:\.\d+(?:_\d+)*(?:[eE][-+]?\d+(?:_\d+)*)?|[eE][-+]?\d+(?:_\d+)*))
  | (?P<num>\d\w*(?:\#\w*)?)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>&&=|\|\|=|<<=|>>=|\+>=|<\*=|\*>=|\\=|==|!=|<=|>=|&&|\|\||<<|>>|\+>|<\*|\*>|\+=|-=|\*=|/=|%=|\^=|&=|\|=|~=|[-+*/%<>=!(){};,:&|~^\\?@])
""", re.X | re.A)

SIMPLE_ESC = {"n": "\n", "t": "\t", "r": "\r", "^": "^", '"': '"', "'": "'"}
HEX = "0123456789abcdefABCDEF"

# compound assignment:  x op= e   means   x = x op e
COMPOUND = {"+=": "+", "-=": "-", "*=": "*", "/=": "/", "%=": "%", "^=": "^", "&=": "&", "|=": "|", "~=": "~",
            "&&=": "&&", "||=": "||", "<<=": "<<", ">>=": ">>", "+>=": "+>", "<*=": "<*", "*>=": "*>", "\\=": "\\"}
SHIFT_OPS = ("<<", ">>", "+>", "<*", "*>")

# a line ending with one of these is not finished: the statement continues
CONT_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", "<=", ">", ">=", "&&", "||", "!", "=", ",",
            "&", "|", "~", "^", "?", "\\"} | set(COMPOUND) | set(SHIFT_OPS)


def continues(tok):
  return tok[0] == "op" and tok[1] in CONT_OPS


def lex_string(src, pos, line):
  """-> (bytes, kind, new position); kind 'b' for '...' (byte string), 'u' for "..." (unicode)."""
  q, n = src[pos], len(src)
  kind = "u" if q == '"' else "b"
  i, out = pos + 1, bytearray()
  while True:
    if i >= n or src[i] == "\n":
      raise CompileError(f"line {line}: string is not closed")
    c = src[i]
    if c == q:
      return bytes(out), kind, i + 1
    if c != "^":
      out += c.encode("utf-8")
      i += 1
      continue
    e = src[i + 1:i + 2]
    if e in SIMPLE_ESC and e != "":
      out += SIMPLE_ESC[e].encode()
      i += 2
    elif e in ("u", "U"):
      k = 4 if e == "u" else 6
      digits = src[i + 2:i + 2 + k]
      if len(digits) != k or any(d not in HEX for d in digits):
        raise CompileError(f"line {line}: bad escape ^{e}{digits} (needs {k} hex digits)")
      cp = int(digits, 16)
      if cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF:
        raise CompileError(f"line {line}: bad unicode escape ^{e}{digits}")
      out += chr(cp).encode("utf-8")
      i += 2 + k
    else:
      digits = src[i + 1:i + 3]
      if len(digits) != 2 or any(d not in HEX for d in digits):
        raise CompileError(f"line {line}: bad escape ^{src[i + 1:i + 2]}")
      v = int(digits, 16)
      out += bytes([v]) if kind == "b" else chr(v).encode("utf-8")
      i += 3


def tokenize(src):
  toks, pos, line, n = [], 0, 1, len(src)
  paren, paren_line = 0, 0
  paren_saved = []              # paren state of the enclosing level while inside '{ }'
  stacks = [[]]                 # one indentation stack per open '{'
  brace_lines = []
  at_start, colon_pending = True, False

  def add(kind, val):
    toks.append((kind, val, line))

  while pos < n:
    if at_start:              # measure indentation of a new logical line
      p, col = pos, 0
      while p < n and src[p] in " \r":
        if src[p] == " ":
          col += 1
        p += 1
      if p < n and src[p] != "\n":
        at_start = False
        if src[p] != "}":
          cur = stacks[-1]
          if not cur:
            cur.append(col)
          elif col > cur[-1]:
            if not colon_pending:
              raise CompileError(f"line {line}: unexpected indentation")
            cur.append(col)
            add("indent", None)
          elif col < cur[-1]:
            popped = False
            while len(cur) > 1 and col < cur[-1]:
              cur.pop()
              add("dedent", None)
              popped = True
            if popped and col > cur[-1]:
              raise CompileError(f"line {line}: inconsistent indentation")
        colon_pending = False

    if src[pos] in "\"'":
      data, kind, pos = lex_string(src, pos, line)
      toks.append(("str", (data, kind), line))
      continue
    m = TOKEN_RE.match(src, pos)
    if not m:
      if src[pos] == "." and src[pos + 1:pos + 2].isdigit():
        raise CompileError(f"line {line}: bad number '.{src[pos + 1]}...' (a float needs digits before the dot: 0.5)")
      raise CompileError(f"line {line}: unexpected character {src[pos]!r}")
    kind, text = m.lastgroup, m.group()
    pos = m.end()
    if kind == "nl":
      if paren == 0 and not (toks and continues(toks[-1])):
        if toks and toks[-1][0] != "nl":
          colon_pending = toks[-1][0] == "op" and toks[-1][1] == ":"
          add("nl", None)
        at_start = True
      line += 1
    elif kind == "ws":
      pass
    elif kind == "flt":                                  # 1.5   1.5e-3   2e10   (digits may contain '_')
      if pos < n and (src[pos].isalnum() or src[pos] in "_."):
        raise CompileError(f"line {line}: bad number '{text}{src[pos]}...'")
      v = float(text.replace("_", ""))
      if v == float("inf"):
        raise CompileError(f"line {line}: float literal too large")
      toks.append(("flt", v, line))
    elif kind == "num" and "#" in text:                  # binary literal 2#0001_1011
      m = re.fullmatch(r"2#([01]+(?:_[01]+)*)", text)
      if not m:
        raise CompileError(f"line {line}: bad binary literal '{text}' (the form is 2#0001_1011, base 2 only)")
      v = int(m.group(1).replace("_", ""), 2)
      if v >= 2 ** 64:
        raise CompileError(f"line {line}: binary literal too large")
      toks.append(("hex", v - 2 ** 64 if v >= 2 ** 63 else v, line))     # (same token kind as #hex: already wrapped)
    elif kind == "num" and text[:2] in ("0x", "0X"):    # hexadecimal literal 0xFF (the same as #FF)
      if not re.fullmatch(r"0[xX][0-9a-fA-F]+(_[0-9a-fA-F]+)*", text):
        raise CompileError(f"line {line}: bad hex literal '{text}' (the form is 0xFF or 0xFF_FF)")
      v = int(text[2:].replace("_", ""), 16)
      if v >= 2 ** 64:
        raise CompileError(f"line {line}: hex literal too large")
      toks.append(("hex", v - 2 ** 64 if v >= 2 ** 63 else v, line))
    elif kind == "num":
      if not re.fullmatch(r"\d+(_\d+)*", text):
        hint = ""
        if "_" in text:
          hint = " ('_' is allowed only between digits)"
        elif re.fullmatch(r"0[bB][01]+", text):
          hint = f" (binary literals are written 2#{text[2:]})"
        raise CompileError(f"line {line}: bad number '{text}'{hint}")
      if pos < n and src[pos] == ".":
        raise CompileError(f"line {line}: bad number '{text}.' (a float needs digits after the dot: {text}.0)")
      toks.append(("num", int(text.replace("_", "")), line))
    elif kind == "hex":
      if not re.fullmatch(r"#[0-9a-fA-F]+(_[0-9a-fA-F]+)*", text):
        raise CompileError(f"line {line}: bad hex literal '{text}'")
      v = int(text[1:].replace("_", ""), 16)
      if v >= 2 ** 64:
        raise CompileError(f"line {line}: hex literal too large")
      toks.append(("hex", v - 2 ** 64 if v >= 2 ** 63 else v, line))
    elif kind == "id":
      toks.append(("kw" if text in KEYWORDS else "id", text, line))
    else:
      if text == "(":
        paren += 1
        paren_line = line
      elif text == ")":
        paren -= 1
        if paren < 0:
          raise CompileError(f"line {line}: unmatched ')'")
      elif text == "{":
        stacks.append([])
        brace_lines.append(line)
        paren_saved.append((paren, paren_line))     # newlines count again inside { }
        paren = 0
      elif text == "}":
        if len(stacks) == 1:
          raise CompileError(f"line {line}: unmatched '}}'")
        if paren:
          raise CompileError(f"line {paren_line}: '(' is never closed")
        paren, paren_line = paren_saved.pop()
        brace_lines.pop()
        for _ in stacks.pop()[1:]:       # close indented blocks still open
          add("dedent", None)
      toks.append(("op", text, line))

  if paren:
    raise CompileError(f"line {paren_line}: '(' is never closed")
  if brace_lines:
    raise CompileError(f"line {brace_lines[-1]}: '{{' is never closed")
  if toks and toks[-1][0] != "nl":
    add("nl", None)
  for _ in stacks[0][1:]:
    add("dedent", None)
  add("eof", None)
  return toks


# ----------------------------------------------------------------------------
# Parser -> AST (tuples)
#   statements (line is always the last element, except where noted):
#     ("assign", name, expr, line, mode[, True if it defines a constant])   ("print", items, line)   ("if", cond, then, else, line)
#     ("while", cond, body, line)  ("exit", e, line)  ("exprstmt", e, line)  ("return", e|None, line)
#     ("fn", Scope)  ("block", stmts)  ("skip",)  ("break",)  ("continue",)
#   expressions:
#     ("num", n) ("flt", x) ("var", name, line, mode) ("fnlit", Scope) ("call", callee, args, line)
#     ("bin", op, l, r) ("cmp", ops, operands) ("and"/"or", l, r) ("neg"/"not"/"bnot", e)
#   mode: None = plain name, "^" = global (^x), "@" = variable of an enclosing function (@x)
# ----------------------------------------------------------------------------
INT_MAX = 2 ** 63 - 1
INT_MIN = -(2 ** 63)
MAX_PARAMS = 20


def is_const_name(name):
  """names made of capitals (digits and _ allowed) with at least one letter are constants: MAX_SPEED, X2, _N"""
  return re.fullmatch(r"[A-Z0-9_]*[A-Z][A-Z0-9_]*", name) is not None


def describe(tok):
  k, v, _ = tok
  if k == "eof":
    return "end of file"
  if k == "nl":
    return "end of line"
  if k == "indent":
    return "unexpected indentation"
  if k == "dedent":
    return "end of indented block"
  if k == "str":
    return "a string"
  return repr(v)


class Scope:
  """The global scope (parent None) or one function.
    slots: global scope -> {name: index in .data}; function -> {name: rbp offset}
    Frame layout of a function:
        [rbp+16] closure pointer, params above it, locals below rbp.
    Variables captured by nested functions live in heap boxes (see `boxed`);
    `free` lists the boxes a function receives through its closure."""

  def __init__(self, name, parent, params=()):
    self.name, self.parent = name, parent
    self.depth = 0 if parent is None else parent.depth + 1
    self.params = list(params)
    n = len(self.params)
    self.slots = {p: 24 + 8 * (n - 1 - i) for i, p in enumerate(self.params)}
    self.nlocals = 0
    self.named_fns = []                 # `fn name ...` definitions directly in this scope
    self.globals_decl, self.nonlocal_decl = set(), set()    # names used as ^x / \x here
    self.body, self.label = None, None
    self.defined = set(self.params)     # used by codegen (use-before-assignment check)
    self.boxed = set()                  # own variables captured by nested functions
    self.free = {}                      # (owner scope, name) -> index in closure
    self.queued = False
    self.consts = {}                    # constants defined in this scope: name -> line
    self.ty, self.checked = None, False  # used by the type checker


class Parser:
  def __init__(self, toks):
    self.t = toks
    self.i = 0
    self.global_scope = Scope("<main>", None)
    self.scope = self.global_scope
    self.vars = self.global_scope.slots   # name -> index (global variables)
    self.fn_globals = set()             # names assigned as ^x inside some function
    self.nfuncs = 0
    self.closed_at = -1                 # token index right after a consumed line end / dedent
    # strings 0..3 are used by the runtime
    self.strings = [b"\n", b"runtime error: division by zero\n",
                    b"runtime error: call of an unset function\n",
                    b"runtime error: negative exponent\n",
                    b"runtime error: power of a negative number with a fractional exponent\n"]
    self.loop_depth = 0
    self.nblock = 0                     # how many blocks are open in the current scope (a function body is one block)
    self.ctx = []                       # open '(' / '{' (innermost last)
    self.warnings = []

  # -- helpers
  def peek(self):
    return self.t[self.i]

  def next(self):
    tok = self.t[self.i]
    self.i += 1
    return tok

  def is_(self, val):
    k, v, _ = self.peek()
    return k in ("op", "kw") and v == val

  def accept(self, val):
    if self.is_(val):
      self.i += 1
      return True
    return False

  def expect(self, val):
    if not self.accept(val):
      raise CompileError(f"line {self.peek()[2]}: expected {val!r}, found {describe(self.peek())}")

  def err(self, msg):
    raise CompileError(f"line {self.peek()[2]}: {msg}")

  def skip_nl(self):
    while self.peek()[0] == "nl":
      self.i += 1

  def skip_seps(self):                    # blank lines and stray ';'
    while self.peek()[0] == "nl" or self.is_(";"):
      self.i += 1

  def at_end(self):                       # nothing follows (used where an expression is optional)
    k, v, _ = self.peek()
    return (k in ("nl", "eof", "dedent")
            or (k == "op" and v in (";", "}", ")", ","))
            or (k == "kw" and v in STMT_KW | {"else", "elif"}))

  def end_stmt(self):
    """A statement ends at a line end, ';', a closing bracket, 'else'/'elif' or the start of
        another statement (keyword)."""
    if self.i == self.closed_at:        # a nested body (fn literal) already consumed the line end
      return
    if self.accept(";"):
      self.closed_at = self.i
      return
    k, v, _ = self.peek()
    if k == "nl":
      self.i += 1
      self.closed_at = self.i
    elif k in ("eof", "dedent"):
      pass
    elif k == "op" and (v in ("}", "{") or (v in (")", ",") and self.ctx and self.ctx[-1] == "(")):
      pass
    elif k == "kw" and (v in STMT_KW or v in ("else", "elif", "function")):
      pass
    else:
      self.err(f"expected end of statement, found {describe(self.peek())}")

  # -- statements
  def program(self):
    stmts = []
    while True:
      self.skip_seps()
      if self.peek()[0] == "eof":
        return stmts
      stmts.append(self.stmt())

  def brace_block(self):
    self.expect("{")
    self.ctx.append("{")
    self.nblock += 1
    stmts = []
    while True:
      self.skip_seps()
      if self.accept("}"):
        self.ctx.pop()
        self.nblock -= 1
        return stmts
      if self.peek()[0] == "eof":
        self.err("missing '}'")
      stmts.append(self.stmt())

  def body_continues(self):               # in a one-line body: does another statement follow?
    if self.t[self.i - 1][0] in ("nl", "dedent"):
      return False                    # the line (or a nested indented block) is finished
    k, v, _ = self.peek()
    if k == "kw" and v in STMT_KW:
      return True
    return not self.at_end()

  def block(self, allman=True):
    self.nblock += 1
    try:
      return self.block_(allman)
    finally:
      self.nblock -= 1

  def block_(self, allman=True):
    save = self.i
    if allman:
      self.skip_nl()                  # allow '{' on the next line
    if self.is_("{"):
      return self.brace_block()
    self.i = save
    if self.accept(":"):
      if self.peek()[0] != "nl":      # one-line body:  if x: print 1; print 2
        stmts = []
        while True:
          stmts.append(self.stmt())
          if not self.body_continues():
            return stmts
      self.skip_nl()
      if self.peek()[0] != "indent":
        self.err("expected an indented block after ':'")
      self.next()
      stmts = []
      while True:
        self.skip_seps()
        if self.peek()[0] == "dedent":
          self.next()
          self.closed_at = self.i
          return stmts
        if self.peek()[0] == "eof":
          return stmts
        stmts.append(self.stmt())
    self.err(f"expected '{{' or ':', found {describe(self.peek())}")

  # -- variables and scopes
  def declare(self, name, mode, line):
    """register the target of an assignment"""
    sc = self.scope
    if mode == "^":
      self.global_scope.slots.setdefault(name, len(self.global_scope.slots))
      if sc.parent is not None:
        self.use_marked(name, mode, line)
        self.fn_globals.add(name)
    elif mode == "@":
      self.use_marked(name, mode, line)
    elif sc.parent is None:
      sc.slots.setdefault(name, len(sc.slots))
    elif name in sc.globals_decl:
      raise CompileError(f"line {line}: '{name}' is used as '^{name}' in '{sc.name}', "
                         f"so it cannot also be a local variable there")
    elif name in sc.nonlocal_decl:
      raise CompileError(f"line {line}: '{name}' is used as '@{name}' in '{sc.name}', "
                         f"so it cannot also be a local variable there")
    elif name not in sc.slots:
      sc.nlocals += 1
      sc.slots[name] = -8 * sc.nlocals

  def use_marked(self, name, mode, line):
    """a ^name or @name written inside a function"""
    sc = self.scope
    if mode == "@":
      if sc.parent is None or sc.parent.parent is None:
        raise CompileError(f"line {line}: '@{name}' needs an enclosing function")
    if sc.parent is None:
      return
    if name in sc.slots:
      raise CompileError(f"line {line}: '{name}' is already local to '{sc.name}', "
                         f"it cannot also be used as '{mode}{name}'")
    (sc.globals_decl if mode == "^" else sc.nonlocal_decl).add(name)

  def const_problem(self, e):
    """why `e` is not a constant expression (None if it is): numbers, constants defined above, operators,
    function literals"""
    k = e[0]
    if k == "var":
      if e[3] not in (None, "^") or not is_const_name(e[1]):
        return f"it uses the variable '{e[1]}'"
      sc = self.global_scope if e[3] == "^" else self.scope
      while sc is not None and e[1] not in sc.consts:        # constants of this function, of the functions around it, global ones
        sc = None if e[3] == "^" else sc.parent
      if sc is None:
        return f"it uses '{e[1]}', which is defined later"
      return None
    if k == "call":
      return "it calls a function"
    if k in ("bin", "and", "or"):
      parts = e[2:4] if k == "bin" else e[1:3]
    elif k == "cmp":
      parts = e[2]
    elif k == "cond":
      parts = e[1:4]
    elif k in ("neg", "not", "bnot"):
      parts = e[1:2]
    else:                                   # num, fnlit
      return None
    for p in parts:
      why = self.const_problem(p)
      if why:
        return why
    return None

  def define_const(self, name, mode, line):
    sc = self.scope
    if mode is not None and sc.parent is not None:
      raise CompileError(f"line {line}: constant '{name}' cannot be written as {mode}{name} "
                         f"(a constant belongs to the scope where it is defined)")
    if self.nblock != (0 if sc.parent is None else 1):
      raise CompileError(f"line {line}: constant '{name}' can only be defined directly at the top level of the program "
                         f"or of a function (not inside an 'if', a loop or another block)")
    if name in sc.consts:
      raise CompileError(f"line {line}: constant '{name}' is already defined (line {sc.consts[name]})")

  def assign(self, name, mode):
    optok = self.next()                     # '=' or a compound operator like '+='
    line, op = optok[2], optok[1]
    e = self.expr()
    if op != "=":                           # x op= e   ->   x = x op e
      if is_const_name(name):
        raise CompileError(f"line {line}: constant '{name}' cannot be changed")
      cur = ("var", name, line, mode)
      bop = COMPOUND[op]
      e = ("and" if bop == "&&" else "or", cur, e) if bop in ("&&", "||") else ("bin", bop, cur, e)
    self.end_stmt()
    if is_const_name(name):
      if mode == "@":
        raise CompileError(f"line {line}: '@{name}': a constant cannot be an enclosing function's variable")
      self.define_const(name, mode, line)
      why = self.const_problem(e)
      if why:
        raise CompileError(f"line {line}: the value of constant '{name}' must be a constant expression "
                           f"(numbers, constants defined above, operators, function literals): {why}")
      self.scope.consts[name] = line
      self.declare(name, mode, line)
      return ("assign", name, e, line, mode, True)
    self.declare(name, mode, line)
    return ("assign", name, e, line, mode)

  def expr_stmt(self):
    line = self.peek()[2]
    e = self.expr()
    self.end_stmt()
    if e[0] != "call":
      self.warnings.append(f"line {line}: the value of this expression is not used")
    return ("exprstmt", e, line)

  def if_stmt(self, line):                # after 'if' / 'elif'
    cond = self.expr()
    then = self.block()
    els = []
    save = self.i
    self.skip_nl()
    if self.accept("elif"):
      els = [self.if_stmt(self.t[self.i - 1][2])]
    elif self.accept("else"):
      els = [self.stmt()] if self.is_("if") else self.block()
    else:
      self.i = save
    return ("if", cond, then, els, line)

  def stmt(self):
    k, v, line = self.peek()
    if (k == "kw" and v == "function") or (k == "op" and v == "\\"):
      last = len(self.t) - 1
      t1, t2 = self.t[min(self.i + 1, last)], self.t[min(self.i + 2, last)]
      if t1[0] == "id" and (t2[0] == "id" or (t2[0] == "op" and t2[1] == "(")):
        return self.fn_def()                    # function name(params) / function name param
      return self.expr_stmt()                     # a function literal used as a statement
    if k == "kw":
      if v == "skip":
        self.next()
        self.end_stmt()
        return ("skip",)
      if v == "print":
        self.next()
        items = []
        if not self.at_end():
          while True:
            s = self.string_item()
            if s is not None:
              self.strings.append(s)
              items.append(("str", len(self.strings) - 1))
            else:
              items.append(("expr", self.expr()))
            if not self.accept(","):
              break
        self.end_stmt()
        return ("print", items, line)
      if v == "if":
        self.next()
        return self.if_stmt(line)
      if v == "while":
        self.next()
        cond = self.expr()
        self.loop_depth += 1
        body = self.block()
        self.loop_depth -= 1
        return ("while", cond, body, line)
      if v in ("break", "continue"):
        self.next()
        if not self.loop_depth:
          raise CompileError(f"line {line}: '{v}' outside of a loop")
        self.end_stmt()
        return (v,)
      if v == "exit":
        self.next()
        e = self.expr()
        self.end_stmt()
        return ("exit", e, line)
      if v == "return":
        self.next()
        return self.return_stmt(line, optional=True)
      self.err(f"unexpected {v!r}")
    if k == "id":
      nk = self.t[self.i + 1]
      if nk[0] == "op" and (nk[1] == "=" or nk[1] in COMPOUND):
        self.next()
        return self.assign(v, None)
      return self.expr_stmt()
    if k == "op" and v == "=":                              # '=' is a short 'return'
      self.next()
      return self.return_stmt(line, optional=False)
    if k == "op" and v == "{":                              # a block is a statement like any other
      return ("block", self.brace_block())
    if k == "op" and v in ("^", "@"):
      last = len(self.t) - 1
      t1, t2 = self.t[min(self.i + 1, last)], self.t[min(self.i + 2, last)]
      if t1[0] == "id" and t2[0] == "op" and (t2[1] == "=" or t2[1] in COMPOUND):
        self.i += 2
        return self.assign(t1[1], v)
      return self.expr_stmt()
    if k in ("num", "hex", "flt") or (k == "op" and v in ("(", "-", "!", "~")):
      return self.expr_stmt()
    self.err(f"unexpected {describe(self.peek())}")

  def return_stmt(self, line, optional):
    if self.scope.parent is None:
      raise CompileError(f"line {line}: 'return' outside of a function")
    if optional and self.at_end():
      e = None
    elif self.at_end():
      raise CompileError(f"line {line}: '=' (return) needs a value")
    else:
      e = self.expr()
    self.end_stmt()
    return ("return", e, line)

  def string_item(self):
    """a print item that is a string: '...' / "..." literals written one after another,
        possibly inside parentheses (which may span lines). None if the item is not a string."""
    k = self.peek()[0]
    if k == "str":
      first = self.next()
      data, kind = first[1]
      while self.peek()[0] == "str":
        tok = self.next()
        if tok[1][1] != kind:
          raise CompileError(f"line {tok[2]}: cannot join '...' and \"...\" strings")
        data += tok[1][0]
      return data
    if self.is_("("):
      j = self.i
      while self.t[j][0] == "op" and self.t[j][1] == "(":
        j += 1
      if self.t[j][0] != "str":
        return None
      self.next()
      self.ctx.append("(")
      data = self.string_item()
      self.ctx.pop()
      self.expect(")")
      return data
    return None

  # -- functions
  def parse_function(self, name, line, literal):
    """after `function`/`\\` (literal) or after `function name` (definition): (params) or one param, then body"""
    params = []
    if self.accept("("):
      if not self.accept(")"):
        while True:
          k, pname, pl = self.next()
          if k != "id":
            raise CompileError(f"line {pl}: expected a parameter name")
          if pname in params:
            raise CompileError(f"line {pl}: duplicate parameter '{pname}'")
          params.append(pname)
          if not self.accept(","):
            break
        self.expect(")")
    elif self.peek()[0] == "id":                    # a single parameter needs no parentheses
      params.append(self.next()[1])
    else:
      self.err(f"expected '(' or a parameter name, found {describe(self.peek())}")
    for p in params:
      if is_const_name(p):
        raise CompileError(f"line {line}: parameter '{p}' looks like a constant "
                           f"(names in capitals are constants and cannot be parameters)")
    if len(params) > MAX_PARAMS:
      raise CompileError(f"line {line}: too many parameters (at most {MAX_PARAMS})")
    fn = Scope(name or "<function>", self.scope, params)
    fn.line = line
    self.nfuncs += 1
    fn.label = f"fn{self.nfuncs}_{name or 'anon'}"
    saved = (self.scope, self.loop_depth, self.nblock)
    self.scope, self.loop_depth, self.nblock = fn, 0, 0
    if not (self.is_("{") or self.is_(":") or (not literal and self.peek()[0] == "nl")):
      self.err(f"expected '{{' or ':' after the parameters, found {describe(self.peek())}")
    fn.body = self.block(allman=not literal)
    self.scope, self.loop_depth, self.nblock = saved
    return fn

  def fn_def(self):
    _, _, line = self.next()                       # 'function' or '\\'
    _, name, _ = self.next()
    if any(f.name == name for f in self.scope.named_fns):
      raise CompileError(f"line {line}: function '{name}' is already defined in this scope")
    if is_const_name(name):
      self.define_const(name, None, line)
      self.scope.consts[name] = line
    fn = self.parse_function(name, line, literal=False)
    self.scope.named_fns.append(fn)
    self.declare(name, None, line)
    return ("fn", fn)

  # -- expressions
  def expr(self):
    return self.cond()

  def cond(self):                                     # c ? a ! b   (right-associative, lowest level)
    c = self.or_()
    if self.accept("?"):
      a = self.expr()
      self.expect("!")
      return ("cond", c, a, self.cond())
    return c

  def or_(self):
    l = self.and_()
    while self.accept("||"):
      l = ("or", l, self.and_())
    return l

  def and_(self):
    l = self.eq()
    while self.accept("&&"):
      l = ("and", l, self.eq())
    return l

  def chain(self, ops, operand):
    """a < b <= c ...  -> one 'cmp' node; a single comparison stays a 'bin' node"""
    first = operand()
    names, xs = [], [first]
    while self.peek()[0] == "op" and self.peek()[1] in ops:
      names.append(self.next()[1])
      xs.append(operand())
    if not names:
      return first
    if len(names) == 1:
      return ("bin", names[0], xs[0], xs[1])
    return ("cmp", names, xs)

  def left(self, ops, operand):                       # left-associative binary level
    l = operand()
    while self.peek()[0] == "op" and self.peek()[1] in ops:
      op = self.next()[1]
      l = ("bin", op, l, operand())
    return l

  def eq(self):
    return self.chain(("==", "!="), self.cmp)

  def cmp(self):
    return self.chain(("<", "<=", ">", ">="), self.bor)

  def bor(self):
    return self.left(("|",), self.bxor)

  def bxor(self):
    return self.left(("~",), self.band)

  def band(self):
    return self.left(("&",), self.shift)

  def shift(self):
    return self.left(SHIFT_OPS, self.add)

  def add(self):
    return self.left(("+", "-"), self.mul)

  def mul(self):
    return self.left(("*", "/", "%", "\\"), self.power)

  def power(self):                                    # a^b^c = a^(b^c); unary operators bind tighter: -2^2 = (-2)^2
    e = self.unary()
    if self.is_("^"):
      self.next()
      return ("bin", "^", e, self.power())
    return e

  def unary(self):
    if self.accept("-"):
      if self.peek()[0] == "num":                 # fold -5 (also -9223372036854775808)
        n = -self.next()[1]
        if n < INT_MIN:
          self.err("integer literal too large")
        return ("num", n)
      if self.peek()[0] == "flt":                     # fold -1.5
        return ("flt", -self.next()[1])
      return ("neg", self.unary())
    if self.accept("!"):
      return ("not", self.unary())
    if self.accept("~"):
      return ("bnot", self.unary())
    return self.postfix()

  def postfix(self):                                  # calls:  f(x)  f(x)(y)  (\\a: =a)(1)
    e = self.primary()
    while self.is_("("):
      line = self.next()[2]
      self.ctx.append("(")
      args = []
      if not self.accept(")"):
        while True:
          args.append(self.expr())
          if not self.accept(","):
            break
        self.expect(")")
      self.ctx.pop()
      if len(args) > MAX_PARAMS:
        raise CompileError(f"line {line}: too many arguments (at most {MAX_PARAMS})")
      e = ("call", e, args, line)
    return e

  def primary(self):
    tok = self.next()
    k, v, line = tok
    if k == "num":
      if v > INT_MAX:
        raise CompileError(f"line {line}: integer literal too large")
      return ("num", v)
    if k == "flt":
      return ("flt", v)
    if k == "hex":
      return ("num", v)
    if k == "id":
      return ("var", v, line, None)
    if k == "op" and v in ("^", "@"):
      k2, name, _ = self.next()
      if k2 != "id":
        raise CompileError(f"line {line}: expected a variable name after '{v}'")
      self.use_marked(name, v, line)
      return ("var", name, line, v)
    if (k == "kw" and v == "function") or (k == "op" and v == "\\"):
      return ("fnlit", self.parse_function(None, line, literal=True))
    if k == "str":
      raise CompileError(f"line {line}: a string can only be printed (it is not a value)")
    if k == "op" and v == "(":
      self.ctx.append("(")
      e = self.expr()
      self.expect(")")
      self.ctx.pop()
      return e
    raise CompileError(f"line {line}: unexpected {describe(tok)} in expression")


# ----------------------------------------------------------------------------
# Name resolution (shared by the type checker and the code generator)
# ----------------------------------------------------------------------------
class Resolver:
  g = None                                # the global Scope

  def err(self, line, msg):
    raise CompileError(f"line {line}: {msg}")

  def find_enclosing(self, name, sc):
    """innermost enclosing *function* (not the global scope) that owns local `name`"""
    e = sc.parent
    while e is not None and e.parent is not None:
      if name in e.globals_decl:
        return None
      if name in e.slots:
        return e
      e = e.parent
    return None

  def lookup(self, name, sc, line, mode=None):
    """-> ("g", name) | ("l", scope, name) own local | ("f", owner, name) variable of an enclosing function"""
    if mode == "^" or (mode is None and sc.parent is not None and name in sc.globals_decl):
      if name not in self.g.slots:
        self.err(line, f"undefined global variable '{name}'")
      return ("g", name)
    if mode == "@" or (mode is None and name in sc.nonlocal_decl):
      e = self.find_enclosing(name, sc)
      if e is None:
        self.err(line, f"'@{name}': no variable '{name}' in an enclosing function")
      return ("f", e, name)
    if sc.parent is None:
      if name not in sc.slots:
        self.err(line, f"undefined variable '{name}'")
      return ("g", name)
    if name in sc.slots:
      return ("l", sc, name)
    e = self.find_enclosing(name, sc)
    if e is not None:
      return ("f", e, name)
    if name in self.g.slots:
      return ("g", name)
    self.err(line, f"undefined variable '{name}'")


# ----------------------------------------------------------------------------
# Static types: int, float and functions.  Every variable, parameter and function result gets a type variable;
# types are found by unification (no annotations needed). A variable keeps the type of its first value (no
# implicit conversion on assignment, in calls or in `return`); a parameter takes its type from the way it is
# used and from the calls of the function.
# Inside operators int and float mix: `+ - * / % ^` give float if either side is float (a number is converted
# to float), comparisons convert both sides to float. As the types of operands may only be known later (a
# parameter, for instance), such operators are kept as constraints and solved after the whole program has been
# seen (Checker.solve); what is still unknown at the end becomes int.
# ----------------------------------------------------------------------------
class Ty:
  def __init__(self, kind, params=None, ret=None):
    self.kind, self.params, self.ret, self.ref = kind, params, ret, None


INT = Ty("int")
FLOAT = Ty("float")
ARITH_OPS = ("+", "-", "*", "%", "^")      # float if either side is float (`/` is always float, `\\` always int)


def prune(t):
  while t.kind == "var" and t.ref is not None:
    t = t.ref
  return t


def show(t, seen=()):
  t = prune(t)
  if t.kind in ("int", "float"):
    return t.kind
  if t.kind == "var":
    return "?"
  if id(t) in seen:
    return "..."                        # a function type that contains itself
  seen = seen + (id(t),)
  s = "fn(" + ", ".join(show(p, seen) for p in t.params) + ")"
  r = prune(t.ret)
  return s if r.kind == "var" else s + " -> " + show(r, seen)


class Mismatch(Exception):
  pass


def unify_raw(a, b, seen=None):
  """Types may be recursive (fn(T) -> T with T the same type), so pairs already being compared are skipped."""
  a, b = prune(a), prune(b)
  if a is b:
    return
  if a.kind == "var" or b.kind == "var":
    v, o = (a, b) if a.kind == "var" else (b, a)
    v.ref = o
  elif a.kind != b.kind or (a.kind == "fn" and len(a.params) != len(b.params)):
    raise Mismatch()
  elif a.kind == "fn":
    seen = set() if seen is None else seen
    if (id(a), id(b)) in seen:
      return
    seen.add((id(a), id(b)))
    for x, y in zip(a.params, b.params):
      unify_raw(x, y, seen)
    unify_raw(a.ret, b.ret, seen)


class Checker(Resolver):
  def __init__(self, gscope):
    self.g = gscope
    self.env = {}                       # variable key -> Ty
    self.fns = []                       # functions whose body is being checked
    self.types = {}                     # id(expression node) -> Ty   (the code generator reads this)
    self.pending = []                   # constraints whose operand types are not known yet

  def unify(self, expected, found, line, what):
    try:
      unify_raw(expected, found)
    except Mismatch:
      self.err(line, f"type mismatch {what}: expected {show(expected)}, found {show(found)}")

  def key(self, r):
    return ("g", r[1]) if r[0] == "g" else (r[1], r[2])

  def var_ty(self, name, sc, line, mode):
    k = self.key(self.lookup(name, sc, line, mode))
    if k not in self.env:
      self.env[k] = Ty("var")
    return self.env[k]

  def fn_ty(self, f):
    if f.ty is None:
      ps = [Ty("var") for _ in f.params]
      f.ty = Ty("fn", ps, Ty("var"))
      for p, t in zip(f.params, ps):
        self.env[(f, p)] = t
    return f.ty

  def check_body(self, f):
    if f.checked:
      return
    f.checked = True
    self.fn_ty(f)
    self.fns.append(f)
    self.stmts(f.body, f)
    self.fns.pop()

  def run(self, ast):
    self.stmts(ast, self.g)
    self.finish()

  # -- numeric constraints
  def need_num(self, t, line, what):
    """t must be a number (int or float)"""
    t = prune(t)
    if t.kind == "fn":
      self.err(line, f"type mismatch {what}: expected a number, found {show(t)}")
    if t.kind == "var":
      self.pending.append(("num", t, line, what))

  def constrain(self, c):
    if not self.step(c):
      self.pending.append(c)

  def result(self, res, t, line, op):
    try:
      unify_raw(res, t)
    except Mismatch:
      self.err(line, f"type mismatch in '{op}': the result is {t.kind}, expected {show(res)}")

  def step(self, c):
    """try to settle one constraint; False if its operand types are still unknown"""
    kind = c[0]
    if kind == "num":
      t = prune(c[1])
      if t.kind == "var":
        return False
      self.need_num(t, c[2], c[3])
      return True
    if kind == "arith":                 # result = float if one side is float, else int
      _, res, a, b, line, op = c
      a, b = prune(a), prune(b)
      if a.kind == "fn":
        self.err(line, f"type mismatch in left operand of '{op}': expected a number, found {show(a)}")
      if b.kind == "fn":
        self.err(line, f"type mismatch in right operand of '{op}': expected a number, found {show(b)}")
      if a.kind == "float" or b.kind == "float":
        self.result(res, FLOAT, line, op)
        for t in (a, b):
          if t.kind == "var":
            self.pending.append(("num", t, line, f"in operand of '{op}'"))
        return True
      if a.kind == "int" and b.kind == "int":
        self.result(res, INT, line, op)
        return True
      return False
    if kind == "eq":                    # two numbers (any mix) or two functions of the same type
      _, a, b, line, what = c
      a, b = prune(a), prune(b)
      if a.kind == "fn" or b.kind == "fn":
        self.unify(a, b, line, what)
        return True
      if a.kind != "var" and b.kind != "var":
        return True
      if a.kind == "var" and b.kind == "var":
        return False
      self.pending.append(("num", a if a.kind == "var" else b, line, what))
      return True
    if kind == "cond":                  # c ? a ! b : numbers mix like in an operator, functions must agree
      _, res, a, b, line, what = c
      a, b = prune(a), prune(b)
      if a.kind == "fn" or b.kind == "fn":
        self.unify(a, b, line, what)
        self.unify(res, a, line, what)
        return True
      if a.kind == "float" or b.kind == "float":
        self.unify(res, FLOAT, line, what)
        for t in (a, b):
          if t.kind == "var":
            self.pending.append(("num", t, line, what))
        return True
      if a.kind == "int" and b.kind == "int":
        self.unify(res, INT, line, what)
        return True
      return False
    raise AssertionError(kind)

  def solve(self):
    progress = True
    while progress and self.pending:
      progress = False
      batch, self.pending = self.pending, []
      for c in batch:
        if self.step(c):
          progress = True
        else:
          self.pending.append(c)

  def finish(self):
    """after the whole program: types that were never determined are int"""
    while True:
      self.solve()
      if not self.pending:
        return
      for c in self.pending:
        ops = c[1:2] if c[0] == "num" else c[1:4] if c[0] in ("arith", "cond") else c[1:3]
        for t in ops:
          t = prune(t)
          if t.kind == "var":
            unify_raw(t, INT)

  # -- statements
  def stmts(self, lst, sc):
    for s in lst:
      self.stmt(s, sc)

  def stmt(self, s, sc):
    k = s[0]
    if k == "assign":
      t = self.expr(s[2], sc, s[3])
      self.unify(self.var_ty(s[1], sc, s[3], s[4]), t, s[3], f"in assignment to '{s[1]}'")
    elif k == "print":
      for kind, v in s[1]:
        if kind == "expr":
          self.need_num(self.expr(v, sc, s[2]), s[2], "in 'print' (only numbers can be printed)")
    elif k == "if":
      self.need_num(self.expr(s[1], sc, s[4]), s[4], "in the condition of 'if'")
      self.stmts(s[2], sc)
      self.stmts(s[3], sc)
    elif k == "while":
      self.need_num(self.expr(s[1], sc, s[3]), s[3], "in the condition of 'while'")
      self.stmts(s[2], sc)
    elif k == "exit":
      self.unify(INT, self.expr(s[1], sc, s[2]), s[2], "in 'exit'")
    elif k == "exprstmt":
      self.expr(s[1], sc, s[2])
    elif k == "block":
      self.stmts(s[1], sc)
    elif k == "return":
      if s[1] is not None:
        t = self.expr(s[1], sc, s[2])
        self.unify(self.fn_ty(self.fns[-1]).ret, t, s[2], "in 'return' (all returns of a function must agree)")
    elif k == "fn":
      f = s[1]
      self.unify(self.var_ty(f.name, sc, f.line, None), self.fn_ty(f), f.line, f"in definition of '{f.name}'")
      self.check_body(f)

  # -- expressions
  def operand(self, e, sc, line, what):
    self.unify(INT, self.expr(e, sc, line), line, f"in {what}")

  def expr(self, e, sc, line):
    t = self.expr_(e, sc, line)
    self.types[id(e)] = t               # the code generator needs the type of every expression
    return t

  def expr_(self, e, sc, line):
    k = e[0]
    if k == "num":
      return INT
    if k == "flt":
      return FLOAT
    if k == "var":
      return self.var_ty(e[1], sc, e[2], e[3])
    if k == "fnlit":
      self.check_body(e[1])
      return self.fn_ty(e[1])
    if k == "call":
      _, callee, args, cl = e
      ct = prune(self.expr(callee, sc, cl))
      ats = [self.expr(a, sc, cl) for a in args]
      if ct.kind in ("int", "float"):
        self.err(cl, f"type mismatch in call: {'an' if ct.kind == 'int' else 'a'} {ct.kind} is not a function")
      if ct.kind == "fn":
        if len(ct.params) != len(ats):
          self.err(cl, f"wrong number of arguments: the function takes {len(ct.params)}, "
                       f"called with {len(ats)}")
        for i, (p, a) in enumerate(zip(ct.params, ats), 1):
          self.unify(p, a, cl, f"in argument {i} of the call")
        return ct.ret
      r = Ty("var")
      self.unify(ct, Ty("fn", ats, r), cl, "in call")
      return r
    if k == "bin":
      op = e[1]
      if op in ("/", "\\"):                 # float division / integer division: numbers in, float / int out
        self.need_num(self.expr(e[2], sc, line), line, f"in left operand of '{op}'")
        self.need_num(self.expr(e[3], sc, line), line, f"in right operand of '{op}'")
        return FLOAT if op == "/" else INT
      if op in ARITH_OPS:
        ta, tb = self.expr(e[2], sc, line), self.expr(e[3], sc, line)
        res = Ty("var")
        self.constrain(("arith", res, ta, tb, line, op))
        return res
      if op in ("==", "!="):
        ta, tb = self.expr(e[2], sc, line), self.expr(e[3], sc, line)
        self.constrain(("eq", ta, tb, line, f"in '{op}' (both sides must have the same type, or both be numbers)"))
      elif op in ("<", "<=", ">", ">="):
        self.need_num(self.expr(e[2], sc, line), line, f"in left operand of '{op}'")
        self.need_num(self.expr(e[3], sc, line), line, f"in right operand of '{op}'")
      else:                             # bitwise operators and shifts: integers only
        self.operand(e[2], sc, line, f"left operand of '{op}'")
        self.operand(e[3], sc, line, f"right operand of '{op}'")
      return INT
    if k == "cmp":
      ops, xs = e[1], e[2]
      ts = [self.expr(x, sc, line) for x in xs]
      for op, a, b in zip(ops, ts, ts[1:]):
        if op in ("==", "!="):
          self.constrain(("eq", a, b, line, f"in '{op}' (both sides must have the same type, or both be numbers)"))
        else:
          self.need_num(a, line, f"in operand of '{op}'")
          self.need_num(b, line, f"in operand of '{op}'")
      return INT
    if k == "cond":
      self.need_num(self.expr(e[1], sc, line), line, "in the condition of '?'")
      ta, tb = self.expr(e[2], sc, line), self.expr(e[3], sc, line)
      res = Ty("var")
      self.constrain(("cond", res, ta, tb, line, "in '?!' (both branches must have the same type, or both be numbers)"))
      return res
    if k in ("and", "or"):
      sym = '&&' if k == 'and' else '||'
      self.need_num(self.expr(e[1], sc, line), line, f"in left operand of '{sym}'")
      self.need_num(self.expr(e[2], sc, line), line, f"in right operand of '{sym}'")
      return INT
    if k == "neg":
      t = self.expr(e[1], sc, line)
      self.need_num(t, line, "in operand of '-'")
      return t
    if k == "not":
      self.need_num(self.expr(e[1], sc, line), line, "in operand of '!'")
      return INT
    if k == "bnot":
      self.operand(e[1], sc, line, "operand of '~'")
      return INT
    raise AssertionError(k)


# ----------------------------------------------------------------------------
# x86-64 code generator
# ----------------------------------------------------------------------------
class Asm:
  def __init__(self):
    self.code = bytearray()
    self.labels = {}
    self.refs = []        # (pos, label)   rel32 to a label
    self.fix = []         # (pos, symbol)  rip-relative rel32 to an IAT/data symbol
    self.static_closures = []   # data symbols (16 bytes each) for closures without captured variables
    self.n = 0

  def emit(self, *parts):
    for p in parts:
      if isinstance(p, int):
        self.code.append(p)
      else:
        self.code.extend(p)

  def new_label(self, hint="L"):
    self.n += 1
    return f"{hint}{self.n}"

  def label(self, name):
    assert name not in self.labels, name
    self.labels[name] = len(self.code)

  def _ref(self, label):
    self.refs.append((len(self.code), label))
    self.code += b"\0\0\0\0"

  def jmp(self, label):
    self.emit(0xE9)
    self._ref(label)

  def jcc(self, cc, label):         # cc: 4=z 5=nz 9=ns ...
    self.emit(0x0F, 0x80 + cc)
    self._ref(label)

  def call(self, label):
    self.emit(0xE8)
    self._ref(label)

  def rip(self, opcode, sym):       # instruction whose last 4 bytes are a rip-relative disp
    self.emit(opcode)
    self.fix.append((len(self.code), sym))
    self.code += b"\0\0\0\0"

  def resolve_labels(self):
    for pos, label in self.refs:
      rel = self.labels[label] - (pos + 4)
      self.code[pos:pos + 4] = struct.pack("<i", rel)


FAIL_CC = {"==": 5, "!=": 4, "<": 0x0D, "<=": 0x0F, ">": 0x0E, ">=": 0x0C}   # jump if the comparison is false
CMP_SETCC = {"==": 0x94, "!=": 0x95, "<": 0x9C, "<=": 0x9E, ">": 0x9F, ">=": 0x9D}


# ---- BEGIN FLOAT_RT (generated by tools/build_float_rt.py from tools/float_rt.asm; do not edit by hand)
FLOAT_RT = {
  "rt_fmod": bytes.fromhex(
    "66480f7ec666480f7ecf4989f249c1ea3f4989f049c1e8344981e0ff0700004989f949c1e9344981e1ff0700004981f8ff07"
    "00000f84210000004889f248d1e24989fb49d1e34c39da0f871c0000000f8505000000e93f010000c348b8000000000000f8"
    "7f66480f6ec0c34d85c00f852d0000004889f248c1e20c4885d20f880b00000049ffc848d1e2e9ecffffff48c7c101000000"
    "4c29c148d3e6e91a00000048b8ffffffffffff0f004821c648b800000000000010004809c64d85c90f852d0000004889fa48"
    "c1e20c4885d20f880b00000049ffc948d1e2e9ecffffff48c7c1010000004c29c948d3e7e91a00000048b8ffffffffffff0f"
    "004821c748b800000000000010004809c74d39c80f8e200000004889f24829fa0f88090000000f84730000004889d648d1e6"
    "49ffc8e9d7ffffff4889f24829fa0f88090000000f84530000004889d648b800000000000010004839c60f830b00000048d1"
    "e649ffc8e9ecffffff4d85c00f8e0f0000004829c649c1e0344c09c6e90d00000048c7c1010000004c29c148d3ee49c1e23f"
    "4c09d666480f6ec6c34c89d048c1e03f66480f6ec0c3"
  ),
  "rt_fpow": bytes.fromhex(
    "31d266490f7ec166480f7ec84889c148d1e10f851000000048b8000000000000f03f66480f6ec0c3f2480f2cc9f2480f2ad1"
    "660f2ed10f85840000000f8a7e0000004989c84885c90f890300000048f7d94883ec1866c74424107f03d96c2410f20f1104"
    "24d9e8dd04244885c90f8415000000f6c1010f8402000000dcc9d8c848d1e9e9e2ffffffddd84d85c00f891e0000004c89c8"
    "48d1e00f850c000000ddd84883c418ba01000000c3d9e8d9c9def9dd1c24f20f1004244883c41831d2c34c89c84889c148d1"
    "e10f844b0000004885c00f885b0000004883ec1866c74424107f03d96c2410f20f110c24dd0424f20f110424dd0424d9f1d9"
    "c0d9fcdce9d9c9d9f0d9e8dec1d9fdddd9dd1c24f20f1004244883c41831d2c366480f7ec84885c00f8805000000660f57c0"
    "c3ba01000000c3ba02000000c3"
  ),
  "rt_fmt_float": bytes.fromhex(
    "4883ec404989d74889d74889c34889d948d1e148ba000000000000e0ff4839d10f87480200004885db0f8906000000c6072d"
    "48ffc7480fbaf33f48b9000000000000f07f4839cb0f84300200004885db0f843602000066c74424287f03d96c242848891c"
    "2448c74424080a0000004889d848c1e834482dff0300004869c0d104000048c1f80c4989c448c7c10e0000004c29e14989c8"
    "4885c90f890300000048f7d9dd0424d9e8df6c24084885c90f8415000000f6c1010f8402000000dcc9d8c848d1e9e9e2ffff"
    "ffddd84d85c00f8807000000dec9e902000000def9d9fcdf7c24104c8b6c241048b80080c6a47e8d03004939c50f8c080000"
    "0049ffc4e986ffffff48b800407a10f35a00004939c50f8d0800000049ffcce96bffffff49c7c60f00000048c7c10a000000"
    "4983fe010f8e1c0000004c89e831d248f7f14885d20f850b0000004989c549ffcee9daffffff488d7424184c89e84d89f031"
    "d248f7f180c23049ffc8428814064d85c00f85e8ffffff4983fcfc0f8c760000004983fc0e0f8f6c0000004d85e40f884300"
    "00004d8d4c24014d39ce0f8e180000004c89c9f3a4c6072e48ffc74c89f14c29c9f3a4e9de0000004c89f1f3a44c89c94c29"
    "f1b030f3aa66c7072e304883c702e9c100000066c707302e4883c7024c89e148f7d948ffc9b030f3aa4c89f1f3a4e9a10000"
    "00a44983fe010f8e0c000000c6072e48ffc7498d4efff3a4c6076548ffc74c89e04885c00f8808000000c6072be906000000"
    "c6072d48f7d848ffc748c7c16400000031d248f7f14885c00f84070000000430880748ffc74889d048c7c10a00000031d248"
    "f7f10430880748ffc780c230881748ffc7e928000000c7076e616e004883c703e919000000c707696e66004883c703e90a00"
    "0000c707302e30004883c7034889f84c29f84883c440c3"
  ),
}
# ---- END FLOAT_RT


class CodeGen(Resolver):
  def __init__(self, gscope, strings, fn_globals, types):
    self.types = types                  # id(expression node) -> Ty, from the Checker
    self.a = Asm()
    self.g = gscope
    self.scope = gscope
    self.strings = strings
    self.fn_globals = fn_globals
    self.loops = []
    self.queue = []                     # functions still to be generated

  # -- analysis: which variables are captured by nested functions?
  def capture(self, name, sc, line, mode=None):
    r = self.lookup(name, sc, line, mode)
    if r[0] == "f":
      owner = r[1]
      owner.boxed.add(name)
      x = sc
      while x is not owner:                           # every function in between passes the box on
        x.free.setdefault((owner, name), len(x.free))
        x = x.parent

  def analyze(self, stmts, sc):
    for s in stmts:
      k = s[0]
      if k == "assign":
        self.a_expr(s[2], sc)
        self.capture(s[1], sc, s[3], s[4])
      elif k == "print":
        for kind, v in s[1]:
          if kind == "expr":
            self.a_expr(v, sc)
      elif k == "if":
        self.a_expr(s[1], sc)
        self.analyze(s[2], sc)
        self.analyze(s[3], sc)
      elif k == "while":
        self.a_expr(s[1], sc)
        self.analyze(s[2], sc)
      elif k in ("exit", "exprstmt"):
        self.a_expr(s[1], sc)
      elif k == "return":
        if s[1] is not None:
          self.a_expr(s[1], sc)
      elif k == "block":
        self.analyze(s[1], sc)
      elif k == "fn":
        self.analyze(s[1].body, s[1])

  def a_expr(self, e, sc):
    k = e[0]
    if k == "var":
      self.capture(e[1], sc, e[2], e[3])
    elif k == "call":
      self.a_expr(e[1], sc)
      for arg in e[2]:
        self.a_expr(arg, sc)
    elif k == "bin":
      self.a_expr(e[2], sc)
      self.a_expr(e[3], sc)
    elif k in ("and", "or"):
      self.a_expr(e[1], sc)
      self.a_expr(e[2], sc)
    elif k == "cmp":
      for x in e[2]:
        self.a_expr(x, sc)
    elif k == "cond":
      for x in e[1:]:
        self.a_expr(x, sc)
    elif k in ("neg", "not", "bnot"):
      self.a_expr(e[1], sc)
    elif k == "fnlit":
      self.analyze(e[1].body, e[1])

  # -- variable access
  def check_defined(self, name, line):
    sc = self.scope
    if name in sc.defined or (sc.parent is None and name in self.fn_globals):
      return
    if sc.parent is None:
      self.err(line, f"variable '{name}' used before assignment")
    self.err(line, f"variable '{name}' is local to function '{sc.name}' and used before "
                   f"assignment (use '^{name}' to refer to the global one)")

  def free_box(self, owner, name):                         # rdx = box pointer of a captured variable
    a, i = self.a, self.scope.free[(owner, name)]
    a.emit(0x48, 0x8B, 0x55, 0x10)                       # mov rdx,[rbp+16]   (closure)
    a.emit(0x48, 0x8B, 0x92, struct.pack("<i", 16 + 8 * i))   # mov rdx,[rdx+16+8i]

  def var_load(self, name, line, mode=None):
    a, sc = self.a, self.scope
    r = self.lookup(name, sc, line, mode)
    if r[0] == "g":
      if sc.parent is None:
        self.check_defined(name, line)
      a.rip([0x48, 0x8B, 0x05], "var:" + name)         # mov rax,[var]
    elif r[0] == "l":
      self.check_defined(name, line)
      off = sc.slots[name]
      if name in sc.boxed:
        a.emit(0x48, 0x8B, 0x95, struct.pack("<i", off))   # mov rdx,[rbp+off]  (box)
        a.emit(0x48, 0x8B, 0x02)                           # mov rax,[rdx]
      else:
        a.emit(0x48, 0x8B, 0x85, struct.pack("<i", off))   # mov rax,[rbp+off]
    else:
      self.free_box(r[1], name)
      a.emit(0x48, 0x8B, 0x02)                         # mov rax,[rdx]

  def var_store(self, name, line, mode=None):              # value in rax
    a, sc = self.a, self.scope
    r = self.lookup(name, sc, line, mode)
    if r[0] == "g":
      a.rip([0x48, 0x89, 0x05], "var:" + name)         # mov [var],rax
    elif r[0] == "l":
      off = sc.slots[name]
      if name in sc.boxed:
        a.emit(0x48, 0x8B, 0x95, struct.pack("<i", off))   # mov rdx,[rbp+off]
        a.emit(0x48, 0x89, 0x02)                           # mov [rdx],rax
      else:
        a.emit(0x48, 0x89, 0x85, struct.pack("<i", off))   # mov [rbp+off],rax
    else:
      self.free_box(r[1], name)
      a.emit(0x48, 0x89, 0x02)                         # mov [rdx],rax
    sc.defined.add(name)

  # -- closures and functions
  def make_closure(self, f):
    """rax = pointer to a closure object [code, nparams, captured box pointers...]"""
    a, P = self.a, self.scope
    if not f.queued:
      f.queued = True
      self.queue.append(f)
    n = len(f.params)
    a.emit(0x48, 0x8D, 0x05)                             # lea rax,[rip+function]
    a._ref(f.label)
    if not f.free:                                       # nothing captured: one static object
      sym = "clo:" + f.label
      if sym not in a.static_closures:
        a.static_closures.append(sym)
      a.rip([0x48, 0x8D, 0x15], sym)                   # lea rdx,[closure]
      a.emit(0x48, 0x89, 0x02)                         # mov [rdx],rax
      a.emit(0x48, 0xC7, 0x42, 0x08, struct.pack("<I", n))   # mov qword [rdx+8],n
      a.emit(0x48, 0x89, 0xD0)                         # mov rax,rdx
      return
    a.emit(0xB9, struct.pack("<I", 16 + 8 * len(f.free)))      # mov ecx,size
    a.call("rt_alloc")                                   # rax = zeroed heap block (clobbers rcx,rdx,...)
    a.emit(0x48, 0x8D, 0x15)                             # lea rdx,[rip+function]
    a._ref(f.label)
    a.emit(0x48, 0x89, 0x10)                             # mov [rax],rdx
    a.emit(0x48, 0xC7, 0x40, 0x08, struct.pack("<I", n))     # mov qword [rax+8],n
    for (owner, name), i in sorted(f.free.items(), key=lambda kv: kv[1]):
      if owner is P:
        a.emit(0x48, 0x8B, 0x95, struct.pack("<i", P.slots[name]))   # mov rdx,[rbp+off] (box)
      else:
        self.free_box(owner, name)                   # box received by P's own closure
      a.emit(0x48, 0x89, 0x90, struct.pack("<i", 16 + 8 * i))   # mov [rax+16+8i],rdx

  def hoist(self, sc):
    """create the closures of all `fn name` definitions of a scope on entry"""
    sc.defined.update(f.name for f in sc.named_fns)
    for f in sc.named_fns:
      self.make_closure(f)
      self.var_store(f.name, 0)

  def epilogue(self):
    n = len(self.scope.params)
    self.a.emit(0x48, 0x89, 0xEC, 0x5D, 0xC2, struct.pack("<H", 8 * (n + 1)))  # leave; ret 8*(n+1)

  def gen_function(self, f):
    a = self.a
    self.scope, self.loops = f, []
    a.label(f.label)
    a.emit(0x55, 0x48, 0x89, 0xE5)                       # push rbp; mov rbp,rsp
    for _ in range(f.nlocals):
      a.emit(0x6A, 0x00)                               # push 0  (zeroed local)
    for name, off in f.slots.items():                    # move captured variables into heap boxes
      if name in f.boxed:
        a.emit(0xB9, struct.pack("<I", 8))
        a.call("rt_alloc")
        if name in f.params:
          a.emit(0x48, 0x8B, 0x95, struct.pack("<i", off))   # mov rdx,[rbp+off]
          a.emit(0x48, 0x89, 0x10)                           # mov [rax],rdx
        a.emit(0x48, 0x89, 0x85, struct.pack("<i", off))       # mov [rbp+off],rax
    self.hoist(f)
    for s in f.body:                                     # the constants of this function are created first
      if s[0] == "assign" and len(s) > 5:
        self.expr(s[2])
        self.var_store(s[1], s[3], s[4])
    self.stmts(f.body)
    a.emit(0x31, 0xC0)                                   # xor eax,eax  (default result 0)
    self.epilogue()

  # -- types in the generated code: values are always 64 bits; a float is the bit pattern of a double
  def tk(self, e):
    """'int', 'float' or 'fn' (a type that was never determined counts as int)"""
    t = prune(self.types.get(id(e), INT))
    return t.kind if t.kind in ("float", "fn") else "int"

  def load_xmm(self, xmm, reg, kind):
    """xmm := the number in the general register reg (0 = rax, 1 = rcx, 2 = rdx); an int is converted to float"""
    modrm = 0xC0 | (xmm << 3) | reg
    if kind == "float":
      self.a.emit(0x66, 0x48, 0x0F, 0x6E, modrm)       # movq xmm,reg
    else:
      self.a.emit(0xF2, 0x48, 0x0F, 0x2A, modrm)       # cvtsi2sd xmm,reg

  def test_rax(self, kind):
    """set ZF when the value in rax is false: 0 (for a float: +0.0 or -0.0)"""
    if kind == "float":
      self.a.emit(0x48, 0x89, 0xC1, 0x48, 0xD1, 0xE1)  # mov rcx,rax; shl rcx,1   (drops the sign bit)
    else:
      self.a.emit(0x48, 0x85, 0xC0)                    # test rax,rax

  def fcmp_false(self, op, lab):
    """xmm0 = left, xmm1 = right: jump to lab if `left op right` is false (a comparison with nan is false, except !=)"""
    a = self.a
    if op in ("<", "<="):
      a.emit(0x66, 0x0F, 0x2E, 0xC8)                   # ucomisd xmm1,xmm0
      a.jcc(6 if op == "<" else 2, lab)                # jbe / jb
    elif op in (">", ">="):
      a.emit(0x66, 0x0F, 0x2E, 0xC1)                   # ucomisd xmm0,xmm1
      a.jcc(6 if op == ">" else 2, lab)
    elif op == "==":
      a.emit(0x66, 0x0F, 0x2E, 0xC1)
      a.jcc(5, lab)                                    # jne
      a.jcc(0xA, lab)                                  # jp  (unordered)
    else:                                              # "!="
      ok = a.new_label("fne_ok")
      a.emit(0x66, 0x0F, 0x2E, 0xC1)
      a.jcc(0xA, ok)                                   # unordered: not equal
      a.jcc(4, lab)                                    # equal: false
      a.label(ok)

  def mov_rax_imm(self, n):
    a = self.a
    if -2 ** 31 <= n < 2 ** 31:
      a.emit(0x48, 0xC7, 0xC0, struct.pack("<i", n))
    else:
      a.emit(0x48, 0xB8, struct.pack("<q", n))

  def expr(self, e):
    a, k = self.a, e[0]
    if k == "num":
      self.mov_rax_imm(e[1])
    elif k == "flt":
      self.mov_rax_imm(struct.unpack("<q", struct.pack("<d", e[1]))[0])
    elif k == "var":
      self.var_load(e[1], e[2], e[3])
    elif k == "fnlit":
      self.make_closure(e[1])
    elif k == "call":
      _, callee, args, line = e
      for arg in args:
        self.expr(arg)
        a.emit(0x50)                                 # push rax
      self.expr(callee)                                # rax = closure pointer
      a.emit(0x48, 0x85, 0xC0)                         # test rax,rax
      a.jcc(4, "rt_notfn")
      a.emit(0x50)                                     # push rax  (hidden last argument)
      a.emit(0xFF, 0x10)                               # call [rax]
    elif k == "neg":
      self.expr(e[1])
      if self.tk(e[1]) == "float":
        a.emit(0x48, 0x0F, 0xBA, 0xF8, 0x3F)           # btc rax,63   (flip the sign bit)
      else:
        a.emit(0x48, 0xF7, 0xD8)                       # neg rax
    elif k == "bnot":
      self.expr(e[1])
      a.emit(0x48, 0xF7, 0xD0)                         # not rax
    elif k == "cmp":                                     # chained comparison: a < b <= c
      ops, xs = e[1], e[2]
      tys = [self.tk(x) for x in xs]
      lf, le = a.new_label("ch_f"), a.new_label("ch_e")
      self.expr(xs[0])
      a.emit(0x50)                                     # push rax  (previous operand)
      for i, op in enumerate(ops):
        self.expr(xs[i + 1])                         # each operand is evaluated once
        a.emit(0x48, 0x89, 0xC2)                     # mov rdx,rax
        a.emit(0x48, 0x8B, 0x0C, 0x24)               # mov rcx,[rsp]
        if "float" in (tys[i], tys[i + 1]):
          self.load_xmm(0, 1, tys[i])                  # previous operand (rcx) -> xmm0
          self.load_xmm(1, 2, tys[i + 1])              # this operand (rdx) -> xmm1
          self.fcmp_false(op, lf)
        else:
          a.emit(0x48, 0x39, 0xD1)                   # cmp rcx,rdx
          a.jcc(FAIL_CC[op], lf)                     # stop at the first false link
        if i < len(ops) - 1:
          a.emit(0x48, 0x89, 0x14, 0x24)           # mov [rsp],rdx
      a.emit(0xB8, 1, 0, 0, 0)                         # mov eax,1
      a.jmp(le)
      a.label(lf)
      a.emit(0x31, 0xC0)                               # xor eax,eax
      a.label(le)
      a.emit(0x48, 0x83, 0xC4, 0x08)                   # add rsp,8
    elif k == "cond":                                    # c ? a ! b
      lel, len_ = a.new_label("cd_else"), a.new_label("cd_end")
      tres = self.tk(e)
      self.expr(e[1])
      self.test_rax(self.tk(e[1]))
      a.jcc(4, lel)
      for branch, lab in ((e[2], len_), (e[3], None)):
        self.expr(branch)
        if tres == "float" and self.tk(branch) == "int":
          a.emit(0xF2, 0x48, 0x0F, 0x2A, 0xC0)         # cvtsi2sd xmm0,rax   (an int branch becomes float)
          a.emit(0x66, 0x48, 0x0F, 0x7E, 0xC0)         # movq rax,xmm0
        if lab is not None:
          a.jmp(lab)
          a.label(lel)
      a.label(len_)
    elif k == "not":
      self.expr(e[1])
      self.test_rax(self.tk(e[1]))
      a.emit(0x0F, 0x94, 0xC0, 0x0F, 0xB6, 0xC0)       # sete al; movzx eax,al
    elif k == "and":
      lf, le = a.new_label("and_f"), a.new_label("and_e")
      self.expr(e[1])
      self.test_rax(self.tk(e[1]))
      a.jcc(4, lf)
      self.expr(e[2])
      self.test_rax(self.tk(e[2]))
      a.emit(0x0F, 0x95, 0xC0, 0x0F, 0xB6, 0xC0)       # setne al; movzx eax,al
      a.jmp(le)
      a.label(lf)
      a.emit(0x31, 0xC0)                               # xor eax,eax
      a.label(le)
    elif k == "or":
      lt, le = a.new_label("or_t"), a.new_label("or_e")
      self.expr(e[1])
      self.test_rax(self.tk(e[1]))
      a.jcc(5, lt)
      self.expr(e[2])
      self.test_rax(self.tk(e[2]))
      a.emit(0x0F, 0x95, 0xC0, 0x0F, 0xB6, 0xC0)
      a.jmp(le)
      a.label(lt)
      a.emit(0xB8, 1, 0, 0, 0)                         # mov eax,1
      a.label(le)
    elif k == "bin":
      op = e[1]
      self.expr(e[2])
      a.emit(0x50)                                     # push rax
      self.expr(e[3])
      a.emit(0x48, 0x89, 0xC1)                         # mov rcx,rax
      a.emit(0x58)                                     # pop rax
      tl, tr = self.tk(e[2]), self.tk(e[3])
      if (op in ARITH_OPS or op == "/") and self.tk(e) == "float":   # float arithmetic; an int operand is converted
        self.load_xmm(0, 0, tl)                      # left  (rax) -> xmm0
        self.load_xmm(1, 1, tr)                      # right (rcx) -> xmm1
        if op in ("+", "-", "*"):
          a.emit(0xF2, 0x0F, {"+": 0x58, "-": 0x5C, "*": 0x59}[op], 0xC1)   # addsd / subsd / mulsd xmm0,xmm1
        elif op in ("/", "%"):
          if tr == "float":
            a.emit(0x48, 0x89, 0xCA, 0x48, 0xD1, 0xE2)   # mov rdx,rcx; shl rdx,1   (+0.0 and -0.0)
          else:
            a.emit(0x48, 0x85, 0xC9)                 # test rcx,rcx
          a.jcc(4, "rt_divzero")
          if op == "/":
            a.emit(0xF2, 0x0F, 0x5E, 0xC1)           # divsd xmm0,xmm1
          else:
            a.call("rt_fmod")
        else:                                        # power
          ok = a.new_label("fp_ok")
          a.call("rt_fpow")
          a.emit(0x85, 0xD2)                         # test edx,edx
          a.jcc(4, ok)
          a.emit(0x83, 0xFA, 0x01)                   # cmp edx,1
          a.jcc(4, "rt_divzero")
          a.jmp("rt_badpow")
          a.label(ok)
        a.emit(0x66, 0x48, 0x0F, 0x7E, 0xC0)         # movq rax,xmm0
      elif op == "\\" and "float" in (tl, tr):         # integer division of floats: trunc((a - fmod(a, b)) / b)
        self.load_xmm(0, 0, tl)
        self.load_xmm(1, 1, tr)
        if tr == "float":
          a.emit(0x48, 0x89, 0xCA, 0x48, 0xD1, 0xE2)     # mov rdx,rcx; shl rdx,1   (+0.0 and -0.0)
        else:
          a.emit(0x48, 0x85, 0xC9)                     # test rcx,rcx
        a.jcc(4, "rt_divzero")
        a.emit(0x66, 0x0F, 0x28, 0xD0)                 # movapd xmm2,xmm0
        a.call("rt_fmod")                              # xmm0 = fmod(a, b); xmm1 and xmm2 are kept
        a.emit(0xF2, 0x0F, 0x5C, 0xD0)                 # subsd xmm2,xmm0
        a.emit(0xF2, 0x0F, 0x5E, 0xD1)                 # divsd xmm2,xmm1
        a.emit(0xF2, 0x48, 0x0F, 0x2C, 0xC2)           # cvttsd2si rax,xmm2
      elif op in CMP_SETCC and "float" in (tl, tr):    # comparison with a float: both sides as float, exactly
        lf, le = a.new_label("fc_f"), a.new_label("fc_e")
        self.load_xmm(0, 0, tl)
        self.load_xmm(1, 1, tr)
        self.fcmp_false(op, lf)
        a.emit(0xB8, 1, 0, 0, 0)                     # mov eax,1
        a.jmp(le)
        a.label(lf)
        a.emit(0x31, 0xC0)                           # xor eax,eax
        a.label(le)
      elif op == "+":
        a.emit(0x48, 0x01, 0xC8)                     # add rax,rcx
      elif op == "-":
        a.emit(0x48, 0x29, 0xC8)                     # sub rax,rcx
      elif op == "*":
        a.emit(0x48, 0x0F, 0xAF, 0xC1)               # imul rax,rcx
      elif op == "&":
        a.emit(0x48, 0x21, 0xC8)                     # and rax,rcx
      elif op == "|":
        a.emit(0x48, 0x09, 0xC8)                     # or rax,rcx
      elif op == "~":
        a.emit(0x48, 0x31, 0xC8)                     # xor rax,rcx
      elif op == "^":                                  # power by repeated squaring
        lp, sk, dn = a.new_label("pw_l"), a.new_label("pw_s"), a.new_label("pw_d")
        a.emit(0x48, 0x85, 0xC9)                     # test rcx,rcx
        a.jcc(8, "rt_negexp")                        # js
        a.emit(0x48, 0xC7, 0xC2, 1, 0, 0, 0)         # mov rdx,1   (result)
        a.label(lp)
        a.emit(0x48, 0x85, 0xC9)
        a.jcc(4, dn)                                 # exponent exhausted
        a.emit(0xF6, 0xC1, 0x01)                     # test cl,1
        a.jcc(4, sk)
        a.emit(0x48, 0x0F, 0xAF, 0xD0)               # imul rdx,rax
        a.label(sk)
        a.emit(0x48, 0x0F, 0xAF, 0xC0)               # imul rax,rax
        a.emit(0x48, 0xD1, 0xE9)                     # shr rcx,1
        a.jmp(lp)
        a.label(dn)
        a.emit(0x48, 0x89, 0xD0)                     # mov rax,rdx
      elif op in ("<<", ">>", "+>"):                   # shifts; a negative count shifts the other way
        big, neg, nbig, end = (a.new_label(n) for n in ("sh_big", "sh_neg", "sh_nbig", "sh_end"))
        a.emit(0x48, 0x85, 0xC9)                     # test rcx,rcx
        a.jcc(8, neg)                                # js
        a.emit(0x48, 0x83, 0xF9, 0x3F)               # cmp rcx,63
        a.jcc(7, big)                                # ja  (unsigned compare: 64 or more shifts everything out)
        a.emit(0x48, 0xD3, {"<<": 0xE0, ">>": 0xE8, "+>": 0xF8}[op])   # shl / shr / sar rax,cl
        a.jmp(end)
        a.label(big)
        if op == "+>":
          a.emit(0x48, 0xC1, 0xF8, 0x3F)             # sar rax,63   (all sign bits)
        else:
          a.emit(0x31, 0xC0)                         # xor eax,eax
        a.jmp(end)
        a.label(neg)
        a.emit(0x48, 0xF7, 0xD9)                     # neg rcx      (|count|; the smallest int stays huge)
        a.emit(0x48, 0x83, 0xF9, 0x3F)               # cmp rcx,63
        a.jcc(7, nbig)
        a.emit(0x48, 0xD3, {"<<": 0xE8, ">>": 0xE0, "+>": 0xE0}[op])   # the opposite shift: shr / shl / shl rax,cl
        a.jmp(end)
        a.label(nbig)
        a.emit(0x31, 0xC0)                           # xor eax,eax
        a.label(end)
      elif op in ("<*", "*>"):                         # rotate; the count is taken modulo 64 by the hardware
        a.emit(0x48, 0xD3, 0xC0 if op == "<*" else 0xC8)   # rol / ror rax,cl
      elif op in ("\\", "%"):
        a.emit(0x48, 0x85, 0xC9)                     # test rcx,rcx
        a.jcc(4, "rt_divzero")
        a.emit(0x48, 0x99, 0x48, 0xF7, 0xF9)         # cqo; idiv rcx
        if op == "%":
          a.emit(0x48, 0x89, 0xD0)                 # mov rax,rdx
      else:
        a.emit(0x48, 0x39, 0xC8)                     # cmp rax,rcx
        a.emit(0x0F, CMP_SETCC[op], 0xC0)            # setcc al
        a.emit(0x0F, 0xB6, 0xC0)                     # movzx eax,al
    else:
      raise AssertionError(k)

  # -- statements
  def stmts(self, lst):
    for s in lst:
      self.stmt(s)

  def stmt(self, s):
    a, k = self.a, s[0]
    if k == "assign":
      if len(s) > 5:
        return                                         # a constant: already set at program start
      self.expr(s[2])
      self.var_store(s[1], s[3], s[4])
    elif k == "fn":
      pass                                             # created on scope entry (hoisted)
    elif k == "return":
      if s[1] is None:
        a.emit(0x31, 0xC0)
      else:
        self.expr(s[1])
      self.epilogue()
    elif k == "exprstmt":
      self.expr(s[1])
    elif k == "skip":
      pass
    elif k == "block":
      self.stmts(s[1])
    elif k == "print":
      for kind, v in s[1]:
        if kind == "str":
          a.rip([0x48, 0x8D, 0x0D], f"str:{v}")    # lea rcx,[str]
          a.emit(0xBA, struct.pack("<I", len(self.strings[v])))  # mov edx,len
          a.call("rt_print_str")
        else:
          self.expr(v)
          a.call("rt_print_float" if self.tk(v) == "float" else "rt_print_int")
      a.rip([0x48, 0x8D, 0x0D], "str:0")
      a.emit(0xBA, 1, 0, 0, 0)
      a.call("rt_print_str")
    elif k == "if":
      le = a.new_label("if_end")
      self.expr(s[1])
      self.test_rax(self.tk(s[1]))
      if s[3]:
        lelse = a.new_label("if_else")
        a.jcc(4, lelse)
        self.stmts(s[2])
        a.jmp(le)
        a.label(lelse)
        self.stmts(s[3])
      else:
        a.jcc(4, le)
        self.stmts(s[2])
      a.label(le)
    elif k == "while":
      ls, le = a.new_label("wh_start"), a.new_label("wh_end")
      a.label(ls)
      self.expr(s[1])
      self.test_rax(self.tk(s[1]))
      a.jcc(4, le)
      self.loops.append((ls, le))
      self.stmts(s[2])
      self.loops.pop()
      a.jmp(ls)
      a.label(le)
    elif k == "break":
      a.jmp(self.loops[-1][1])
    elif k == "continue":
      a.jmp(self.loops[-1][0])
    elif k == "exit":
      self.expr(s[1])
      a.emit(0x48, 0x89, 0xC1)                         # mov rcx,rax
      self.exit_process()
    else:
      raise AssertionError(k)

  def exit_process(self):
    a = self.a
    a.emit(0x48, 0x83, 0xE4, 0xF0)                       # and rsp,-16
    a.emit(0x48, 0x83, 0xEC, 0x20)                       # sub rsp,32 (shadow space)
    a.rip([0xFF, 0x15], "ExitProcess")                   # call [ExitProcess]

  # -- whole program
  def program(self, ast):
    a = self.a
    self.analyze(ast, self.g)
    a.label("main")
    a.emit(0x48, 0x83, 0xEC, 0x28)                       # sub rsp,0x28 (align + shadow)
    a.emit(0xB9, struct.pack("<i", -11))                 # mov ecx,STD_OUTPUT_HANDLE
    a.rip([0xFF, 0x15], "GetStdHandle")
    a.rip([0x48, 0x89, 0x05], "stdout")
    a.emit(0xB9, struct.pack("<I", 65001))               # mov ecx,CP_UTF8
    a.rip([0xFF, 0x15], "SetConsoleOutputCP")
    a.rip([0xFF, 0x15], "GetProcessHeap")
    a.rip([0x48, 0x89, 0x05], "heap")
    self.hoist(self.g)
    for s in ast:                                        # constants are created first (their values only need
      if s[0] == "assign" and len(s) > 5:               # numbers, earlier constants and function literals)
        self.expr(s[2])
        self.var_store(s[1], s[3], s[4])
    self.stmts(ast)
    a.emit(0x31, 0xC9)                                   # xor ecx,ecx
    self.exit_process()
    while self.queue:                                    # user functions (may queue nested ones)
      self.gen_function(self.queue.pop(0))
    self.runtime()
    a.resolve_labels()
    return a

  def runtime(self):
    a = self.a
    prologue = [0x55, 0x48, 0x89, 0xE5, 0x48, 0x83, 0xEC, 0x30, 0x48, 0x83, 0xE4, 0xF0]
    epilogue = [0x48, 0x89, 0xEC, 0x5D, 0xC3]

    # rt_print_str: rcx = pointer, rdx = length
    a.label("rt_print_str")
    a.emit(prologue)
    a.emit(0x49, 0x89, 0xD0)                             # mov r8,rdx
    a.emit(0x48, 0x89, 0xCA)                             # mov rdx,rcx
    a.rip([0x48, 0x8B, 0x0D], "stdout")                  # mov rcx,[stdout]
    a.rip([0x4C, 0x8D, 0x0D], "written")                 # lea r9,[written]
    a.emit(0x48, 0xC7, 0x44, 0x24, 0x20, 0, 0, 0, 0)     # mov qword [rsp+32],0
    a.rip([0xFF, 0x15], "WriteFile")
    a.emit(epilogue)

    # rt_print_int: rax = signed value
    a.label("rt_print_int")
    a.rip([0x4C, 0x8D, 0x05], "numbuf_end")              # lea r8,[numbuf_end]
    a.emit(0x45, 0x31, 0xC9)                             # xor r9d,r9d
    a.emit(0x48, 0x85, 0xC0)                             # test rax,rax
    a.jcc(9, "pi_pos")                                   # jns
    a.emit(0x48, 0xF7, 0xD8)                             # neg rax
    a.emit(0x41, 0xB9, 1, 0, 0, 0)                       # mov r9d,1
    a.label("pi_pos")
    a.emit(0xB9, 10, 0, 0, 0)                            # mov ecx,10
    a.label("pi_loop")
    a.emit(0x31, 0xD2)                                   # xor edx,edx
    a.emit(0x48, 0xF7, 0xF1)                             # div rcx (unsigned)
    a.emit(0x80, 0xC2, 0x30)                             # add dl,'0'
    a.emit(0x49, 0xFF, 0xC8)                             # dec r8
    a.emit(0x41, 0x88, 0x10)                             # mov [r8],dl
    a.emit(0x48, 0x85, 0xC0)                             # test rax,rax
    a.jcc(5, "pi_loop")                                  # jnz
    a.emit(0x4D, 0x85, 0xC9)                             # test r9,r9
    a.jcc(4, "pi_done")
    a.emit(0x49, 0xFF, 0xC8)                             # dec r8
    a.emit(0x41, 0xC6, 0x00, 0x2D)                       # mov byte [r8],'-'
    a.label("pi_done")
    a.emit(0x4C, 0x89, 0xC1)                             # mov rcx,r8
    a.rip([0x48, 0x8D, 0x15], "numbuf_end")              # lea rdx,[numbuf_end]
    a.emit(0x4C, 0x29, 0xC2)                             # sub rdx,r8
    a.jmp("rt_print_str")

    # rt_print_float: rax = bits of a double; rt_fmt_float (see FLOAT_RT) makes the text
    a.label("rt_print_float")
    a.emit(prologue)
    a.emit(0x48, 0x83, 0xEC, 0x40)                       # sub rsp,0x40   (text buffer)
    a.emit(0x48, 0x89, 0xE2)                             # mov rdx,rsp
    a.call("rt_fmt_float")                               # rax = length
    a.emit(0x48, 0x89, 0xC2)                             # mov rdx,rax
    a.emit(0x48, 0x89, 0xE1)                             # mov rcx,rsp
    a.call("rt_print_str")
    a.emit(epilogue)

    # runtime errors: print message, exit code 1
    for label, idx in (("rt_divzero", 1), ("rt_notfn", 2), ("rt_negexp", 3), ("rt_badpow", 4)):
      a.label(label)
      a.rip([0x48, 0x8D, 0x0D], f"str:{idx}")
      a.emit(0xBA, struct.pack("<I", len(self.strings[idx])))
      a.call("rt_print_str")
      a.emit(0xB9, 1, 0, 0, 0)                         # mov ecx,1
      self.exit_process()

    # rt_alloc: rcx = size in bytes -> rax = zeroed memory from the process heap
    a.label("rt_alloc")
    a.emit(prologue)
    a.emit(0x49, 0x89, 0xC8)                             # mov r8,rcx
    a.rip([0x48, 0x8B, 0x0D], "heap")                    # mov rcx,[heap]
    a.emit(0xBA, 8, 0, 0, 0)                             # mov edx,HEAP_ZERO_MEMORY
    a.rip([0xFF, 0x15], "HeapAlloc")
    a.emit(epilogue)

    for name, blob in FLOAT_RT.items():                   # rt_fmt_float, rt_fpow, rt_fmod: machine code from tools/float_rt.asm
      a.label(name)
      a.emit(blob)


# ----------------------------------------------------------------------------
# PE32+ writer
# ----------------------------------------------------------------------------
IMAGE_BASE = 0x140000000
SECT_ALIGN = 0x1000
FILE_ALIGN = 0x200
IMPORTS = ["GetStdHandle", "WriteFile", "SetConsoleOutputCP", "ExitProcess", "GetProcessHeap", "HeapAlloc"]


def align(x, a):
  return (x + a - 1) // a * a


def build_pe(asm, vars_, strings):
  # ---- .data layout: fixed runtime area, then variables, then strings
  sym = {"stdout": 0, "stdin": 8, "written": 0x10, "heap": 0x18, "numbuf_end": 0x40}
  off = 0x80
  for name, idx in vars_.items():
    sym["var:" + name] = off + idx * 8
  off += len(vars_) * 8
  for name in asm.static_closures:                            # 16 bytes each: [code, nparams]
    sym[name] = off
    off += 16
  data = bytearray(off)
  for i, s in enumerate(strings):
    sym[f"str:{i}"] = len(data)
    data += s + b"\0"
  data_vsize = len(data)

  # ---- .idata layout
  n = len(IMPORTS)
  ilt_off = 40
  iat_off = ilt_off + 8 * (n + 1)
  names_off = iat_off + 8 * (n + 1)
  hint_offs, blob = [], bytearray()
  for name in IMPORTS:
    hint_offs.append(names_off + len(blob))
    entry = struct.pack("<H", 0) + name.encode() + b"\0"
    if len(entry) % 2:
      entry += b"\0"
    blob += entry
  dll_off = names_off + len(blob)
  blob += b"kernel32.dll\0"
  idata_size = names_off + len(blob)

  # ---- section RVAs / file offsets
  code = asm.code
  text_rva = 0x1000
  idata_rva = text_rva + align(len(code), SECT_ALIGN)
  data_rva = idata_rva + align(idata_size, SECT_ALIGN)
  image_size = data_rva + align(data_vsize, SECT_ALIGN)

  text_raw, idata_raw, data_raw = (align(len(code), FILE_ALIGN),
                                   align(idata_size, FILE_ALIGN),
                                   align(data_vsize, FILE_ALIGN))
  text_fo = FILE_ALIGN
  idata_fo = text_fo + text_raw
  data_fo = idata_fo + idata_raw

  # ---- resolve rip-relative fixups
  iat_rva = {name: idata_rva + iat_off + 8 * i for i, name in enumerate(IMPORTS)}
  for pos, name in asm.fix:
    target = iat_rva[name] if name in iat_rva else data_rva + sym[name]
    code[pos:pos + 4] = struct.pack("<i", target - (text_rva + pos + 4))

  # ---- build .idata
  idata = bytearray(idata_size)
  struct.pack_into("<IIIII", idata, 0, idata_rva + ilt_off, 0, 0, idata_rva + dll_off, idata_rva + iat_off)
  for i in range(n):
    struct.pack_into("<Q", idata, ilt_off + 8 * i, idata_rva + hint_offs[i])
    struct.pack_into("<Q", idata, iat_off + 8 * i, idata_rva + hint_offs[i])
  idata[names_off:names_off + len(blob)] = blob

  # ---- headers
  dos = bytearray(0x40)
  dos[0:2] = b"MZ"
  struct.pack_into("<I", dos, 0x3C, 0x40)

  coff = struct.pack("<HHIIIHH", 0x8664, 3, 0, 0, 0, 240, 0x0022)
  opt = struct.pack(
      "<HBBIIIII", 0x20B, 14, 0, text_raw, idata_raw + data_raw, 0, text_rva, text_rva)
  opt += struct.pack("<QII", IMAGE_BASE, SECT_ALIGN, FILE_ALIGN)
  opt += struct.pack("<HHHHHH", 6, 0, 0, 0, 6, 0)
  opt += struct.pack("<IIIIHH", 0, image_size, FILE_ALIGN, 0, 3, 0x8100)
  opt += struct.pack("<QQQQII", 0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
  dirs = [(0, 0)] * 16
  dirs[1] = (idata_rva, 40)                                   # import table
  dirs[12] = (idata_rva + iat_off, 8 * (n + 1))               # IAT
  for rva, size in dirs:
    opt += struct.pack("<II", rva, size)
  assert len(opt) == 240

  def section(name, vsize, rva, rawsize, rawptr, flags):
    return struct.pack("<8sIIIIIIHHI", name, vsize, rva, rawsize, rawptr, 0, 0, 0, 0, flags)

  sections = (section(b".text", len(code), text_rva, text_raw, text_fo, 0x60000020)
              + section(b".idata", idata_size, idata_rva, idata_raw, idata_fo, 0xC0000040)
              + section(b".data", data_vsize, data_rva, data_raw, data_fo, 0xC0000040))

  headers = bytes(dos) + b"PE\0\0" + coff + opt + sections
  assert len(headers) <= FILE_ALIGN
  out = bytearray(headers.ljust(FILE_ALIGN, b"\0"))
  out += bytes(code).ljust(text_raw, b"\0")
  out += bytes(idata).ljust(idata_raw, b"\0")
  out += bytes(data).ljust(data_raw, b"\0")
  return bytes(out)


# ----------------------------------------------------------------------------
def compile_source(src, warnings=None):
  parser = Parser(tokenize(strip_comments(src.replace("\r\n", "\n"))))
  ast = parser.program()
  checker = Checker(parser.global_scope)
  checker.run(ast)
  if warnings is not None:
    warnings.extend(parser.warnings)
  asm = CodeGen(parser.global_scope, parser.strings, parser.fn_globals, checker.types).program(ast)
  return build_pe(asm, parser.vars, parser.strings)


def main():
  ap = argparse.ArgumentParser(description="Compile a Ka program to a Windows x64 .exe")
  ap.add_argument("--version", action="version", version=f"ka {VERSION}")
  ap.add_argument("source")
  ap.add_argument("-o", "--output")
  args = ap.parse_args()
  out = args.output or os.path.splitext(args.source)[0] + ".exe"
  warnings = []
  try:
    with open(args.source, encoding="utf-8") as f:
      exe = compile_source(f.read(), warnings)
  except CompileError as e:
    print(f"{args.source}: error: {e}", file=sys.stderr)
    return 1
  for w in warnings:
    print(f"{args.source}: warning: {w}", file=sys.stderr)
  with open(out, "wb") as f:
    f.write(exe)
  print(f"wrote {out} ({len(exe)} bytes)")
  return 0


if __name__ == "__main__":
  sys.exit(main())
