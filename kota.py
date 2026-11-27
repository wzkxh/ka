#!/usr/bin/env python3
"""
kota - a compiler for the language "Kota" that produces a native Windows x64 console
executable (PE32+) directly. Pure Python 3, no dependencies (the compiler runs on any
OS; the produced .exe runs on Windows).

Usage:
    python kota.py program.ko              -> program.exe
    python kota.py program.ko -o out.exe
    python kota.py -e program.ko           compile, run the .exe, delete it   (-k: keep it)
    python kota.py -c "print 1 + 2"        compile the text, run, delete      (-k: keep it as yyyymmdd_HHMMSS.exe)

The language is described in LANGUAGE.md. Pipeline:
    strip comments -> tokenize (NEWLINE/INDENT/DEDENT) -> parse to AST (tuples)
    -> type check (static inference) -> x86-64 code -> PE image
"""
import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
import time


VERSION = "7.4"                         # see RELEASE_NOTES.md
CHECK_INIT = True                       # runtime checks of variables that are not provably assigned (see InitCheck); a mode to switch off later
WARN_UNUSED_VALUE = False               # warning for an expression statement that is not a call; off by default
CHECK_ASSERTS = True                    # `assert` statements are checked at run time; False: they are parsed and dropped (no code, nothing evaluated)


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
KEYWORDS = {"if", "elif", "else", "while", "break", "continue", "print", "exit", "function", "return", "skip", "assert"}
STMT_KW = {"if", "while", "break", "continue", "print", "exit", "return", "skip", "assert"}

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
#     ("bin", op, l, r) ("cmp", ops, operands) ("and"/"or", l, r) ("neg"/"not"/"bnot"/"rand"/"abs"/"prime", e)
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


def render_tokens(toks):
  """the source text of some tokens as one line, for the report of a failed assert (the spelling of numbers and the spaces are normalised)"""
  out, prev, prefix = [], None, False
  for k, v, _ in toks:
    if k in ("nl", "indent", "dedent", "eof"):
      return ""                                           # not a simple one-line expression: no text
    if k in ("num", "hex"):
      t = str(v)
    elif k == "flt":
      t = repr(v)
    elif k == "str":
      data, kind = v
      q = "'" if kind == "b" else '"'
      body = "".join(f"^{ord(ch):02x}" if ch in (q, "^") or ord(ch) < 32 else ch for ch in data.decode("utf-8", "replace"))
      t = q + body + q
    else:
      t = v
    operand_before = prev is not None and (prev[0] in ("num", "hex", "flt", "str", "id") or prev[1] in (")", "]"))
    unary = k == "op" and t in ("-", "!", "~", "?", "\\", "^", "@") and not operand_before
    if out and not prefix and t not in (")", "]", ",", ";") and not (t in ("(", "[") and operand_before) and not (out[-1] in ("(", "[")):
      out.append(" ")
    out.append(t)
    prefix = unary
    prev = (k, t)
  text = "".join(out)
  return text if len(text) <= 120 else text[:117] + "..."


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
    # strings 0..6 are used by the runtime
    self.strings = [b"\n", b"runtime error: division by zero\n",
                    b"runtime error: call of an unset function\n",
                    b"runtime error: negative exponent\n",
                    b"runtime error: power of a negative number with a fractional exponent\n",
                    b"runtime error: bad argument of '?'\n",
                    b"runtime error: out of memory\n"]
    self.byte_strings = []              # str literals (bytes), stored in .data as [u64 length][bytes]
    self.text_strings = []              # text literals (lists of code points), stored as [u64 count][u32 ...]
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
            or (k == "op" and v == "!" and self.ctx and self.ctx[-1] == "?")
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
    elif k == "op" and (v in ("}", "{") or (v in (")", ",") and self.ctx and self.ctx[-1] == "(")
                        or (v == "!" and self.ctx and self.ctx[-1] == "?")):
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
      self.scope.consts[name] = line
      self.declare(name, mode, line)
      return ("assign", name, e, line, mode, True)
    self.declare(name, mode, line)
    return ("assign", name, e, line, mode)

  def expr_stmt(self):
    line = self.peek()[2]
    e = self.expr()
    self.end_stmt()
    if WARN_UNUSED_VALUE and e[0] != "call":               # off by default
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

  def print_item(self):                   # one item of 'print' (and the report of 'assert'): a string literal (static) or an expression
    save = (self.i, len(self.ctx))
    s = self.string_item()
    if s is not None and not (self.at_end() or self.is_(",")):
      self.i = save[0]                                # 'a' + 'b': not a plain literal, an expression
      del self.ctx[save[1]:]
      s = None
    if s is not None:
      self.strings.append(s)
      return ("str", len(self.strings) - 1)
    return ("expr", self.expr())

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
            items.append(self.print_item())
            if not self.accept(","):
              break
        self.end_stmt()
        return ("print", items, line)
      if v == "assert":                               # assert condition[, what to report]
        self.next()
        start = self.i
        cond = self.expr()
        text = render_tokens(self.t[start:self.i])
        item = self.print_item() if self.accept(",") else None
        self.end_stmt()
        if not CHECK_ASSERTS:
          return ("skip",)
        head = f"assertion failed (line {line})"
        self.strings.append((head + (": " if item or text else "")).encode())
        items = [("str", len(self.strings) - 1)]
        if item:
          items.append(item)
        elif text:
          self.strings.append(text.encode())
          items.append(("str", len(self.strings) - 1))
        # if !condition: print the report, exit 1   (the checker names the 'assert' in its messages: the third item of "not")
        return ("if", ("not", cond, "in 'assert'"), [("print", items, line), ("exit", ("num", 1), line)], [], line)
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
    if k in ("num", "hex", "flt") or (k == "op" and v in ("(", "-", "!", "~", "?", "|", "*")):
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
      self.ctx.append("?")                          # a one-line body in the middle part ends at the `!`
      a = self.expr()
      self.ctx.pop()
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
    if self.accept("?"):                            # a random number; after an operand `?` is the conditional
      return ("rand", self.unary())
    if self.accept("|"):                            # |x: the absolute value of a number, the length of a str or a text (after an operand `|` is bitwise or)
      return ("abs", self.unary())
    if self.accept("*"):                            # *n: 1 if the int n is prime, else 0 (after an operand `*` is multiplication)
      return ("prime", self.unary())
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
      data, kind = v
      while self.peek()[0] == "str":                  # literals written one after another are joined
        tok = self.next()
        if tok[1][1] != kind:
          raise CompileError(f"line {tok[2]}: cannot join '...' and \"...\" strings")
        data += tok[1][0]
      if kind == "b":
        self.byte_strings.append(data)
        return ("bstr", len(self.byte_strings) - 1)
      self.text_strings.append([ord(ch) for ch in data.decode("utf-8")])
      return ("btext", len(self.text_strings) - 1)
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
STR = Ty("str")
TEXT = Ty("text")
ARITH_OPS = ("+", "-", "*", "%", "^")      # float if either side is float (`/` is always float, `\\` always int)


def prune(t):
  while t.kind == "var" and t.ref is not None:
    t = t.ref
  return t


def show(t, seen=()):
  t = prune(t)
  if t.kind in ("int", "float", "str", "text"):
    return t.kind
  if t.kind == "var":
    return "?"
  if id(t) in seen:
    return "..."                        # a function type that contains itself
  seen = seen + (id(t),)
  s = "fn(" + ",".join(show(p, seen) for p in t.params) + ")"
  r = prune(t.ret)
  return s if r.kind == "var" else s + "->" + show(r, seen)


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
  def need_num(self, t, line, what, strings=False):
    """t must be a number (int or float); with strings=True also a str or a text (a truth value, or printing)"""
    t = prune(t)
    if t.kind == "fn" or (t.kind in ("str", "text") and not strings):
      self.err(line, f"type mismatch {what}: expected a number{' or a string' if strings else ''}, found {show(t)}")
    if t.kind == "var":
      self.pending.append(("num", t, line, what, strings))

  def string_kind(self, a, b):
    """'str' or 'text' if one of two types is a string type, else None"""
    return a.kind if a.kind in ("str", "text") else b.kind if b.kind in ("str", "text") else None

  def same_string(self, a, b, line, err):
    """both types must be the string type of the other one (an unknown type becomes it); err(t) is the message"""
    kind = self.string_kind(a, b)
    ty = STR if kind == "str" else TEXT
    for t in (a, b):
      if t.kind == "var":
        self.unify(t, ty, line, "")
      elif t.kind != kind:
        self.err(line, err(kind, t))
    return ty

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
      self.need_num(t, c[2], c[3], len(c) > 4 and c[4])
      return True
    if kind == "abs":
      _, res, t, line = c
      t = prune(t)
      if t.kind == "var":
        return False
      if t.kind == "fn":
        self.err(line, f"type mismatch in operand of '|': expected a number or a string, found {show(t)}")
      self.unify(res, FLOAT if t.kind == "float" else INT, line, "")
      return True
    if kind == "order":                 # numbers (any mix) or two strings of the same kind
      _, a, b, line, op = c
      a, b = prune(a), prune(b)
      if self.string_kind(a, b):
        self.same_string(a, b, line, lambda k, t: f"type mismatch in '{op}': cannot compare {k} and {show(t)}")
        return True
      for side, t in (("left", a), ("right", b)):
        if t.kind == "fn":
          self.err(line, f"type mismatch in {side} operand of '{op}': expected a number, found {show(t)}")
      if a.kind == "var" and b.kind == "var":
        return False
      if a.kind == "var" or b.kind == "var":
        self.pending.append(("num", a if a.kind == "var" else b, line, f"in '{op}'", False))
      return True
    if kind == "arith":                 # result = float if one side is float, else int
      _, res, a, b, line, op = c
      a, b = prune(a), prune(b)
      if op == "+" and self.string_kind(a, b):         # concatenation: both sides are str, or both are text
        def bad(k, t):
          return f"type mismatch in {'left' if t is a else 'right'} operand of '+': " + \
                 (f"expected str, found {show(t)}" if k == "str" else f"cannot mix text and {show(t)}")
        self.result(res, self.same_string(a, b, line, bad), line, op)
        return True
      if a.kind in ("fn", "str", "text"):
        self.err(line, f"type mismatch in left operand of '{op}': expected a number, found {show(a)}")
      if b.kind in ("fn", "str", "text"):
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
    if kind == "eq":                    # two numbers (any mix), two strings of the same kind, or two functions of the same type
      _, a, b, line, what = c
      a, b = prune(a), prune(b)
      if self.string_kind(a, b):
        self.same_string(a, b, line, lambda k, t: f"type mismatch {what}: cannot compare {k} and {show(t)}")
        return True
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
      if a.kind in ("fn", "str", "text") or b.kind in ("fn", "str", "text"):
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
      r = self.lookup(s[1], sc, s[3], s[4])
      if any(f.name == s[1] for f in (self.g if r[0] == "g" else r[1]).named_fns):
        self.err(s[3], f"'{s[1]}' is a function (defined with 'function') and cannot be assigned")
      self.unify(self.var_ty(s[1], sc, s[3], s[4]), t, s[3], f"in assignment to '{s[1]}'")
    elif k == "print":
      for kind, v in s[1]:
        if kind == "expr":
          self.need_num(self.expr(v, sc, s[2]), s[2], "in 'print' (only numbers, str and text can be printed)", True)
    elif k == "if":
      self.need_num(self.expr(s[1], sc, s[4]), s[4], "in the condition of 'if'", True)
      self.stmts(s[2], sc)
      self.stmts(s[3], sc)
    elif k == "while":
      self.need_num(self.expr(s[1], sc, s[3]), s[3], "in the condition of 'while'", True)
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
    if k == "bstr":
      return STR
    if k == "btext":
      return TEXT
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
        self.constrain(("order", self.expr(e[2], sc, line), self.expr(e[3], sc, line), line, op))
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
          self.constrain(("order", a, b, line, op))
      return INT
    if k == "cond":
      self.need_num(self.expr(e[1], sc, line), line, "in the condition of '?'", True)
      ta, tb = self.expr(e[2], sc, line), self.expr(e[3], sc, line)
      res = Ty("var")
      self.constrain(("cond", res, ta, tb, line, "in '?!' (both branches must have the same type, or both be numbers)"))
      return res
    if k in ("and", "or"):
      sym = '&&' if k == 'and' else '||'
      self.need_num(self.expr(e[1], sc, line), line, f"in left operand of '{sym}'", True)
      self.need_num(self.expr(e[2], sc, line), line, f"in right operand of '{sym}'", True)
      return INT
    if k == "neg":
      t = self.expr(e[1], sc, line)
      self.need_num(t, line, "in operand of '-'")
      return t
    if k == "rand":                     # ?x has the type of x: int -> int, float -> float, str -> str, text -> text
      t = self.expr(e[1], sc, line)
      self.need_num(t, line, "in operand of '?'", True)
      return t
    if k == "not":
      self.need_num(self.expr(e[1], sc, line), line, e[2] if len(e) > 2 else "in operand of '!'", True)
      return INT
    if k == "bnot":
      self.operand(e[1], sc, line, "operand of '~'")
      return INT
    if k == "prime":                    # *n: int only, the result is an int (0 or 1)
      self.operand(e[1], sc, line, "operand of '*'")
      return INT
    if k == "abs":                      # |x: int -> int, float -> float, str or text -> int (the length)
      res = Ty("var")
      self.constrain(("abs", res, self.expr(e[1], sc, line), line))
      return res
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


# ----------------------------------------------------------------------------
# Variables used before they are assigned: definite assignment analysis.
# For every read of a variable it is decided whether the variable is
#   - assigned on every path that leads to the read: nothing is needed;
#   - assigned on no path: a compile error;
#   - maybe assigned: the variable gets a hidden "assigned" flag, the read checks it (runtime error if not set).
# A variable of another scope (a global read in a function, a variable of the enclosing function) is safe if it is
# assigned at every place where code of its scope can start the function: every call in the top-level code, or every
# call and every exit of the enclosing function. Parameters and `function name` definitions are assigned from the start.
# ----------------------------------------------------------------------------
class InitState:
  __slots__ = ("must","may")

  def __init__(self,must,may):
    self.must,self.may = must,may         # keys assigned on every path / on some path

  def copy(self):
    return InitState(set(self.must),set(self.may))


def join_states(a,b):                     # None = the code is not reachable
  if a is None:
    return b
  if b is None:
    return a
  return InitState(a.must & b.must,a.may | b.may)


class InitCheck(Resolver):
  def __init__(self,gscope):
    self.g = gscope
    self.cur = gscope
    self.scopes = []
    self.seen = set()
    self.ext = set()                      # keys that code of another scope can assign (^x, @x)
    self.calls = {}                       # scope -> the 'must' sets at its call sites
    self.exits = {}                       # scope -> the 'must' sets where it can be left
    self.deferred = []                    # (node, key): reads of variables of another scope
    self.check_reads = set()              # id(var node) of the reads that need a runtime check
    self.flagged = set()                  # keys of the variables that need a hidden flag

  def key_of(self,r):                     # the same keys as Checker.key
    return ("g",r[1]) if r[0] == "g" else (r[1],r[2])

  def owner(self,key):
    return self.g if key[0] == "g" else key[0]

  def ext_own(self):
    return {k for k in self.ext if self.owner(k) is self.cur}

  # -- phase 1: all scopes, and the variables that other scopes assign
  def add_scope(self,f):
    if f not in self.seen:
      self.seen.add(f)
      self.scopes.append(f)
      self.collect(f.body,f)

  def collect(self,stmts,sc):
    for s in stmts:
      k = s[0]
      if k == "assign":
        self.collect_expr(s[2],sc)
        key = self.key_of(self.lookup(s[1],sc,s[3],s[4]))
        if self.owner(key) is not sc:
          self.ext.add(key)
      elif k == "print":
        for kind,v in s[1]:
          if kind == "expr":
            self.collect_expr(v,sc)
      elif k == "if":
        self.collect_expr(s[1],sc)
        self.collect(s[2],sc)
        self.collect(s[3],sc)
      elif k == "while":
        self.collect_expr(s[1],sc)
        self.collect(s[2],sc)
      elif k in ("exit","exprstmt"):
        self.collect_expr(s[1],sc)
      elif k == "return":
        if s[1] is not None:
          self.collect_expr(s[1],sc)
      elif k == "block":
        self.collect(s[1],sc)
      elif k == "fn":
        self.add_scope(s[1])

  def collect_expr(self,e,sc):
    if isinstance(e,tuple) and e and isinstance(e[0],str):
      if e[0] == "fnlit":
        self.add_scope(e[1])
        return
      for x in e[1:]:
        if isinstance(x,(tuple,list)):
          self.collect_expr(x,sc)
    elif isinstance(e,list):
      for x in e:
        self.collect_expr(x,sc)

  # -- phase 2: the flow of every scope
  def run(self,ast):
    self.g.body = ast
    self.scopes = [self.g]
    self.seen = {self.g}
    self.collect(ast,self.g)
    for sc in self.scopes:
      self.flow_scope(sc)
    for e,key in self.deferred:           # variables of another scope
      o = self.owner(key)
      if not all(key in m for m in self.calls[o] + self.exits[o]):
        self.check_reads.add(id(e))
        self.flagged.add(key)

  def flow_scope(self,sc):
    self.cur = sc
    self.calls[sc] = []
    self.exits[sc] = []
    must = {(sc,p) for p in sc.params}
    for f in sc.named_fns:                # `function name` definitions exist from the start of the scope
      must.add(("g",f.name) if sc is self.g else (sc,f.name))
    end = self.stmts(sc.body,InitState(must,set(must)))
    if end is not None and sc is not self.g:
      self.exits[sc].append(set(end.must))

  def stmts(self,lst,st):
    for s in lst:
      if st is None:
        return None
      st = self.stmt(s,st)
    return st

  def stmt(self,s,st):
    k = s[0]
    if k == "assign":
      self.expr(s[2],st)
      key = self.key_of(self.lookup(s[1],self.cur,s[3],s[4]))
      st.must.add(key)
      st.may.add(key)
    elif k == "print":
      for kind,v in s[1]:
        if kind == "expr":
          self.expr(v,st)
    elif k == "if":
      self.expr(s[1],st)
      st = join_states(self.stmts(s[2],st.copy()),self.stmts(s[3],st.copy()))
    elif k == "while":                    # the body may run again and again, or not at all
      widen = self.assigned_in(s[2])
      if self.has_call(s[1]) or self.has_call(s[2]):
        widen |= self.ext_own()
      head = st.copy()
      head.may |= widen
      self.expr(s[1],head.copy())
      self.stmts(s[2],head.copy())
      st.may |= widen
    elif k == "exit":
      self.expr(s[1],st)
      return None
    elif k == "exprstmt":
      self.expr(s[1],st)
    elif k == "return":
      if s[1] is not None:
        self.expr(s[1],st)
      if self.cur is not self.g:
        self.exits[self.cur].append(set(st.must))
      return None
    elif k in ("break","continue"):
      return None
    elif k == "block":
      return self.stmts(s[1],st)
    return st

  def assigned_in(self,stmts):            # keys assigned in a list of statements (not in the functions inside it)
    keys = set()
    for s in stmts:
      k = s[0]
      if k == "assign":
        keys.add(self.key_of(self.lookup(s[1],self.cur,s[3],s[4])))
      elif k == "if":
        keys |= self.assigned_in(s[2]) | self.assigned_in(s[3])
      elif k == "while":
        keys |= self.assigned_in(s[2])
      elif k == "block":
        keys |= self.assigned_in(s[1])
    return keys

  def has_call(self,x):
    if isinstance(x,tuple):
      return (len(x) > 0 and x[0] == "call") or any(self.has_call(y) for y in x if isinstance(y,(tuple,list)))
    if isinstance(x,list):
      return any(self.has_call(y) for y in x)
    return False

  def expr(self,e,st):
    k = e[0]
    if k in ("num","flt","fnlit","bstr","btext"):
      return
    if k == "var":
      self.read(e,st)
    elif k == "call":
      self.expr(e[1],st)
      for x in e[2]:
        self.expr(x,st)
      self.calls[self.cur].append(set(st.must))
      st.may |= self.ext_own()            # the called code may assign variables of this scope
    elif k == "bin":
      self.expr(e[2],st)
      self.expr(e[3],st)
    elif k == "cmp":
      for x in e[2]:
        self.expr(x,st)
    elif k == "cond":
      for x in e[1:4]:
        self.expr(x,st)
    elif k in ("and","or"):
      self.expr(e[1],st)
      self.expr(e[2],st)
    else:                                 # neg, not, bnot, rand
      self.expr(e[1],st)

  def read(self,e,st):
    name,line,mode = e[1],e[2],e[3]
    key = self.key_of(self.lookup(name,self.cur,line,mode))
    if key in st.must:
      return
    if self.owner(key) is self.cur:
      if key in st.may:
        self.check_reads.add(id(e))
        self.flagged.add(key)
        return
      if self.cur is self.g:
        self.err(line,f"variable '{name}' used before assignment")
      self.err(line,f"variable '{name}' is local to function '{self.cur.name}' and used before "
                    f"assignment (use '^{name}' to refer to the global one)")
    self.deferred.append((e,key))


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


# ---- BEGIN TIME_RT (generated by tools/build_float_rt.py from tools/time_rt.asm; do not edit by hand)
TIME_RT = {
  "rt_utf8_to_text": bytes.fromhex(
    "4531c04885c90f84d10100004939d00f83c80100000fb60641bb010000003d800000000f82a20100003dc20000000f828901"
    "00003de00000000f821b0000003df00000000f824e0000003df50000000f82c8000000e9630100004883f9020f8259010000"
    "83e01f440fb64e014589ca4181e2c00000004181fa800000000f853a0100004183e13fc1e0064409c841bb02000000e93301"
    "00004883f9030f821b01000083e00f440fb64e014589ca4181e2c00000004181fa800000000f85fc0000004183e13fc1e006"
    "4409c8440fb64e024589ca4181e2c00000004181fa800000000f85d60000004183e13fc1e0064409c83d000800000f82c100"
    "00003d00d800000f820b0000003d00e000000f82ab00000041bb03000000e9ae0000004883f9040f829600000083e007440f"
    "b64e014589ca4181e2c00000004181fa800000000f85770000004183e13fc1e0064409c8440fb64e024589ca4181e2c00000"
    "004181fa800000000f85510000004183e13fc1e0064409c8440fb64e034589ca4181e2c00000004181fa800000000f852b00"
    "00004183e13fc1e0064409c83d000001000f82160000003d000011000f830b00000041bb04000000e90e0000000fb6060500"
    "dc000041bb010000004289048749ffc04c01de4c29d9e926feffff4c89c0c3"
  ),
  "rt_text_to_utf8": bytes.fromhex(
    "4989f84885c90f84050100008b064883c60448ffc93d800000000f82e70000003d000800000f82b70000003d000001000f82"
    "510000004189c141c1e9124181c9f000000044880f4189c141c1e90c4183e13f4181c98000000044884f014189c141c1e906"
    "4183e13f4181c98000000044884f0283e03f0d800000008847034883c704e97cffffff3d80dc00000f82150000003dffdc00"
    "000f870a000000880748ffc7e95cffffff4189c141c1e90c4181c9e000000044880f4189c141c1e9064183e13f4181c98000"
    "000044884f0183e03f0d800000008847024883c703e921ffffff4189c141c1e9064181c9c000000044880f83e03f0d800000"
    "008847014883c702e9fcfeffff880748ffc7e9f2feffff4889f84c29c0c3"
  ),
  "rt_time_format": bytes.fromhex(
    "4989d44531c04885c90f84790200004983f8400f836f0200008b064883f9020f825a000000448b4e044183e9314183f9030f"
    "874800000083f8790f845200000083f86d0f848b00000083f8640f848d00000083f8480f848f00000083f84d0f8491000000"
    "83f8530f849300000083f8460f84a300000083f8770f84e70000004289048749ffc04883c60448ffc9e974ffffff4183f901"
    "0f841a0000004183f9030f85d9ffffff450fb7142441bb04000000e933010000410fb7042431d241ba6400000041f7f24189"
    "d241bb02000000e915010000450fb7542402e927000000450fb7542406e91c000000450fb7542408e911000000450fb75424"
    "0ae906000000450fb754240c4183f9010f876fffffff458d5901e9d00000004183f9020f875cffffff410fb744240e31d241"
    "ba640000004183f9000f841c00000041ba0a0000004183f9010f840c0000004189c2458d5901e99200000041f7f24189c245"
    "8d5901e9830000004183f9020f870fffffff410fb744240485c00f8505000000b8070000004183f9000f850e0000004189c2"
    "41bb01000000e94e000000ffc88d04404189c24589cd41ffc54489c04401e883f8400f87d0000000488d05cd0000004c01d0"
    "31d2440fb614104689148749ffc048ffc24439ea0f82e8ffffff4883c6084883e902e91dfeffff4589dd4183fa0a0f821000"
    "00004183fd020f830600000041bd020000004183fa640f82100000004183fd030f830600000041bd030000004181fae80300"
    "000f82100000004183fd040f830600000041bd040000004489c04401e883f8400f873c0000004489d04d89c349c1e3024901"
    "fb41ba0a0000004589e931d241f7f283c2304389548bfc41ffc90f85eaffffff4d01e84883c6084883e902e97efdffff4c89"
    "c0c34d6f6e54756557656454687546726953617453756e"
  ),
}
# ---- END TIME_RT


# ---- BEGIN INT_RT (generated by tools/build_float_rt.py from tools/int_rt.asm; do not edit by hand)
INT_RT = {
  "rt_isprime": bytes.fromhex(
    "4883f8420f8d210000004883f8020f8c86000000488d48fe48ba2b8a22288822080a48d3ea89d083e001c3a8010f84670000"
    "004989c031d2b90300000048f7f14885d20f845100000041b9050000004c89c8490fafc10f80380000004c39c00f8f2f0000"
    "004c89c031d249f7f14885d20f8424000000498d49024c89c031d248f7f14885d20f840f0000004983c106e9bbffffffb801"
    "000000c331c0c3"
  ),
}
# ---- END INT_RT


class CodeGen(Resolver):
  def __init__(self, gscope, strings, byte_strings, text_strings, fn_globals, types, init):
    self.check_reads = init.check_reads if CHECK_INIT else set()     # reads that check the hidden flag of a variable
    self.flagged = init.flagged if CHECK_INIT else set()             # variables that have a hidden flag
    self.uninit_stubs = {}
    self.types = types                  # id(expression node) -> Ty, from the Checker
    self.a = Asm()
    self.g = gscope
    self.scope = gscope
    self.strings = strings
    self.strings_b = byte_strings
    self.strings_t = text_strings
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
    elif k in ("neg", "not", "bnot", "rand", "abs", "prime"):
      self.a_expr(e[1], sc)
    elif k == "fnlit":
      self.analyze(e[1].body, e[1])

  # -- variable access
  def free_box(self, owner, name):                         # rdx = box pointer of a captured variable
    a, i = self.a, self.scope.free[(owner, name)]
    a.emit(0x48, 0x8B, 0x55, 0x10)                       # mov rdx,[rbp+16]   (closure)
    a.emit(0x48, 0x8B, 0x92, struct.pack("<i", 16 + 8 * i))   # mov rdx,[rdx+16+8i]

  # -- hidden "assigned" flags of the variables that InitCheck could not prove assigned at every read
  def key_of(self,r):
    return ("g",r[1]) if r[0] == "g" else (r[1],r[2])

  def alloc_flags(self):
    for key in sorted(self.flagged,key=lambda k: ("" if k[0] == "g" else k[0].label,k[1])):
      name = key[1]
      if key[0] == "g":                                  # a global: one more data slot
        self.g.slots["?init:" + name] = len(self.g.slots)
      elif name not in key[0].boxed:                     # a local: one more frame slot (a captured variable keeps its flag in its box)
        key[0].nlocals += 1
        key[0].slots["?init:" + name] = -8 * key[0].nlocals

  def stub_label(self,name):                             # where a failed check jumps to
    if name not in self.uninit_stubs:
      self.strings.append(f"runtime error: variable '{name}' is not initialized\n".encode())
      self.uninit_stubs[name] = (self.a.new_label("uninit"),len(self.strings) - 1)
    return self.uninit_stubs[name][0]

  def emit_uninit_stubs(self):
    a = self.a
    for name,(label,idx) in self.uninit_stubs.items():
      a.label(label)
      a.rip([0x48,0x8D,0x0D],f"str:{idx}")               # lea rcx,[message]
      a.emit(0xBA,struct.pack("<I",len(self.strings[idx])))   # mov edx,length
      a.call("rt_print_str")
      a.emit(0xB9,1,0,0,0)                               # mov ecx,1
      self.exit_process()

  def flag_test(self,name):                              # rax = the flag
    a = self.a
    a.emit(0x48,0x85,0xC0)                               # test rax,rax
    a.jcc(4,self.stub_label(name))                       # jz: the variable was never assigned

  def var_load(self, name, line, mode=None, check=False):
    a, sc = self.a, self.scope
    r = self.lookup(name,sc,line,mode)
    check = check and CHECK_INIT
    if r[0] == "g":
      if check:
        a.rip([0x48,0x8B,0x05],"var:?init:" + name)      # mov rax,[flag]
        self.flag_test(name)
      a.rip([0x48,0x8B,0x05],"var:" + name)              # mov rax,[var]
    elif r[0] == "l":
      off = sc.slots[name]
      if name in sc.boxed:
        a.emit(0x48,0x8B,0x95,struct.pack("<i",off))     # mov rdx,[rbp+off]  (box)
        if check:
          a.emit(0x48,0x8B,0x42,0x08)                    # mov rax,[rdx+8]    (flag)
          self.flag_test(name)
        a.emit(0x48,0x8B,0x02)                           # mov rax,[rdx]
      else:
        if check:
          a.emit(0x48,0x8B,0x85,struct.pack("<i",sc.slots["?init:" + name]))   # mov rax,[rbp+flag]
          self.flag_test(name)
        a.emit(0x48,0x8B,0x85,struct.pack("<i",off))     # mov rax,[rbp+off]
    else:
      self.free_box(r[1],name)
      if check:
        a.emit(0x48,0x8B,0x42,0x08)                      # mov rax,[rdx+8]    (flag)
        self.flag_test(name)
      a.emit(0x48,0x8B,0x02)                             # mov rax,[rdx]

  def var_store(self, name, line, mode=None):              # value in rax
    a, sc = self.a, self.scope
    r = self.lookup(name,sc,line,mode)
    flag = CHECK_INIT and self.key_of(r) in self.flagged
    if r[0] == "g":
      a.rip([0x48,0x89,0x05],"var:" + name)              # mov [var],rax
      if flag:
        a.emit(0xB9,1,0,0,0)                             # mov ecx,1
        a.rip([0x48,0x89,0x0D],"var:?init:" + name)      # mov [flag],rcx
    elif r[0] == "l":
      off = sc.slots[name]
      if name in sc.boxed:
        a.emit(0x48,0x8B,0x95,struct.pack("<i",off))     # mov rdx,[rbp+off]
        a.emit(0x48,0x89,0x02)                           # mov [rdx],rax
        if flag:
          a.emit(0x48,0xC7,0x42,0x08,struct.pack("<I",1))   # mov qword [rdx+8],1
      else:
        a.emit(0x48,0x89,0x85,struct.pack("<i",off))     # mov [rbp+off],rax
        if flag:
          a.emit(0x48,0xC7,0x85,struct.pack("<i",sc.slots["?init:" + name]),struct.pack("<I",1))   # mov qword [rbp+flag],1
    else:
      self.free_box(r[1],name)
      a.emit(0x48,0x89,0x02)                             # mov [rdx],rax
      if flag:
        a.emit(0x48,0xC7,0x42,0x08,struct.pack("<I",1))  # mov qword [rdx+8],1

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
        a.emit(0xB9, struct.pack("<I", 16 if (f, name) in self.flagged else 8))
        a.call("rt_alloc")
        if name in f.params:
          a.emit(0x48, 0x8B, 0x95, struct.pack("<i", off))   # mov rdx,[rbp+off]
          a.emit(0x48, 0x89, 0x10)                           # mov [rax],rdx
        a.emit(0x48, 0x89, 0x85, struct.pack("<i", off))       # mov [rbp+off],rax
    self.hoist(f)
    self.stmts(f.body)
    a.emit(0x31, 0xC0)                                   # xor eax,eax  (default result 0)
    self.epilogue()

  # -- types in the generated code: values are always 64 bits; a float is the bit pattern of a double
  def tk(self, e):
    """'int', 'float', 'str', 'text' or 'fn' (a type that was never determined counts as int)"""
    t = prune(self.types.get(id(e), INT))
    return t.kind if t.kind in ("float", "fn", "str", "text") else "int"

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
    elif k in ("bstr", "btext"):                         # address of the static object; the empty string is 0
      data = (self.strings_b if k == "bstr" else self.strings_t)[e[1]]
      if data:
        a.rip([0x48, 0x8D, 0x05], f"{k}:{e[1]}")         # lea rax,[object]
      else:
        a.emit(0x31, 0xC0)                               # xor eax,eax
    elif k == "var":
      self.var_load(e[1], e[2], e[3], id(e) in self.check_reads)
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
    elif k == "prime":                                   # *n
      self.expr(e[1])
      a.call("rt_isprime")                               # rax = 1 if n is prime, else 0
    elif k == "abs":                                     # |x
      self.expr(e[1])
      tx = self.tk(e[1])
      if tx == "float":
        a.emit(0x48, 0x0F, 0xBA, 0xF0, 0x3F)           # btr rax,63   (clear the sign bit)
      elif tx in ("str", "text"):                        # the length is the first word of the object; the empty string is 0
        a.emit(0x48, 0x85, 0xC0)                       # test rax,rax
        a.emit(0x74, 0x03)                             # jz  +3
        a.emit(0x48, 0x8B, 0x00)                       # mov rax,[rax]
      else:
        a.emit(0x48, 0x89, 0xC1)                       # mov rcx,rax
        a.emit(0x48, 0xC1, 0xF9, 0x3F)                 # sar rcx,63   (all ones if negative)
        a.emit(0x48, 0x31, 0xC8)                       # xor rax,rcx
        a.emit(0x48, 0x29, 0xC8)                       # sub rax,rcx
    elif k == "rand":                                    # ?x
      self.expr(e[1])
      a.call({"float": "rt_rand_float", "str": "rt_time_str", "text": "rt_time_text"}.get(self.tk(e[1]), "rt_rand_int"))
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
        if tys[i] == tys[i + 1] and tys[i] in ("str", "text"):
          a.emit(0x48, 0x89, 0x14, 0x24)             # mov [rsp],rdx   (the helper clobbers rdx; this operand is the next "previous")
          a.emit(0x48, 0x89, 0xC8)                   # mov rax,rcx     (previous string)
          a.emit(0x48, 0x89, 0xD1)                   # mov rcx,rdx     (this string)
          a.call("rt_textcmp" if tys[i] == "text" else "rt_strcmp")   # rax = -1, 0 or 1
          a.emit(0x48, 0x83, 0xF8, 0x00)             # cmp rax,0
          a.jcc(FAIL_CC[op], lf)
        elif "float" in (tys[i], tys[i + 1]):
          self.load_xmm(0, 1, tys[i])                  # previous operand (rcx) -> xmm0
          self.load_xmm(1, 2, tys[i + 1])              # this operand (rdx) -> xmm1
          self.fcmp_false(op, lf)
        else:
          a.emit(0x48, 0x39, 0xD1)                   # cmp rcx,rdx
          a.jcc(FAIL_CC[op], lf)                     # stop at the first false link
        if i < len(ops) - 1 and not (tys[i] == tys[i + 1] and tys[i] in ("str", "text")):
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
      if op == "+" and tl == tr and tl in ("str", "text"):
        a.call("rt_textcat" if tl == "text" else "rt_strcat")   # a new string: [length][contents]; empty = 0
      elif op in CMP_SETCC and tl == tr and tl in ("str", "text"):
        a.call("rt_textcmp" if tl == "text" else "rt_strcmp")   # rax = -1, 0 or 1
        a.emit(0x48, 0x83, 0xF8, 0x00)               # cmp rax,0
        a.emit(0x0F, CMP_SETCC[op], 0xC0, 0x0F, 0xB6, 0xC0)  # setcc al; movzx eax,al
      elif (op in ARITH_OPS or op == "/") and self.tk(e) == "float":   # float arithmetic; an int operand is converted
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
            a.call("rt_fmodfloor")                   # the remainder has the sign of the divisor
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
      elif op == "\\" and "float" in (tl, tr):         # integer division of floats: floor(a / b) = (a - fmod(a, b)) / b, one less if the remainder was floored
        self.load_xmm(0, 0, tl)
        self.load_xmm(1, 1, tr)
        if tr == "float":
          a.emit(0x48, 0x89, 0xCA, 0x48, 0xD1, 0xE2)     # mov rdx,rcx; shl rdx,1   (+0.0 and -0.0)
        else:
          a.emit(0x48, 0x85, 0xC9)                     # test rcx,rcx
        a.jcc(4, "rt_divzero")
        a.emit(0x66, 0x0F, 0x28, 0xD0)                 # movapd xmm2,xmm0   (a)
        a.call("rt_fmodfloor")                         # xmm4 = fmod(a, b), edx = 1 if the floored remainder differs; xmm1, xmm2 are kept
        a.emit(0xF2, 0x0F, 0x5C, 0xD4)                 # subsd xmm2,xmm4
        a.emit(0xF2, 0x0F, 0x5E, 0xD1)                 # divsd xmm2,xmm1    (the quotient toward zero; a - fmod may be rounded, so it can be 13276.999999999998)
        a.emit(0xF2, 0x48, 0x0F, 0x2D, 0xC2)           # cvtsd2si rax,xmm2  (round to the nearest integer, not toward zero)
        a.emit(0x48, 0x29, 0xD0)                       # sub rax,rdx        (floor)
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
        a.emit(0x48, 0x99, 0x48, 0xF7, 0xF9)         # cqo; idiv rcx   (rax = quotient toward zero, rdx = remainder with the sign of the dividend)
        lf = a.new_label("fl_ok")                    # floor: if the remainder is not 0 and has the other sign than the divisor,
        a.emit(0x48, 0x85, 0xD2)                     # the quotient is one less and the remainder is bigger by the divisor
        a.jcc(4, lf)                                 # test rdx,rdx; jz
        a.emit(0x49, 0x89, 0xD0)                     # mov r8,rdx
        a.emit(0x49, 0x31, 0xC8)                     # xor r8,rcx   (the sign bit tells whether the signs differ)
        a.jcc(9, lf)                                 # jns
        if op == "\\":
          a.emit(0x48, 0xFF, 0xC8)                   # dec rax
        else:
          a.emit(0x48, 0x01, 0xCA)                   # add rdx,rcx
        a.label(lf)
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
          tv = self.tk(v)
          a.call({"str": "rt_print_value_str", "text": "rt_print_value_text", "float": "rt_print_float"}.get(tv, "rt_print_int"))
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
    self.alloc_flags()
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
    self.stmts(ast)
    a.emit(0x31, 0xC9)                                   # xor ecx,ecx
    self.exit_process()
    while self.queue:                                    # user functions (may queue nested ones)
      self.gen_function(self.queue.pop(0))
    self.emit_uninit_stubs()
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

    # rt_print_value_str: rax = null (empty) or pointer to [u64 length][bytes]
    a.label("rt_print_value_str")
    empty = a.new_label("ps_empty")
    a.emit(0x48, 0x85, 0xC0)                             # test rax,rax
    a.jcc(4, empty)
    a.emit(0x48, 0x8B, 0x10)                             # mov rdx,[rax] (length)
    a.emit(0x48, 0x8D, 0x48, 0x08)                       # lea rcx,[rax+8] (contents)
    a.jmp("rt_print_str")
    a.label(empty)
    a.emit(0xC3)                                         # ret

    # rt_print_value_text: rax = null or [u64 code-point count][u32 code points].
    # The code points are encoded as UTF-8 into a 1024-byte buffer on the stack; the buffer is written with one WriteFile
    # when it is nearly full and at the end (not one call per character).
    # Registers: r8 = next code point, r9 = how many are left, r10 = next output byte, r11 = flush limit (buffer + 1020).
    # Frame: [rsp .. rsp+0x20) shadow space, [rsp+0x20] 5th argument, buffer at rsp+0x30; r8, r9 are saved at [rbp-8], [rbp-16] over WriteFile.
    t_loop, t_final, t_flush, t_done = (a.new_label(n) for n in ("pt_loop", "pt_final", "pt_flush", "pt_done"))
    t_one, t_two, t_three = (a.new_label(n) for n in ("pt_one", "pt_two", "pt_three"))
    a.label("rt_print_value_text")
    a.emit(0x55, 0x48, 0x89, 0xE5)                       # push rbp; mov rbp,rsp
    a.emit(0x48, 0x81, 0xEC, struct.pack("<I", 0x460))   # sub rsp,0x460
    a.emit(0x48, 0x83, 0xE4, 0xF0)                       # and rsp,-16
    a.emit(0x48, 0x85, 0xC0)                             # test rax,rax
    a.jcc(4, t_done)                                     # empty text: nothing to print
    a.emit(0x4C, 0x8B, 0x08)                             # mov r9,[rax]        count
    a.emit(0x4C, 0x8D, 0x40, 0x08)                       # lea r8,[rax+8]      first code point
    a.emit(0x4C, 0x8D, 0x54, 0x24, 0x30)                 # lea r10,[rsp+0x30]  buffer
    a.emit(0x4C, 0x8D, 0x9C, 0x24, struct.pack("<I", 0x30 + 1020))   # lea r11,[rsp+0x30+1020]
    a.label(t_loop)
    a.emit(0x4D, 0x85, 0xC9)                             # test r9,r9
    a.jcc(4, t_final)
    a.emit(0x4D, 0x39, 0xDA)                             # cmp r10,r11
    a.jcc(7, t_flush)                                    # ja: no room for 4 more bytes
    a.emit(0x41, 0x8B, 0x00)                             # mov eax,[r8]
    a.emit(0x49, 0x83, 0xC0, 0x04)                       # add r8,4
    a.emit(0x49, 0xFF, 0xC9)                             # dec r9
    a.emit(0x3D, struct.pack("<I", 0x80))                # cmp eax,0x80
    a.jcc(2, t_one)                                      # jb
    a.emit(0x3D, struct.pack("<I", 0x800))               # cmp eax,0x800
    a.jcc(2, t_two)
    a.emit(0x3D, struct.pack("<I", 0x10000))             # cmp eax,0x10000
    a.jcc(2, t_three)
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 18, 0x80, 0xC9, 0xF0) # four bytes: ecx = cp>>18 | 0xF0
    a.emit(0x41, 0x88, 0x0A)                             # mov [r10],cl
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 12, 0x80, 0xE1, 0x3F, 0x80, 0xC9, 0x80)   # cl = (cp>>12)&0x3F | 0x80
    a.emit(0x41, 0x88, 0x4A, 0x01)                       # mov [r10+1],cl
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 6, 0x80, 0xE1, 0x3F, 0x80, 0xC9, 0x80)    # cl = (cp>>6)&0x3F | 0x80
    a.emit(0x41, 0x88, 0x4A, 0x02)                       # mov [r10+2],cl
    a.emit(0x24, 0x3F, 0x0C, 0x80)                       # al = cp&0x3F | 0x80
    a.emit(0x41, 0x88, 0x42, 0x03)                       # mov [r10+3],al
    a.emit(0x49, 0x83, 0xC2, 0x04)                       # add r10,4
    a.jmp(t_loop)
    a.label(t_three)
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 12, 0x80, 0xC9, 0xE0) # ecx = cp>>12 | 0xE0
    a.emit(0x41, 0x88, 0x0A)                             # mov [r10],cl
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 6, 0x80, 0xE1, 0x3F, 0x80, 0xC9, 0x80)    # cl = (cp>>6)&0x3F | 0x80
    a.emit(0x41, 0x88, 0x4A, 0x01)                       # mov [r10+1],cl
    a.emit(0x24, 0x3F, 0x0C, 0x80)                       # al = cp&0x3F | 0x80
    a.emit(0x41, 0x88, 0x42, 0x02)                       # mov [r10+2],al
    a.emit(0x49, 0x83, 0xC2, 0x03)                       # add r10,3
    a.jmp(t_loop)
    a.label(t_two)
    a.emit(0x89, 0xC1, 0xC1, 0xE9, 6, 0x80, 0xC9, 0xC0)  # ecx = cp>>6 | 0xC0
    a.emit(0x41, 0x88, 0x0A)                             # mov [r10],cl
    a.emit(0x24, 0x3F, 0x0C, 0x80)                       # al = cp&0x3F | 0x80
    a.emit(0x41, 0x88, 0x42, 0x01)                       # mov [r10+1],al
    a.emit(0x49, 0x83, 0xC2, 0x02)                       # add r10,2
    a.jmp(t_loop)
    a.label(t_one)
    a.emit(0x41, 0x88, 0x02)                             # mov [r10],al
    a.emit(0x49, 0xFF, 0xC2)                             # inc r10
    a.jmp(t_loop)
    a.label(t_final)
    a.emit(0x48, 0x8D, 0x54, 0x24, 0x30)                 # lea rdx,[rsp+0x30]
    a.emit(0x49, 0x39, 0xD2)                             # cmp r10,rdx
    a.jcc(4, t_done)                                     # nothing left in the buffer
    a.label(t_flush)                                     # write the buffer, then go on (back to t_loop; at the end t_final finds it empty)
    a.emit(0x4C, 0x89, 0x45, 0xF8)                       # mov [rbp-8],r8
    a.emit(0x4C, 0x89, 0x4D, 0xF0)                       # mov [rbp-16],r9
    a.emit(0x48, 0x8D, 0x54, 0x24, 0x30)                 # lea rdx,[rsp+0x30]   buffer
    a.emit(0x4D, 0x89, 0xD0)                             # mov r8,r10
    a.emit(0x49, 0x29, 0xD0)                             # sub r8,rdx           number of bytes
    a.rip([0x48, 0x8B, 0x0D], "stdout")                  # mov rcx,[stdout]
    a.rip([0x4C, 0x8D, 0x0D], "written")                 # lea r9,[written]
    a.emit(0x48, 0xC7, 0x44, 0x24, 0x20, 0, 0, 0, 0)     # mov qword [rsp+0x20],0
    a.rip([0xFF, 0x15], "WriteFile")
    a.emit(0x4C, 0x8B, 0x45, 0xF8)                       # mov r8,[rbp-8]
    a.emit(0x4C, 0x8B, 0x4D, 0xF0)                       # mov r9,[rbp-16]
    a.emit(0x4C, 0x8D, 0x54, 0x24, 0x30)                 # lea r10,[rsp+0x30]
    a.emit(0x4C, 0x8D, 0x9C, 0x24, struct.pack("<I", 0x30 + 1020))   # lea r11,[rsp+0x30+1020]
    a.jmp(t_loop)
    a.label(t_done)
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

    # random numbers: SplitMix64, the state is the 8 bytes at "state" in .data (the initial value is written by build_pe)
    # rt_next_u64: rax = the next 64-bit number (clobbers rcx)
    a.label("rt_next_u64")
    a.rip([0x48,0x8B,0x05],"state")                      # mov rax,[state]
    a.emit(0x48,0xB9,struct.pack("<Q",0x9E3779B97F4A7C15))   # mov rcx,0x9E3779B97F4A7C15
    a.emit(0x48,0x01,0xC8)                               # add rax,rcx
    a.rip([0x48,0x89,0x05],"state")                      # mov [state],rax      z = (state += 0x9E37...)
    for shift,mult in ((30,0xBF58476D1CE4E5B9),(27,0x94D049BB133111EB)):
      a.emit(0x48,0x89,0xC1)                             # mov rcx,rax
      a.emit(0x48,0xC1,0xE9,shift)                       # shr rcx,shift
      a.emit(0x48,0x31,0xC8)                             # xor rax,rcx          z ^= z >> shift
      a.emit(0x48,0xB9,struct.pack("<Q",mult))           # mov rcx,mult
      a.emit(0x48,0x0F,0xAF,0xC1)                        # imul rax,rcx         z *= mult
    a.emit(0x48,0x89,0xC1)                               # mov rcx,rax
    a.emit(0x48,0xC1,0xE9,31)                            # shr rcx,31
    a.emit(0x48,0x31,0xC8)                               # xor rax,rcx          return z ^ (z >> 31)
    a.emit(0xC3)                                         # ret
    # rt_rand_int: rax = n  ->  n > 1: next % n;  n = 0: the next 64 bits;  n < 0: state = -n, result 0;  n = 1: the time (rt_time_us)
    a.label("rt_rand_int")
    raw,seed = a.new_label("rnd_raw"),a.new_label("rnd_seed")
    a.emit(0x48,0x85,0xC0)                               # test rax,rax
    a.jcc(4,raw)                                         # jz
    a.jcc(8,seed)                                        # js
    a.emit(0x48,0x83,0xF8,0x01)                          # cmp rax,1
    a.jcc(4,"rt_time_us")                                # je   ?1 is the time (rt_time_us returns to the caller of rt_rand_int)
    a.emit(0x49,0x89,0xC0)                               # mov r8,rax           n
    a.call("rt_next_u64")
    a.emit(0x31,0xD2)                                    # xor edx,edx
    a.emit(0x49,0xF7,0xF0)                               # div r8               unsigned: rdx = next % n
    a.emit(0x48,0x89,0xD0)                               # mov rax,rdx
    a.emit(0xC3)
    a.label(raw)
    a.call("rt_next_u64")
    a.emit(0xC3)
    a.label(seed)
    a.emit(0x48,0xF7,0xD8)                               # neg rax
    a.rip([0x48,0x89,0x05],"state")                      # mov [state],rax
    a.emit(0x31,0xC0)                                    # xor eax,eax
    a.emit(0xC3)
    # rt_rand_float: rax = bits of x  ->  bits of a double in [0, x); x must be > 0.0 (like the C function rand_float64)
    a.label("rt_rand_float")
    ok = a.new_label("rf_ok")
    a.emit(0x49,0x89,0xC0)                               # mov r8,rax           x
    a.emit(0x66,0x49,0x0F,0x6E,0xC0)                     # movq xmm0,r8
    a.emit(0x66,0x0F,0x57,0xDB)                          # xorpd xmm3,xmm3
    a.emit(0x66,0x0F,0x2E,0xC3)                          # ucomisd xmm0,xmm3
    a.jcc(6,"rt_badrand")                                # jbe  (x <= 0.0 or nan)
    a.call("rt_next_u64")
    a.emit(0x48,0xC1,0xE8,11)                            # shr rax,11           53 random bits
    a.emit(0xF2,0x48,0x0F,0x2A,0xC8)                     # cvtsi2sd xmm1,rax    (exact)
    a.emit(0x48,0xB9,struct.pack("<Q",0x3CA0000000000000))   # mov rcx,2^-53
    a.emit(0x66,0x48,0x0F,0x6E,0xD1)                     # movq xmm2,rcx
    a.emit(0xF2,0x0F,0x59,0xCA)                          # mulsd xmm1,xmm2      unit in [0,1)
    a.emit(0xF2,0x0F,0x59,0xC8)                          # mulsd xmm1,xmm0      result = unit * x
    a.emit(0x66,0x0F,0x2E,0xC8)                          # ucomisd xmm1,xmm0
    a.jcc(0xA,ok)                                        # jp   (not possible for x > 0.0, but harmless)
    a.jcc(2,ok)                                          # jb   (result < x: fine)
    a.emit(0x49,0xFF,0xC8)                               # dec r8               result >= x (rounding): the next smaller number
    a.emit(0x66,0x49,0x0F,0x6E,0xC8)                     # movq xmm1,r8
    a.label(ok)
    a.emit(0x66,0x48,0x0F,0x7E,0xC8)                     # movq rax,xmm1
    a.emit(0xC3)

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
    for label, idx in (("rt_divzero", 1), ("rt_notfn", 2), ("rt_negexp", 3), ("rt_badpow", 4), ("rt_badrand", 5), ("rt_nomem", 6)):
      a.label(label)
      a.rip([0x48, 0x8D, 0x0D], f"str:{idx}")
      a.emit(0xBA, struct.pack("<I", len(self.strings[idx])))
      a.call("rt_print_str")
      a.emit(0xB9, 1, 0, 0, 0)                         # mov ecx,1
      self.exit_process()

    # rt_strcmp: rax = left string, rcx = right string -> rax = -1, 0 or 1.
    # Strings are [u64 byte length][bytes]; null is the empty string.
    a.label("rt_strcmp")
    a.emit(prologue)
    a.emit(0x49, 0x89, 0xC0)                           # mov r8,rax (left object)
    left_empty = a.new_label("sc_left_empty")
    right_empty = a.new_label("sc_right_empty")
    sc_loop = a.new_label("sc_loop")
    sc_lengths = a.new_label("sc_lengths")
    sc_less = a.new_label("sc_less")
    sc_greater = a.new_label("sc_greater")
    sc_done = a.new_label("sc_done")
    sc_same = a.new_label("sc_same")
    a.emit(0x48, 0x39, 0xC8)                           # cmp rax,rcx (same immutable object => equal)
    a.jcc(4, sc_same)
    a.emit(0x4D, 0x85, 0xC0)                           # test r8,r8 (left pointer is null?)
    a.jcc(4, left_empty)
    a.emit(0x49, 0x8B, 0x10)                           # mov rdx,[r8] (left length)
    a.emit(0x4D, 0x8D, 0x40, 0x08)                     # lea r8,[r8+8] (left bytes)
    a.jmp(sc_lengths + "_left")
    a.label(left_empty)
    a.emit(0x31, 0xD2, 0x4D, 0x31, 0xC0)               # xor edx,edx; xor r8,r8
    a.label(sc_lengths + "_left")
    a.emit(0x49, 0x89, 0xC9)                           # mov r9,rcx (right object)
    a.emit(0x4D, 0x85, 0xC9)                           # test r9,r9
    a.jcc(4, right_empty)
    a.emit(0x4D, 0x8B, 0x11)                           # mov r10,[r9] (right length)
    a.emit(0x4D, 0x8D, 0x49, 0x08)                     # lea r9,[r9+8] (right bytes)
    a.jmp(sc_lengths)
    a.label(right_empty)
    a.emit(0x45, 0x31, 0xD2, 0x4D, 0x31, 0xC9)         # xor r10d,r10d; xor r9,r9
    a.label(sc_lengths)
    a.label(sc_loop)
    a.emit(0x48, 0x85, 0xD2)                           # test rdx,rdx
    a.jcc(4, sc_lengths + "_end")
    a.emit(0x4D, 0x85, 0xD2)                           # test r10,r10
    a.jcc(4, sc_lengths + "_end")
    a.emit(0x41, 0x0F, 0xB6, 0x00)                     # movzx eax,byte [r8]
    a.emit(0x41, 0x0F, 0xB6, 0x09)                     # movzx ecx,byte [r9]
    a.emit(0x39, 0xC8)                                 # cmp eax,ecx (unsigned byte values)
    a.jcc(2, sc_less)                                  # jb
    a.jcc(7, sc_greater)                               # ja
    a.emit(0x49, 0xFF, 0xC0, 0x49, 0xFF, 0xC1)         # inc r8; inc r9
    a.emit(0x48, 0xFF, 0xCA, 0x49, 0xFF, 0xCA)         # dec rdx; dec r10
    a.jmp(sc_loop)
    a.label(sc_lengths + "_end")
    a.emit(0x4C, 0x39, 0xD2)                           # cmp rdx,r10 (remaining lengths)
    a.jcc(2, sc_less)                                  # jb
    a.jcc(7, sc_greater)                               # ja
    a.label(sc_same)
    a.emit(0x31, 0xC0)                                 # xor eax,eax
    a.jmp(sc_done)
    a.label(sc_less)
    a.emit(0x48, 0xC7, 0xC0, 0xFF, 0xFF, 0xFF, 0xFF)   # mov rax,-1 (sign-extended)
    a.jmp(sc_done)
    a.label(sc_greater)
    a.emit(0xB8, 1, 0, 0, 0)                           # mov eax,1
    a.label(sc_done)
    a.emit(epilogue)

    # rt_strcat: rax = left, rcx = right -> a newly allocated [length][bytes] object.
    # Old strings are intentionally not freed; empty result is the null pointer.
    a.label("rt_strcat")
    a.emit(prologue)
    a.emit(0x48, 0x89, 0x45, 0xF8)                     # mov [rbp-8],rax (left object)
    a.emit(0x48, 0x89, 0x4D, 0xF0)                     # mov [rbp-16],rcx (right object)
    a.emit(0x31, 0xD2)                                 # xor edx,edx
    a.emit(0x48, 0x85, 0xC0)                           # test rax,rax
    cat_left_empty = a.new_label("cat_left_empty")
    cat_right_empty = a.new_label("cat_right_empty")
    cat_empty = a.new_label("cat_empty")
    cat_left_loop = a.new_label("cat_left_loop")
    cat_right_setup = a.new_label("cat_right_setup")
    cat_right_loop = a.new_label("cat_right_loop")
    cat_finish = a.new_label("cat_finish")
    cat_done = a.new_label("cat_done")
    a.jcc(4, cat_left_empty)
    a.emit(0x48, 0x8B, 0x10)                           # mov rdx,[rax]
    a.label(cat_left_empty)
    a.emit(0x48, 0x89, 0x55, 0xE8)                     # mov [rbp-24],rdx (left length)
    a.emit(0x31, 0xD2)                                 # xor edx,edx
    a.emit(0x48, 0x8B, 0x4D, 0xF0)                     # mov rcx,[rbp-16]
    a.emit(0x48, 0x85, 0xC9)                           # test rcx,rcx
    a.jcc(4, cat_right_empty)
    a.emit(0x48, 0x8B, 0x11)                           # mov rdx,[rcx]
    a.label(cat_right_empty)
    a.emit(0x48, 0x89, 0x55, 0xE0)                     # mov [rbp-32],rdx (right length)
    a.emit(0x48, 0x8B, 0x45, 0xE8)                     # mov rax,[rbp-24]
    a.emit(0x48, 0x03, 0x45, 0xE0)                     # add rax,[rbp-32]
    a.emit(0x48, 0x85, 0xC0)                           # test rax,rax
    a.jcc(4, cat_empty)
    a.emit(0x48, 0x89, 0x45, 0xD8)                     # mov [rbp-40],rax (total length)
    a.emit(0x48, 0x8D, 0x48, 0x08)                     # lea rcx,[rax+8] (allocation size)
    a.call("rt_alloc")
    a.emit(0x48, 0x8B, 0x55, 0xD8)                     # mov rdx,[rbp-40]
    a.emit(0x48, 0x89, 0x10)                           # mov [rax],rdx (length)
    a.emit(0x48, 0x89, 0x45, 0xD0)                     # mov [rbp-48],rax (result object)
    a.emit(0x49, 0x89, 0xC2)                           # mov r10,rax (result object)
    a.emit(0x49, 0x83, 0xC2, 0x08)                     # add r10,8 (destination)
    a.emit(0x48, 0x8B, 0x45, 0xF8)                     # mov rax,[rbp-8]
    a.emit(0x48, 0x85, 0xC0)                           # test rax,rax
    a.jcc(4, cat_right_setup)
    a.emit(0x4C, 0x8D, 0x40, 0x08)                     # lea r8,[rax+8]
    a.emit(0x48, 0x8B, 0x55, 0xE8)                     # mov rdx,[rbp-24]
    a.label(cat_left_loop)
    a.emit(0x48, 0x85, 0xD2)                           # test rdx,rdx
    a.jcc(4, cat_right_setup)
    a.emit(0x41, 0x8A, 0x08, 0x41, 0x88, 0x0A)         # mov cl,[r8]; mov [r10],cl
    a.emit(0x49, 0xFF, 0xC0, 0x49, 0xFF, 0xC2)         # inc r8; inc r10
    a.emit(0x48, 0xFF, 0xCA)                           # dec rdx
    a.jmp(cat_left_loop)
    a.label(cat_right_setup)
    a.emit(0x48, 0x8B, 0x45, 0xF0)                     # mov rax,[rbp-16]
    a.emit(0x48, 0x85, 0xC0)                           # test rax,rax
    a.jcc(4, cat_finish)
    a.emit(0x4C, 0x8D, 0x40, 0x08)                     # lea r8,[rax+8]
    a.emit(0x48, 0x8B, 0x55, 0xE0)                     # mov rdx,[rbp-32]
    a.label(cat_right_loop)
    a.emit(0x48, 0x85, 0xD2)                           # test rdx,rdx
    a.jcc(4, cat_finish)
    a.emit(0x41, 0x8A, 0x08, 0x41, 0x88, 0x0A)         # mov cl,[r8]; mov [r10],cl
    a.emit(0x49, 0xFF, 0xC0, 0x49, 0xFF, 0xC2)         # inc r8; inc r10
    a.emit(0x48, 0xFF, 0xCA)                           # dec rdx
    a.jmp(cat_right_loop)
    a.label(cat_finish)
    a.emit(0x48, 0x8B, 0x45, 0xD0)                     # mov rax,[rbp-48]
    a.jmp(cat_done)
    a.label(cat_empty)
    a.emit(0x31, 0xC0)                                 # xor eax,eax
    a.label(cat_done)
    a.emit(epilogue)

    # rt_textcmp: rax = left, rcx = right -> -1/0/1; lexicographical Unicode code-point order.
    # Objects are [u64 code-point length][u32 code points]; null is empty.
    a.label("rt_textcmp")
    a.emit(prologue)
    a.emit(0x49, 0x89, 0xC0)                           # mov r8,rax
    tx_left_empty = a.new_label("tc_left_empty")
    tx_right_empty = a.new_label("tc_right_empty")
    tx_loop = a.new_label("tc_loop")
    tx_end = a.new_label("tc_end")
    tx_less = a.new_label("tc_less")
    tx_greater = a.new_label("tc_greater")
    tx_same = a.new_label("tc_same")
    tx_done = a.new_label("tc_done")
    a.emit(0x48, 0x39, 0xC8)                           # cmp rax,rcx
    a.jcc(4, tx_same)
    a.emit(0x4D, 0x85, 0xC0)                           # test r8,r8
    a.jcc(4, tx_left_empty)
    a.emit(0x49, 0x8B, 0x10)                           # mov rdx,[r8]
    a.emit(0x4D, 0x8D, 0x40, 0x08)                     # lea r8,[r8+8]
    a.jmp("tc_left_ready")
    a.label(tx_left_empty)
    a.emit(0x31, 0xD2, 0x4D, 0x31, 0xC0)               # zero length and pointer
    a.label("tc_left_ready")
    a.emit(0x49, 0x89, 0xC9)                           # mov r9,rcx
    a.emit(0x4D, 0x85, 0xC9)
    a.jcc(4, tx_right_empty)
    a.emit(0x4D, 0x8B, 0x11)                           # mov r10,[r9]
    a.emit(0x4D, 0x8D, 0x49, 0x08)                     # lea r9,[r9+8]
    a.jmp(tx_loop)
    a.label(tx_right_empty)
    a.emit(0x45, 0x31, 0xD2, 0x4D, 0x31, 0xC9)
    a.label(tx_loop)
    a.emit(0x48, 0x85, 0xD2)
    a.jcc(4, tx_end)
    a.emit(0x4D, 0x85, 0xD2)
    a.jcc(4, tx_end)
    a.emit(0x41, 0x8B, 0x00)                           # mov eax,[r8]
    a.emit(0x41, 0x8B, 0x09)                           # mov ecx,[r9]
    a.emit(0x39, 0xC8)                                 # cmp eax,ecx (unsigned code points)
    a.jcc(2, tx_less)
    a.jcc(7, tx_greater)
    a.emit(0x49, 0x83, 0xC0, 0x04, 0x49, 0x83, 0xC1, 0x04)
    a.emit(0x48, 0xFF, 0xCA, 0x49, 0xFF, 0xCA)
    a.jmp(tx_loop)
    a.label(tx_end)
    a.emit(0x4C, 0x39, 0xD2)
    a.jcc(2, tx_less)
    a.jcc(7, tx_greater)
    a.label(tx_same)
    a.emit(0x31, 0xC0)
    a.jmp(tx_done)
    a.label(tx_less)
    a.emit(0x48, 0xC7, 0xC0, 0xFF, 0xFF, 0xFF, 0xFF)
    a.jmp(tx_done)
    a.label(tx_greater)
    a.emit(0xB8, 1, 0, 0, 0)
    a.label(tx_done)
    a.emit(epilogue)

    # rt_textcat: allocate [u64 code-point length][u32 code points]; old values are not freed.
    a.label("rt_textcat")
    a.emit(prologue)
    a.emit(0x48, 0x89, 0x45, 0xF8)                     # left object
    a.emit(0x48, 0x89, 0x4D, 0xF0)                     # right object
    a.emit(0x31, 0xD2, 0x48, 0x85, 0xC0)
    tx_cat_left_empty = a.new_label("tc_cat_left_empty")
    tx_cat_right_empty = a.new_label("tc_cat_right_empty")
    tx_cat_empty = a.new_label("tc_cat_empty")
    tx_cat_left_loop = a.new_label("tc_cat_left_loop")
    tx_cat_right_setup = a.new_label("tc_cat_right_setup")
    tx_cat_right_loop = a.new_label("tc_cat_right_loop")
    tx_cat_finish = a.new_label("tc_cat_finish")
    tx_cat_done = a.new_label("tc_cat_done")
    a.jcc(4, tx_cat_left_empty)
    a.emit(0x48, 0x8B, 0x10)                           # left length
    a.label(tx_cat_left_empty)
    a.emit(0x48, 0x89, 0x55, 0xE8)                     # save left length
    a.emit(0x31, 0xD2, 0x48, 0x8B, 0x4D, 0xF0, 0x48, 0x85, 0xC9)
    a.jcc(4, tx_cat_right_empty)
    a.emit(0x48, 0x8B, 0x11)                           # right length
    a.label(tx_cat_right_empty)
    a.emit(0x48, 0x89, 0x55, 0xE0)                     # save right length
    a.emit(0x48, 0x8B, 0x45, 0xE8, 0x48, 0x03, 0x45, 0xE0)
    a.emit(0x48, 0x85, 0xC0)
    a.jcc(4, tx_cat_empty)
    a.emit(0x48, 0x89, 0x45, 0xD8)                     # total code-point count
    a.emit(0x48, 0x89, 0xC1, 0x48, 0xC1, 0xE1, 0x02, 0x48, 0x83, 0xC1, 0x08) # bytes = 8 + count*4
    a.call("rt_alloc")
    a.emit(0x48, 0x8B, 0x55, 0xD8, 0x48, 0x89, 0x10)  # store code-point length
    a.emit(0x48, 0x89, 0x45, 0xD0, 0x49, 0x89, 0xC2, 0x49, 0x83, 0xC2, 0x08)
    a.emit(0x48, 0x8B, 0x45, 0xF8, 0x48, 0x85, 0xC0)
    a.jcc(4, tx_cat_right_setup)
    a.emit(0x4C, 0x8D, 0x40, 0x08, 0x48, 0x8B, 0x55, 0xE8)
    a.label(tx_cat_left_loop)
    a.emit(0x48, 0x85, 0xD2)
    a.jcc(4, tx_cat_right_setup)
    a.emit(0x41, 0x8B, 0x08, 0x41, 0x89, 0x0A)       # copy one u32 code point
    a.emit(0x49, 0x83, 0xC0, 0x04, 0x49, 0x83, 0xC2, 0x04, 0x48, 0xFF, 0xCA)
    a.jmp(tx_cat_left_loop)
    a.label(tx_cat_right_setup)
    a.emit(0x48, 0x8B, 0x45, 0xF0, 0x48, 0x85, 0xC0)
    a.jcc(4, tx_cat_finish)
    a.emit(0x4C, 0x8D, 0x40, 0x08, 0x48, 0x8B, 0x55, 0xE0)
    a.label(tx_cat_right_loop)
    a.emit(0x48, 0x85, 0xD2)
    a.jcc(4, tx_cat_finish)
    a.emit(0x41, 0x8B, 0x08, 0x41, 0x89, 0x0A)
    a.emit(0x49, 0x83, 0xC0, 0x04, 0x49, 0x83, 0xC2, 0x04, 0x48, 0xFF, 0xCA)
    a.jmp(tx_cat_right_loop)
    a.label(tx_cat_finish)
    a.emit(0x48, 0x8B, 0x45, 0xD0)
    a.jmp(tx_cat_done)
    a.label(tx_cat_empty)
    a.emit(0x31, 0xC0)
    a.label(tx_cat_done)
    a.emit(epilogue)

    # rt_alloc: rcx = size in bytes -> rax = zeroed memory from the process heap
    a.label("rt_alloc")
    a.emit(prologue)
    a.emit(0x49, 0x89, 0xC8)                             # mov r8,rcx
    a.rip([0x48, 0x8B, 0x0D], "heap")                    # mov rcx,[heap]
    a.emit(0xBA, 8, 0, 0, 0)                             # mov edx,HEAP_ZERO_MEMORY
    a.rip([0xFF, 0x15], "HeapAlloc")
    a.emit(0x48, 0x85, 0xC0)                             # test rax,rax
    a.jcc(4, "rt_nomem")                                 # HeapAlloc failed: runtime error, exit code 1
    a.emit(epilogue)

    # ---- time (version 6.9). The computing routines are TIME_RT (tools/time_rt.asm); these three call Windows and allocate.
    def frame(size):                                       # push rbp; mov rbp,rsp; sub rsp,size; and rsp,-16
      a.emit(0x55,0x48,0x89,0xE5,0x48,0x81,0xEC,struct.pack("<I",size),0x48,0x83,0xE4,0xF0)

    # rt_time_us: -> rax = microseconds since 1970-01-01 UTC. FILETIME counts 100 ns from 1601: (t - 116444736000000000) / 10
    a.label("rt_time_us")
    frame(0x30)
    a.emit(0x48,0x8D,0x4C,0x24,0x20)                 # lea rcx,[rsp+0x20]
    a.rip([0xFF,0x15],"GetSystemTimePreciseAsFileTime")
    a.emit(0x48,0x8B,0x44,0x24,0x20)                 # mov rax,[rsp+0x20]
    a.emit(0x48,0xB9,struct.pack("<Q",116444736000000000)) # mov rcx,(1970 - 1601) in 100 ns
    a.emit(0x48,0x29,0xC8)                           # sub rax,rcx
    a.emit(0xB9,10,0,0,0)                            # mov ecx,10
    a.emit(0x31,0xD2)                                # xor edx,edx
    a.emit(0x48,0xF7,0xF1)                           # div rcx
    a.emit(epilogue)

    # rt_time_text: rax = format (a text object or 0) -> rax = the local time as a new text object (0 if empty)
    # Frame: SYSTEMTIME at rsp+0x20, 64 code points of result at rsp+0x30.
    a.label("rt_time_text")
    tt_skip, tt_empty, tt_end = a.new_label("tt_skip"), a.new_label("tt_empty"), a.new_label("tt_end")
    frame(0x160)
    a.emit(0x48,0x89,0x45,0xF8)                      # mov [rbp-8],rax      format
    a.emit(0x48,0x8D,0x4C,0x24,0x20)                 # lea rcx,[rsp+0x20]
    a.rip([0xFF,0x15],"GetLocalTime")
    a.emit(0x48,0x8B,0x45,0xF8)                      # mov rax,[rbp-8]
    a.emit(0x31,0xC9)                                # xor ecx,ecx          no format
    a.emit(0x48,0x85,0xC0)                           # test rax,rax
    a.jcc(4,tt_skip)
    a.emit(0x48,0x8B,0x08)                           # mov rcx,[rax]        number of code points
    a.emit(0x48,0x8D,0x70,0x08)                      # lea rsi,[rax+8]
    a.label(tt_skip)
    a.emit(0x48,0x8D,0x54,0x24,0x20)                 # lea rdx,[rsp+0x20]   SYSTEMTIME
    a.emit(0x48,0x8D,0x7C,0x24,0x30)                 # lea rdi,[rsp+0x30]   result
    a.call("rt_time_format")                         # rax = number of code points
    a.emit(0x48,0x85,0xC0)                           # test rax,rax
    a.jcc(4,tt_empty)
    a.emit(0x48,0x89,0x45,0xF0)                      # mov [rbp-16],rax
    a.emit(0x48,0x89,0xC1,0x48,0xC1,0xE1,0x02,0x48,0x83,0xC1,0x08)# rcx = 8 + 4 * count
    a.call("rt_alloc")
    a.emit(0x48,0x8B,0x4D,0xF0)                      # mov rcx,[rbp-16]
    a.emit(0x48,0x89,0x08)                           # mov [rax],rcx        length
    a.emit(0x48,0x8D,0x74,0x24,0x30)                 # lea rsi,[rsp+0x30]
    a.emit(0x48,0x8D,0x78,0x08)                      # lea rdi,[rax+8]
    a.emit(0xF3,0xA5)                                # rep movsd
    a.jmp(tt_end)
    a.label(tt_empty)
    a.emit(0x31,0xC0)                                # xor eax,eax
    a.label(tt_end)
    a.emit(epilogue)

    # rt_time_str: rax = format (a str object or 0) -> rax = the local time as a new str object (0 if empty).
    # The format is converted to text (at most 128 code points: enough for 64 result characters), the time is made as text, and
    # the result is converted back to UTF-8. Frame: SYSTEMTIME rsp+0x20, format text rsp+0x30 (512 bytes), result text rsp+0x230 (256),
    # UTF-8 result rsp+0x330 (256).
    a.label("rt_time_str")
    ts_skip, ts_empty, ts_end = a.new_label("ts_skip"), a.new_label("ts_empty"), a.new_label("ts_end")
    frame(0x460)
    a.emit(0x48,0x89,0x45,0xF8)                      # mov [rbp-8],rax      format
    a.emit(0x48,0x8D,0x4C,0x24,0x20)                 # lea rcx,[rsp+0x20]
    a.rip([0xFF,0x15],"GetLocalTime")
    a.emit(0x48,0x8B,0x45,0xF8)                      # mov rax,[rbp-8]
    a.emit(0x31,0xC9)                                # xor ecx,ecx          no format
    a.emit(0x48,0x85,0xC0)                           # test rax,rax
    a.jcc(4,ts_skip)
    a.emit(0x48,0x8B,0x08)                           # mov rcx,[rax]        number of bytes
    a.emit(0x48,0x8D,0x70,0x08)                      # lea rsi,[rax+8]
    a.emit(0x48,0x8D,0x7C,0x24,0x30)                 # lea rdi,[rsp+0x30]
    a.emit(0xBA,128,0,0,0)                           # mov edx,128
    a.call("rt_utf8_to_text")                        # rax = number of code points
    a.emit(0x48,0x89,0xC1)                           # mov rcx,rax
    a.label(ts_skip)
    a.emit(0x48,0x8D,0x74,0x24,0x30)                 # lea rsi,[rsp+0x30]   format as text
    a.emit(0x48,0x8D,0x54,0x24,0x20)                 # lea rdx,[rsp+0x20]   SYSTEMTIME
    a.emit(0x48,0x8D,0xBC,0x24,struct.pack("<I",0x230))# lea rdi,[rsp+0x230]  result as text
    a.call("rt_time_format")                         # rax = number of code points
    a.emit(0x48,0x85,0xC0)                           # test rax,rax
    a.jcc(4,ts_empty)
    a.emit(0x48,0x89,0xC1)                           # mov rcx,rax
    a.emit(0x48,0x8D,0xB4,0x24,struct.pack("<I",0x230))# lea rsi,[rsp+0x230]
    a.emit(0x48,0x8D,0xBC,0x24,struct.pack("<I",0x330))# lea rdi,[rsp+0x330]  result as UTF-8
    a.call("rt_text_to_utf8")                        # rax = number of bytes
    a.emit(0x48,0x89,0x45,0xF0)                      # mov [rbp-16],rax
    a.emit(0x48,0x8D,0x48,0x08)                      # lea rcx,[rax+8]
    a.call("rt_alloc")
    a.emit(0x48,0x8B,0x4D,0xF0)                      # mov rcx,[rbp-16]
    a.emit(0x48,0x89,0x08)                           # mov [rax],rcx        length
    a.emit(0x48,0x8D,0xB4,0x24,struct.pack("<I",0x330))# lea rsi,[rsp+0x330]
    a.emit(0x48,0x8D,0x78,0x08)                      # lea rdi,[rax+8]
    a.emit(0xF3,0xA4)                                # rep movsb
    a.jmp(ts_end)
    a.label(ts_empty)
    a.emit(0x31,0xC0)                                # xor eax,eax
    a.label(ts_end)
    a.emit(epilogue)

    for name, blob in TIME_RT.items():                   # rt_utf8_to_text, rt_text_to_utf8, rt_time_format: machine code from tools/time_rt.asm
      a.label(name)
      a.emit(blob)

    for name, blob in INT_RT.items():                    # rt_isprime: machine code from tools/int_rt.asm
      a.label(name)
      a.emit(blob)

    for name, blob in FLOAT_RT.items():                   # rt_fmt_float, rt_fpow, rt_fmod: machine code from tools/float_rt.asm
      a.label(name)
      a.emit(blob)

    # rt_fmodfloor: xmm0 = x, xmm1 = y (not 0)  ->  xmm0 = x mod y with the sign of y (floored; a zero result is +0.0),
    # xmm4 = fmod(x, y) (sign of x), edx = 1 if the floored remainder differs from fmod. Keeps xmm1, xmm2; clobbers xmm3, rax, rcx.
    a.label("rt_fmodfloor")
    done, zero = a.new_label("fm_done"), a.new_label("fm_zero")
    a.call("rt_fmod")
    a.emit(0x66, 0x0F, 0x28, 0xE0)                       # movapd xmm4,xmm0
    a.emit(0x31, 0xD2)                                   # xor edx,edx
    a.emit(0x66, 0x0F, 0x57, 0xDB)                       # xorpd xmm3,xmm3
    a.emit(0x66, 0x0F, 0x2E, 0xC3)                       # ucomisd xmm0,xmm3
    a.jcc(0xA, done)                                     # jp   (nan)
    a.jcc(4, zero)                                       # je   (remainder 0)
    a.emit(0x66, 0x48, 0x0F, 0x7E, 0xC0)                 # movq rax,xmm0
    a.emit(0x66, 0x48, 0x0F, 0x7E, 0xC9)                 # movq rcx,xmm1
    a.emit(0x48, 0x31, 0xC8)                             # xor rax,rcx   (do the signs differ?)
    a.jcc(9, done)                                       # jns
    a.emit(0xF2, 0x0F, 0x58, 0xC1)                       # addsd xmm0,xmm1
    a.emit(0xBA, 1, 0, 0, 0)                             # mov edx,1
    a.jmp(done)
    a.label(zero)
    a.emit(0x66, 0x0F, 0x57, 0xC0)                       # xorpd xmm0,xmm0   (+0.0)
    a.label(done)
    a.emit(0xC3)                                         # ret


# ----------------------------------------------------------------------------
# PE32+ writer
# ----------------------------------------------------------------------------
IMAGE_BASE = 0x140000000
SECT_ALIGN = 0x1000
FILE_ALIGN = 0x200
IMPORTS = ["GetStdHandle", "WriteFile", "SetConsoleOutputCP", "ExitProcess", "GetProcessHeap", "HeapAlloc", "GetSystemTimePreciseAsFileTime", "GetLocalTime"]


def align(x, a):
  return (x + a - 1) // a * a


def build_pe(asm, vars_, strings, byte_strings, text_strings):
  # ---- .data layout: fixed runtime area, then variables, then strings
  sym = {"stdout": 0, "stdin": 8, "written": 0x10, "heap": 0x18, "numbuf_end": 0x40, "state": 0x40}
  off = 0x80
  for name, idx in vars_.items():
    sym["var:" + name] = off + idx * 8
  off += len(vars_) * 8
  for name in asm.static_closures:                            # 16 bytes each: [code, nparams]
    sym[name] = off
    off += 16
  data = bytearray(off)
  data[0x40:0x48] = struct.pack("<Q",0x123456789ABCDEF0)       # the state of the random generator at the start of every program
  for i, s in enumerate(strings):
    sym[f"str:{i}"] = len(data)
    data += s + b"\0"
  for tag, objs in (("bstr", byte_strings), ("btext", text_strings)):   # static string objects, 8-aligned
    for i, s in enumerate(objs):
      if not s:
        continue                                  # the empty string is 0: no object
      while len(data) % 8:
        data.append(0)
      sym[f"{tag}:{i}"] = len(data)
      if tag == "bstr":
        data += struct.pack("<Q", len(s)) + s
      else:
        data += struct.pack("<Q", len(s)) + struct.pack("<" + "I" * len(s), *s)
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
  init = InitCheck(parser.global_scope)
  init.run(ast)
  asm = CodeGen(parser.global_scope, parser.strings, parser.byte_strings, parser.text_strings, parser.fn_globals,
                checker.types, init).program(ast)
  return build_pe(asm, parser.vars, parser.strings, parser.byte_strings, parser.text_strings)


def run_exe(path):
  """run a compiled program (Windows only) and return its exit code"""
  if os.name != "nt":
    print("kota: cannot run a Windows .exe on this system", file=sys.stderr)
    return 1
  return subprocess.call([os.path.abspath(path)])


def main():
  ap = argparse.ArgumentParser(description="Compile a Kota program to a Windows x64 .exe (and run it with -e or -c)")
  ap.add_argument("source", nargs="?", help="the Kota source file (.ko)")
  ap.add_argument("-o", "--output", help="the name of the .exe")
  ap.add_argument( "-e", "--execute", action="store_true",
                   help="compile, run the .exe, delete it (the exit code is the one of the program)" )
  ap.add_argument("-k", "--keep", action="store_true", help="with -e or -c: do not delete the .exe")
  ap.add_argument( "-c", "--command", metavar="TEXT",
                   help="Kota source text instead of a file: compile, run, delete (like python -c)" )
  args = ap.parse_args()
  if args.command is not None and args.source:
    ap.error("a source file and -c cannot be used together")
  if args.command is None and not args.source:
    ap.error("a source file or -c is required")
  run = args.execute or args.command is not None
  if args.keep and not run:
    ap.error("-k is used together with -e or -c")
  name = args.source if args.command is None else "<command>"
  warnings = []
  try:
    if args.command is None:
      with open(args.source, encoding="utf-8") as f:
        text = f.read()
    else:
      text = args.command
    exe = compile_source(text, warnings)
  except CompileError as e:
    print(f"{name}: error: {e}", file=sys.stderr)
    return 1
  for w in warnings:
    print(f"{name}: warning: {w}", file=sys.stderr)
  out = args.output
  if out is None and (args.keep or not run):             # where the .exe stays: next to the source, or yyyymmdd_HHMMSS.exe for -c
    out = (os.path.splitext(args.source)[0] if args.command is None else time.strftime("%Y%m%d_%H%M%S")) + ".exe"
  temp = out is None                                     # run and delete: a file in the temp directory
  if temp:
    fd, out = tempfile.mkstemp(suffix=".exe", prefix="kota_")
    os.close(fd)
  with open(out, "wb") as f:
    f.write(exe)
  if not run:
    print(f"wrote {out} ({len(exe)} bytes)")
    return 0
  try:
    code = run_exe(out)
  finally:
    if args.keep:
      print(f"kept {out}", file=sys.stderr)
    else:
      try:
        os.remove(out)
      except OSError:
        pass
  return code


if __name__ == "__main__":
  sys.exit(main())
