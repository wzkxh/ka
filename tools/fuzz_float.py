#!/usr/bin/env python3
"""Dev tool: run the float runtime routines (from kota.py's FLOAT_RT, or from /tmp/blobs.pkl with --pkl) in Unicorn on many values
and compare with Python. Usage: python tools/fuzz_float.py [count]   (needs unicorn)"""
import math, os, pickle, random, struct, sys
from unicorn import Uc, UC_ARCH_X86, UC_MODE_64
from unicorn.x86_const import *

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

def load_blobs():
  if "--pkl" in sys.argv:
    return pickle.load(open("/tmp/blobs.pkl", "rb"))
  import kota
  return kota.FLOAT_RT

CODE, STACK, BUF = 0x10000, 0x200000, 0x300000

class Machine:
  def __init__(self, blobs):
    self.uc = Uc(UC_ARCH_X86, UC_MODE_64)
    self.uc.mem_map(CODE, 0x10000)
    self.uc.mem_map(STACK - 0x10000, 0x20000)
    self.uc.mem_map(BUF, 0x1000)
    self.entry, off = {}, 0
    for name, b in blobs.items():
      self.uc.mem_write(CODE + off, b)
      self.entry[name] = CODE + off
      off += (len(b) + 15) & ~15
    self.ret = CODE + 0xF000
    self.uc.mem_write(self.ret, b"\x90")

  def call(self, name, **regs):
    uc = self.uc
    uc.reg_write(UC_X86_REG_RSP, STACK)
    uc.mem_write(STACK, struct.pack("<Q", self.ret))
    for k, v in regs.items():
      uc.reg_write(getattr(__import__("unicorn.x86_const", fromlist=["x"]), "UC_X86_REG_" + k.upper()), v)
    uc.emu_start(self.entry[name], self.ret, count=2_000_000)

def bits(x): return struct.unpack("<Q", struct.pack("<d", x))[0]
def dbl(b): return struct.unpack("<d", struct.pack("<Q", b & (2**64 - 1)))[0]

def ref_fmt(x):
  if x != x: return "nan"
  if x in (math.inf, -math.inf): return "inf" if x > 0 else "-inf"
  if x == 0: return "-0.0" if math.copysign(1, x) < 0 else "0.0"
  sign = "-" if x < 0 else ""
  mant, exp = f"{abs(x):.14e}".split("e")
  e10 = int(exp)
  digits = mant.replace(".", "").rstrip("0") or "0"
  n = len(digits)
  if -4 <= e10 <= 14:
    if e10 >= 0:
      ip = e10 + 1
      body = digits + "0" * (ip - n) + ".0" if n <= ip else digits[:ip] + "." + digits[ip:]
    else:
      body = "0." + "0" * (-e10 - 1) + digits
  else:
    body = digits[0] + ("." + digits[1:] if n > 1 else "") + "e" + ("-" if e10 < 0 else "+") + f"{abs(e10):02d}"
  return sign + body

def run_fmt(m, x):
  m.uc.mem_write(BUF, b"\xAA" * 64)
  m.call("rt_fmt_float", rax=bits(x), rdx=BUF)
  n = m.uc.reg_read(UC_X86_REG_RAX)
  return bytes(m.uc.mem_read(BUF, n)).decode()

def run_xmm(m, name, x, y):
  m.uc.reg_write(UC_X86_REG_XMM0, bits(x))
  m.uc.reg_write(UC_X86_REG_XMM1, bits(y))
  m.call(name)
  return dbl(m.uc.reg_read(UC_X86_REG_XMM0) & (2**64 - 1)), m.uc.reg_read(UC_X86_REG_EDX)

def main():
  count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 20000
  m = Machine(load_blobs())
  rnd = random.Random(12345)
  vals = [0.0, -0.0, 1.0, -1.0, 0.1, 0.5, 1/3, 2/3, 100.0, 1e14, 1e15, 9.99999999999999e14, 999999999999999.9, 1e-4, 1e-5, 0.0001234,
          123456789012345.0, 1234567890123456.0, 1e300, 1.5e-300, 5e-324, 1.7976931348623157e308, 2.2250738585072014e-308,
          math.inf, -math.inf, math.nan, 0.30000000000000004, 3.14159, 2.5, 1e22, 1e23, 123456.789, 9.5, 99.5, 0.99999999999999999]
  for _ in range(count):
    k = rnd.random()
    if k < 0.4:
      vals.append(struct.unpack("<d", struct.pack("<Q", rnd.getrandbits(64)))[0])      # any bit pattern
    elif k < 0.7:
      vals.append(rnd.uniform(-1, 1) * 10 ** rnd.randint(-20, 20))
    else:
      vals.append(round(rnd.uniform(-1000, 1000), rnd.randint(0, 6)))                  # "nice" decimals
  bad = 0
  for x in vals:
    got, want = run_fmt(m, x), ref_fmt(x)
    if got != want:
      bad += 1
      if bad <= 15:
        print("FMT", repr(x), "got", got, "want", want)
  print(f"fmt: {len(vals)} values, {bad} differ ({100 * bad / len(vals):.3f}%)")
  # fmod
  bad = 0
  for _ in range(5000):
    x = rnd.uniform(-1000, 1000) * 10 ** rnd.randint(-3, 3); y = rnd.uniform(-50, 50) * 10 ** rnd.randint(-3, 3)
    if y == 0: continue
    got, _ = run_xmm(m, "rt_fmod", x, y)
    if got != math.fmod(x, y):
      bad += 1
      if bad <= 5: print("FMOD", x, y, got, math.fmod(x, y))
  print("fmod bad:", bad)
  # pow: integral exponents must be within 1 ulp; fractional ones use fyl2x/f2xm1, which Unicorn (QEMU) computes in
  # double precision only (error up to ~4e-15), the real FPU is better
  bad = {"integral": 0, "fractional": 0}; n = {"integral": 0, "fractional": 0}
  for _ in range(5000):
    x = rnd.uniform(-20, 20) if rnd.random() < 0.5 else rnd.uniform(0.01, 50)
    integral = rnd.random() < 0.5
    y = float(rnd.randint(-8, 12)) if integral else rnd.uniform(-6, 6)
    kind = "integral" if integral else "fractional"
    got, err = run_xmm(m, "rt_fpow", x, y)
    try:
      want = math.pow(x, y)
    except (ValueError, ZeroDivisionError):
      want = None
    n[kind] += 1
    if want is None:
      if err == 0 and x != 0:
        bad[kind] += 1
      continue
    tol = 3e-16 if integral else 1e-14
    if err != 0 or abs(got - want) > abs(want) * tol:
      bad[kind] += 1
      if bad[kind] <= 5: print("POW", x, y, "got", got, err, "want", want)
  print("pow bad:", bad, "of", n)
  for x, y in ((0.0, -1.0), (0.0, -0.5), (-8.0, 1/3), (0.0, 2.0), (0.0, 0.5), (2.0, 0.0), (0.0, 0.0), (-2.0, 3.0), (-2.0, -3.0), (2.0, 0.5), (4.0, 0.5), (8.0, 1/3)):
    print("pow", x, y, run_xmm(m, "rt_fpow", x, y))

main()
