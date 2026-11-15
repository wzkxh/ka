#!/usr/bin/env python3
"""Dev tool: add result comments to the test programs (tests/*.ka), taken from what the compiled program really does.
  python tools/annotate_tests.py [name ...] [--whole-output]
- a `print ...` statement at the start of a line gets `-- => <its output>` (when it prints exactly one line);
- a `err_*.ka` test gets `-- ERROR: <expected message>` on the line where the compiler reports the error;
- an `exit N` line of a test with an .exit file gets `-- => exit code N`;
- with --whole-output, a test with output that no comment explains gets the whole output as a comment block at the end.
Lines that already have a `=>` / `ERROR:` note are left alone, so it can be run again after adding tests. Needs unicorn (emulator)."""
import glob, os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import ka, emu

TESTS = os.path.join(HERE, "..", "tests") + os.sep
CONT = tuple(",(+-*/%^&|~!?=<>\\")


def split_comment(line):
  """-> (index of the `--` that starts the comment or -1, comment text)"""
  i, q = 0, None
  while i < len(line):
    c = line[i]
    if q:
      if c == "^":
        i += 2
        continue
      if c == q:
        q = None
    elif c in "\"'":
      q = c
    elif line.startswith("--", i):
      return i, line[i + 2:].strip()
    i += 1
  return -1, ""


def has_semicolon(code):
  q, i = None, 0
  while i < len(code):
    c = code[i]
    if q:
      if c == "^":
        i += 2
        continue
      if c == q:
        q = None
    elif c in "\"'":
      q = c
    elif c == ";":
      return True
    i += 1
  return False


def run_src(src):
  with tempfile.TemporaryDirectory() as d:
    exe = os.path.join(d, "t.exe")
    open(exe, "wb").write(ka.compile_source(src))
    return emu.run_pe(exe)


def print_lines(lines, stripped):
  for i, line in enumerate(lines):
    if not line.startswith("print") or (len(line) > 5 and line[5] != " ") or stripped[i][:5] != "print" or "--[[" in line:
      continue
    idx, _ = split_comment(line)
    code = (line if idx < 0 else line[:idx]).rstrip()
    if has_semicolon(code) or code.endswith(CONT) or code.count("(") != code.count(")") or code.count("{") != code.count("}"):
      continue
    if i + 1 < len(lines) and lines[i + 1][:1] in (" ", "\t"):
      continue
    yield i, code


def annotate_runtime_test(name, whole_output):
  path = TESTS + name + ".ka"
  lines = open(path, newline="").read().split("\n")
  stripped = ka.strip_comments("\n".join(lines)).split("\n")
  cands = list(print_lines(lines, stripped))
  inst = list(lines)
  for n, (i, code) in enumerate(cands):                  # mark every candidate print with a unique marker in the output
    args = code[5:].strip()
    inst[i] = f"print '^01' '{n}' '^02'" + (f", {args}" if args else "")
  out, _, _ = run_src("\n".join(inst))
  parts = re.split(rb"\x01(\d+)\x02", out)
  segs, counts = {}, {}
  for k in range(1, len(parts), 2):
    n = int(parts[k])
    counts[n] = counts.get(n, 0) + 1
    segs[n] = parts[k + 1]
  exit_path = TESTS + name + ".exit"
  exit_code = int(open(exit_path).read()) if os.path.exists(exit_path) else 0
  new, explained = list(lines), 0
  for n, (i, code) in enumerate(cands):
    seg = segs.get(n, b"")
    if counts.get(n) != 1 or not seg.endswith(b"\n") or seg.count(b"\n") != 1:
      continue
    try:
      text = seg[:-1].decode("utf-8")
    except UnicodeDecodeError:
      continue
    if "\r" in text or (text and not text.isprintable()) or len(text) > 100:
      continue
    text = text or "(empty line)"
    explained += 1
    idx, old = split_comment(lines[i])
    if idx >= 0 and ("=>" in old or text in old):          # already said (by a person or an earlier run)
      continue
    if text.startswith("runtime error") and exit_code:
      text += f" (exit code {exit_code})"
    if idx >= 0:
      new[i] = lines[i][:idx] + f"-- => {text}" + (f"  ({old})" if old else "")
    else:
      new[i] = lines[i].rstrip() + f"  -- => {text}"
  for i, line in enumerate(new):
    if line.startswith("exit ") and exit_code and "=>" not in line:
      idx, old = split_comment(line)
      new[i] = (line.rstrip() if idx < 0 else line[:idx].rstrip()) + f"  -- => exit code {exit_code}" + (f"  ({old})" if old else "")
  if whole_output and "-- the whole output:" not in "\n".join(new):
    exp = open(TESTS + name + ".expected", "rb").read().decode("utf-8", "replace").split("\n")
    exp = exp[:-1] if exp and exp[-1] == "" else exp
    if len(exp) > explained and len(exp) <= 24 and all(l.isprintable() for l in exp):
      while new and new[-1] == "":
        new.pop()
      new += ["", "-- the whole output:"] + [("--   " + l).rstrip() for l in exp] + [""]
  return new, lines


def annotate_error_test(name):
  path = TESTS + name + ".ka"
  src = open(path, newline="").read()
  if "ERROR:" in src:
    return None
  want = open(TESTS + name + ".error").read().strip()
  try:
    ka.compile_source(src)
    return None
  except ka.CompileError as e:
    msg = str(e)
  m = re.match(r"line (\d+): ", msg)
  lines = src.split("\n")
  if not m or int(m.group(1)) > len(lines) or not lines[int(m.group(1)) - 1].strip():
    print("  put the note on another line by hand:", name)
    return None
  n = int(m.group(1)) - 1
  idx, old = split_comment(lines[n])
  note = f"-- ERROR: {want}" + (f"  ({old})" if old else "")
  new = list(lines)
  new[n] = (lines[n].rstrip() if idx < 0 else lines[n][:idx]) + ("  " if idx < 0 else "") + note
  try:
    ka.compile_source("\n".join(new))
    return None
  except ka.CompileError as e:
    if str(e) != msg:                                     # the comment itself changes the error: leave it to a human
      print("  the note would change the error, do it by hand:", name)
      return None
  return new, lines


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  names = args or sorted(os.path.basename(p)[:-3] for p in glob.glob(TESTS + "*.ka"))
  changed = 0
  for name in names:
    res = annotate_error_test(name) if name.startswith("err_") else annotate_runtime_test(name, "--whole-output" in sys.argv)
    if res and res[0] != res[1]:
      open(TESTS + name + ".ka", "w", newline="").write("\n".join(res[0]))
      changed += 1
  print("changed", changed, "tests")


main()
