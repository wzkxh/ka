#!/usr/bin/env python3
"""
emu.py - run a Windows x64 console .exe produced by ka.py inside a CPU emulator
(Unicorn), with fake kernel32 functions. Lets the compiler be tested on Linux/macOS
(or by Claude in its sandbox). Windows itself remains the final word.

    pip install unicorn pefile
    python tools/emu.py prog.exe ["stdin text with \\n escapes"]

Library use:  stdout, exit_code, error = run_pe(path, stdin=b"...")
Faked API: GetStdHandle, WriteFile, SetConsoleOutputCP (no-op), ExitProcess,
GetProcessHeap, HeapAlloc (bump allocator), GetLocalTime and GetSystemTimePreciseAsFileTime (the real clock, or the fixed time
given as run_pe(..., now=datetime, unix_us=microseconds)). Checks stack alignment at every call.
"""
import struct
import sys


def run_pe(path, stdin=b"", max_insns=400_000_000, now=None, unix_us=None):
  import pefile
  from unicorn import Uc, UC_ARCH_X86, UC_MODE_64, UC_HOOK_CODE, UcError
  from unicorn.x86_const import (UC_X86_REG_RSP, UC_X86_REG_RIP, UC_X86_REG_RAX, UC_X86_REG_RCX,
                                 UC_X86_REG_RDX, UC_X86_REG_R8, UC_X86_REG_R9)
  pe = pefile.PE(path)
  base = pe.OPTIONAL_HEADER.ImageBase
  mu = Uc(UC_ARCH_X86, UC_MODE_64)
  mu.mem_map(base, pe.OPTIONAL_HEADER.SizeOfImage)
  mu.mem_write(base, pe.header[:pe.OPTIONAL_HEADER.SizeOfHeaders])
  for s in pe.sections:
    mu.mem_write(base + s.VirtualAddress, s.get_data())
  stub = 0x7ff000000000
  mu.mem_map(stub, 0x1000)
  stack_top = 0x2f0000
  mu.mem_map(0x200000, 0x100000)
  mu.mem_map(0x10000000, 0x4000000)          # heap
  heap = [0x10000000]
  apis = {}
  for entry in pe.DIRECTORY_ENTRY_IMPORT:
    for imp in entry.imports:
      addr = stub + 0x10 * (len(apis) + 1)
      apis[addr] = imp.name.decode()
      mu.mem_write(imp.address, struct.pack("<Q", addr))
  out, inp, code, problems = bytearray(), bytearray(stdin), [None], []

  def hook(uc, addr, size, _):
    if addr not in apis:
      return
    name = apis[addr]
    rsp = uc.reg_read(UC_X86_REG_RSP)
    if rsp % 16 != 8:
      problems.append(f"misaligned stack at call of {name}: rsp={rsp:#x}")
      uc.emu_stop()
      return
    ret = struct.unpack("<Q", uc.mem_read(rsp, 8))[0]
    rcx, rdx, r8, r9 = [uc.reg_read(r) for r in (UC_X86_REG_RCX, UC_X86_REG_RDX,
                                                 UC_X86_REG_R8, UC_X86_REG_R9)]
    rax = 1
    if name == "GetStdHandle":
      rax = rcx & 0xffffffff
    elif name == "WriteFile":
      out.extend(uc.mem_read(rdx, r8))
      uc.mem_write(r9, struct.pack("<I", r8))
    elif name == "ReadFile":
      data = bytes(inp[:r8])
      line = data.split(b"\n")[0] + b"\n" if b"\n" in data else data
      del inp[:len(line)]
      uc.mem_write(rdx, line)
      uc.mem_write(r9, struct.pack("<I", len(line)))
    elif name == "GetLocalTime":                  # SYSTEMTIME: year, month, weekday (0 = Sunday), day, hour, minute, second, ms
      import datetime
      t = now or datetime.datetime.now()
      uc.mem_write(rcx, struct.pack("<8H", t.year, t.month, (t.weekday() + 1) % 7, t.day, t.hour, t.minute, t.second,
                                    t.microsecond // 1000))
    elif name == "GetSystemTimePreciseAsFileTime":   # 100 ns since 1601
      import time
      us = unix_us if unix_us is not None else int(time.time() * 1_000_000)
      uc.mem_write(rcx, struct.pack("<Q", us * 10 + 116444736000000000))
    elif name == "GetProcessHeap":
      rax = 1
    elif name == "HeapAlloc":
      rax = heap[0]
      heap[0] += (r8 + 15) // 16 * 16
    elif name == "ExitProcess":
      code[0] = rcx & 0xffffffff
      uc.emu_stop()
      return
    uc.reg_write(UC_X86_REG_RAX, rax)
    uc.reg_write(UC_X86_REG_RSP, rsp + 8)
    uc.reg_write(UC_X86_REG_RIP, ret)

  mu.hook_add(UC_HOOK_CODE, hook, begin=stub, end=stub + 0x1000)
  mu.mem_write(stack_top - 8, struct.pack("<Q", stub))      # fake return address (rsp % 16 == 8)
  mu.reg_write(UC_X86_REG_RSP, stack_top - 8)
  error = None
  try:
    mu.emu_start(base + pe.OPTIONAL_HEADER.AddressOfEntryPoint, 0, count=max_insns)
  except UcError as e:
    error = f"emulator error: {e} at rip={mu.reg_read(UC_X86_REG_RIP):#x}"
  if problems:
    error = problems[0]
  if code[0] is None and error is None:
    error = "program did not call ExitProcess (instruction limit?)"
  return bytes(out), code[0], error


if __name__ == "__main__":
  data = sys.argv[2].encode().decode("unicode_escape").encode() if len(sys.argv) > 2 else b""
  o, c, e = run_pe(sys.argv[1], data)
  sys.stdout.write(o.decode("utf-8", "replace"))
  print(f"[exit code {c}]" + (f" [{e}]" if e else ""))
