#!/usr/bin/env python3
"""Dev tool: check ?'...' and ?"..." (time formatting) against a Python reference, at fixed times, in the emulator.
Needs `pip install unicorn pefile`. Usage: python tools/fuzz_time.py [number of formats] [seed]"""
import datetime, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ka, emu

NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def reference(fmt, t):
  ms = t.microsecond // 1000
  codes = {"y2": f"{t.year % 100:02d}", "y4": f"{t.year:04d}", "m1": str(t.month), "m2": f"{t.month:02d}", "d1": str(t.day),
           "d2": f"{t.day:02d}", "H1": str(t.hour), "H2": f"{t.hour:02d}", "M1": str(t.minute), "M2": f"{t.minute:02d}",
           "S1": str(t.second), "S2": f"{t.second:02d}", "F1": str(ms // 100), "F2": f"{ms // 10:02d}", "F3": f"{ms:03d}",
           "w1": str(t.isoweekday()), "w2": NAMES[t.weekday()][:2], "w3": NAMES[t.weekday()]}
  out, i = "", 0
  while i < len(fmt):
    item, step = fmt[i], 1
    if fmt[i:i + 2] in codes:
      item, step = codes[fmt[i:i + 2]], 2
    if len(out) + len(item) > 64:
      break                                   # an item that does not fit ends the result
    out += item
    i += step
  return out


def main():
  count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
  rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
  alphabet = list("ymdwHMSF") * 3 + list("0123456") * 2 + list(" /:.-x") + ["é", "€", "😀", "ñ"]
  fmts = ["y4/m2/d2 H2:M2:S2.F3", "y2 m1 d1 H1 M1 S1 F1 F2 F3 w1 w2 w3", "", "x", "y", "y4y", "wwww3", "m3 y3 F4 d0 H5 M9", "w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3w3"]
  fmts.append("F3" * 40)                                     # 120 characters: cut at 63..64
  fmts.append("y4" * 17)                                     # 68 characters: 16 codes fit
  fmts.append("a" * 63 + "y4")                              # the code does not fit: 63 characters
  fmts.append("a" * 62 + "w2")                              # fits exactly: 64
  fmts.append("a" * 63 + "w3")                              # does not fit
  fmts.append("é" * 70)
  while len(fmts) < count:
    fmts.append("".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 40))))
  src = ""
  for f in fmts:
    src += f"print ?'{f}'\nprint ?\"{f}\"\n"
  open("/tmp/fuzz_time.exe", "wb").write(ka.compile_source(src))
  times = [datetime.datetime(2026, 11, 26, 23, 35, 58, 296000), datetime.datetime(2027, 1, 1, 0, 0, 0, 5000),
           datetime.datetime(2099, 12, 31, 9, 7, 5, 999000), datetime.datetime(2026, 11, 29, 12, 1, 2, 70000),
           datetime.datetime(2030, 2, 4, 4, 4, 4, 4000), datetime.datetime(2026, 11, 30, 0, 59, 0, 100000)]
  bad = 0
  for t in times:
    out, code, err = emu.run_pe("/tmp/fuzz_time.exe", now=t)
    lines = out.decode("utf-8").split("\n")
    if code != 0 or err:
      print("run failed", code, err); return 1
    for k, f in enumerate(fmts):
      want = reference(f, t)
      for kind, got in (("str", lines[2 * k]), ("text", lines[2 * k + 1])):
        if got != want:
          bad += 1
          if bad < 10:
            print(f"MISMATCH {kind} {t} format {f!r}: got {got!r}, want {want!r}")
  print(f"{len(fmts)} formats x {len(times)} times x 2 kinds: {'all fine' if not bad else str(bad) + ' mismatches'}")
  return 1 if bad else 0


if __name__ == "__main__":
  sys.exit(main())
