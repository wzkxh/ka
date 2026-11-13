#!/usr/bin/env python3
"""
run_tests.py - compile every tests/*.ka, run the program, compare with expectations.

    python run_tests.py              run everything (on Windows: really runs the .exe files)
    python run_tests.py -k closure   only tests whose name contains "closure"
    python run_tests.py -v           show expected/actual on failures
    python run_tests.py --emu        run in the Unicorn emulator instead (Linux/macOS; needs
                                     `pip install unicorn pefile`)
    python run_tests.py --keep       keep the generated .exe files in ./build

Test files (all in tests/, same base name):
    NAME.ka        program
    NAME.expected  expected stdout            (runtime tests)
    NAME.in        stdin to feed              (optional)
    NAME.exit      expected exit code         (optional, default 0)
    NAME.warn      text that must appear in a compiler warning (optional)
    err_NAME.ka + err_NAME.error : the compiler must FAIL, and its message must
                                     contain the text in the .error file (first line)
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
import ka  # noqa: E402


def read(path, mode="r"):
    if not os.path.exists(path):
        return None
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def norm(b):
    return b.replace(b"\r\n", b"\n")


def run_exe(exe, stdin, emu):
    if emu:
        import emu as emumod
        out, code, err = emumod.run_pe(exe, stdin)
        if err:
            return norm(out), code, err
        return norm(out), code, None
    try:
        p = subprocess.run([exe], input=stdin, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return b"", None, "timeout (30 s)"
    return norm(p.stdout), p.returncode, None


def run_one(path, outdir, emu):
    base = path[:-len(".ka")]
    name = os.path.basename(base)
    src = read(path)
    warnings = []
    try:
        exe_bytes = ka.compile_source(src, warnings)
        compile_error = None
    except ka.CompileError as e:
        exe_bytes, compile_error = None, str(e)

    if name.startswith("err_"):
        want = (read(base + ".error") or "").strip()
        if compile_error is None:
            return False, "expected a compile error but compilation succeeded"
        if want not in compile_error:
            return False, f"error message mismatch\n   expected to contain: {want}\n   got: {compile_error}"
        return True, ""
    if compile_error is not None:
        return False, f"unexpected compile error: {compile_error}"

    want_warn = (read(base + ".warn") or "").strip()
    if want_warn and not any(want_warn in w for w in warnings):
        return False, f"expected a warning containing: {want_warn}\n   got: {warnings}"
    exe = os.path.join(outdir, name + ".exe")
    with open(exe, "wb") as f:
        f.write(exe_bytes)
    stdin = read(base + ".in", "rb") or b""
    want_out = (read(base + ".expected", "rb") or b"").replace(b"\r\n", b"\n")
    want_code = int((read(base + ".exit") or "0").strip())
    out, code, err = run_exe(exe, stdin, emu)
    problems = []
    if err:
        problems.append(err)
    if out != want_out:
        problems.append(f"stdout differs\n--- expected\n{want_out.decode('utf-8', 'replace')}--- actual\n{out.decode('utf-8', 'replace')}---")
    if code != want_code:
        problems.append(f"exit code {code}, expected {want_code}")
    return (not problems), "\n   ".join(problems)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="only tests whose name contains this")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--emu", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    if not args.emu and sys.platform != "win32":
        print("note: not Windows, using --emu automatically")
        args.emu = True

    tests = sorted(p for p in glob.glob(os.path.join(HERE, "tests", "*.ka"))
                   if args.k in os.path.basename(p))
    outdir = os.path.join(HERE, "build") if args.keep else tempfile.mkdtemp(prefix="katests_")
    os.makedirs(outdir, exist_ok=True)
    failed, t0 = [], time.time()
    for path in tests:
        name = os.path.basename(path)[:-3]
        try:
            ok, msg = run_one(path, outdir, args.emu)
        except Exception as e:                      # compiler crash etc.
            ok, msg = False, f"internal error: {type(e).__name__}: {e}"
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            failed.append(name)
            print("   " + (msg if args.v or "\n" not in msg else msg.split("\n")[0] + "   (use -v for details)"))
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed in {time.time() - t0:.1f}s")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
