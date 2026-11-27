#!/usr/bin/env python3
"""Dev tool: check the unary operator *n (prime test, rt_isprime) in the emulator against a Python reference (Miller-Rabin for 64 bits).
Needs `pip install unicorn pefile`. Usage: python tools/fuzz_prime.py [count] [seed]
The numbers stay below 10**12 on purpose: trial division is slow for big numbers (the user does not want such runs)."""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kota, emu


def is_prime(n):
  if n < 2:
    return 0
  for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
    if n % p == 0:
      return 1 if n == p else 0
  d, r = n - 1, 0
  while d % 2 == 0:
    d //= 2
    r += 1
  for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):          # enough for n < 3.3e24
    x = pow(a, d, n)
    if x in (1, n - 1):
      continue
    for _ in range(r - 1):
      x = x * x % n
      if x == n - 1:
        break
    else:
      return 0
  return 1


def main():
  count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
  rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
  nums = list(range(-5, 140)) + [65, 66, 67, 68, 69, 70, 71, 121, 169, 289, 361, 529, 841, 961, 1369, 1681, 1849, 2209, 561, 1105, 1729, 2465, 2821, 6601, 8911,
                                 2 ** 31 - 1, 2 ** 31, 2 ** 31 + 11, 1000000007, 998244353, 1000003 * 997, -2 ** 63, -2 ** 63 + 1, 3 ** 18, 7 ** 10]
  while len(nums) < count:
    nums.append(rnd.choice((rnd.randint(-10 ** 6, 10 ** 6), rnd.randint(0, 10 ** 6), rnd.randint(0, 10 ** 9), rnd.randint(0, 10 ** 9))))
  nums = [n for n in nums if -2 ** 63 <= n < 2 ** 63]
  src = "".join(f"print *({n - 1} + 1)\n" if n == -2 ** 63 else f"print *{n}\n" if n >= 0 else f"print *({n})\n" for n in nums)
  src = src.replace("print *(-9223372036854775809 + 1)", "print *(-9223372036854775807 - 1)")
  open("/tmp/fuzz_prime.exe", "wb").write(kota.compile_source(src))
  out, code, err = emu.run_pe("/tmp/fuzz_prime.exe", max_insns=2_000_000_000)
  lines = out.decode().split("\n")
  bad = 0
  for n, got in zip(nums, lines):
    if got != str(is_prime(n)):
      bad += 1
      print(f"MISMATCH {n}: got {got!r}, want {is_prime(n)}")
  print(f"{len(nums)} numbers: {'all fine' if not bad else str(bad) + ' mismatches'} (exit code {code})")
  return 1 if bad or code else 0


if __name__ == "__main__":
  sys.exit(main())
