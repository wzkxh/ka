#!/usr/bin/env python3
"""Dev test of the kota.py command line (-e, -k, -c) without Windows: run_exe is replaced by the emulator.
Needs `pip install unicorn pefile`. Usage: python tools/test_cli.py"""
import contextlib, io, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import kota, emu

ran = []


def fake_run_exe(path):
  out, code, err = emu.run_pe(path)
  ran.append((path, os.path.exists(path)))
  sys.stdout.write(out.decode("utf-8"))
  return code


kota.run_exe = fake_run_exe
failures = 0


def run(argv):
  """run kota.main with these arguments; returns (exit code, stdout, stderr)"""
  global ran
  ran = []
  o, e = io.StringIO(), io.StringIO()
  sys.argv = ["kota.py"] + argv
  with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
    try:
      code = kota.main()
    except SystemExit as x:                       # argparse errors
      code = x.code
  return code, o.getvalue(), e.getvalue()


def check(what, ok):
  global failures
  print(("ok    " if ok else "FAIL  ") + what)
  failures += 0 if ok else 1


with tempfile.TemporaryDirectory() as d:
  os.chdir(d)
  open("p.ko", "w").write('print "hello ", 1 + 2\n')
  open("bad.ko", "w").write("print +\n")
  open("three.ko", "w").write("exit 3\n")

  code, o, e = run(["p.ko"])
  check("plain compile writes p.exe, does not run it", code == 0 and os.path.exists("p.exe") and not ran and o.startswith("wrote p.exe"))
  os.remove("p.exe")

  code, o, e = run(["-e", "p.ko"])
  check("-e runs the program and deletes the exe", code == 0 and o == "hello 3\n" and len(ran) == 1 and ran[0][1] and not os.path.exists("p.exe"))
  check("-e leaves nothing behind", sorted(os.listdir(d)) == ["bad.ko", "p.ko", "three.ko"])

  code, o, e = run(["-e", "-k", "p.ko"])
  check("-e -k keeps p.exe", code == 0 and o == "hello 3\n" and os.path.exists("p.exe") and "kept p.exe" in e)
  os.remove("p.exe")

  code, o, e = run(["-e", "-k", "p.ko", "-o", "q.exe"])
  check("-e -k -o keeps q.exe", code == 0 and os.path.exists("q.exe") and not os.path.exists("p.exe"))
  os.remove("q.exe")

  code, o, e = run(["-e", "p.ko", "-o", "r.exe"])
  check("-e -o runs r.exe and deletes it", code == 0 and o == "hello 3\n" and not os.path.exists("r.exe"))

  code, o, e = run(["-e", "three.ko"])
  check("the exit code of the program is the exit code of kota.py", code == 3)

  code, o, e = run(["-c", 'print "cmd ", 6 * 7'])
  check("-c runs the text", code == 0 and o == "cmd 42\n" and sorted(os.listdir(d)) == ["bad.ko", "p.ko", "three.ko"])

  code, o, e = run(["-c", "x = 1\nx += 4\nprint x"])
  check("-c with several lines", code == 0 and o == "5\n")

  code, o, e = run(["-c", 'print "kept"', "-k"])
  exes = [f for f in os.listdir(d) if f.endswith(".exe")]
  check("-c -k keeps yyyymmdd_HHMMSS.exe in the current directory",
        code == 0 and o == "kept\n" and len(exes) == 1 and len(exes[0]) == len("20261127_011500.exe") and exes[0][8] == "_")
  for f in exes:
    os.remove(f)

  code, o, e = run(["-c", 'print "named"', "-k", "-o", "n.exe"])
  check("-c -k -o keeps n.exe", code == 0 and os.path.exists("n.exe") and not [f for f in os.listdir(d) if f.endswith(".exe") and f != "n.exe"])
  os.remove("n.exe")

  code, o, e = run(["-c", "print +"])
  check("-c: a compile error is reported as <command>, nothing runs", code == 1 and e.startswith("<command>: error:") and not ran)
  code, o, e = run(["-e", "bad.ko"])
  check("-e: a compile error is reported with the file name, nothing runs, nothing left", code == 1 and e.startswith("bad.ko: error:") and not ran and not os.path.exists("bad.exe"))

  for argv, what in ((["-k", "p.ko"], "-k without -e"), (["-c", "print 1", "p.ko"], "-c with a file"), ([], "nothing to compile"),
                     (["-k", "-c", "print 1", "p.ko"], "-k -c with a file")):
    code, o, e = run(argv)
    check(f"usage error: {what}", code == 2 and not ran)
  code, o, e = run(["missing.xx"])
  check("a missing source file is an error message, not a crash", code == 1 and "missing.xx: error: cannot read the source file" in e and "Traceback" not in e)
print("all fine" if not failures else f"{failures} failed")
sys.exit(1 if failures else 0)
