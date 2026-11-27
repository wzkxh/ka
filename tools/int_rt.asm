;;; Integer runtime of Kota (version 7.4). Intel syntax, assembled with Keystone by tools/build_float_rt.py; the bytes are embedded in kota.py.
;;; Same rules as float_rt.asm: position independent, self-contained (no calls, no imports), every register except rbp and rsp may be changed.
;;;
;;; rt_isprime   in: rax = n (int)   out: rax = 1 if n is prime, else 0   (the unary operator *n)
;;;   n < 66: a table of 64 bits, bit (n - 2) is set for the primes 2..65 (0x0A08228828228A2B), n < 2 gives 0.
;;;   else: even numbers and multiples of 3 are not prime; then trial division by i and i + 2 for i = 5, 11, 17, ... while i * i <= n.
;;;   i * i is checked for signed overflow: for n near the top of the int range the square of the first i beyond the root does not fit,
;;;   and without the check the loop would go on for billions of steps (the product wraps to a negative number).
;;; rt_isprime
  cmp rax, 66
  jge big
  cmp rax, 2
  jl not_prime
  lea rcx, [rax - 2]
  mov rdx, 0x0A08228828228A2B
  shr rdx, cl
  mov eax, edx
  and eax, 1
  ret
big:
  test al, 1
  jz not_prime
  mov r8, rax                    ; n
  xor edx, edx
  mov ecx, 3
  div rcx
  test rdx, rdx
  jz not_prime
  mov r9d, 5                     ; i
next_i:
  mov rax, r9
  imul rax, r9                   ; i * i
  jo is_prime                    ; does not fit: i * i > n for sure
  cmp rax, r8
  jg is_prime
  mov rax, r8
  xor edx, edx
  div r9                         ; n is positive: the unsigned division is right
  test rdx, rdx
  jz not_prime
  lea rcx, [r9 + 2]
  mov rax, r8
  xor edx, edx
  div rcx
  test rdx, rdx
  jz not_prime
  add r9, 6
  jmp next_i
is_prime:
  mov eax, 1
  ret
not_prime:
  xor eax, eax
  ret
