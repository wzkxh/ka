;;; Float runtime of Ka. Intel syntax, assembled with Keystone by tools/build_float_rt.py; the bytes are embedded in ka.py.
;;; Each routine is position independent and self-contained (no calls). Only rbp/rsp are preserved: generated code uses
;;; nothing but rax, rcx, rdx, rbp, rsp, so the routines may use every other register.
;;;
;;; rt_fmt_float   in: rax = bits of a double, rdx = output buffer (>= 40 bytes)   out: rax = length of the text
;;;   Text = 15 significant digits, trailing zeros removed, at least one digit after a '.', fixed notation for
;;;   1e-4 <= |x| < 1e15, else d.ddde+XX (Python style).  inf, -inf, nan, 0.0, -0.0.
;;;   Digits are made with the x87 unit in extended precision (the control word is set here, Windows starts with 53 bits).
;;; rt_fpow        in: xmm0 = x, xmm1 = y   out: xmm0 = x^y, edx = 0 ok / 1 zero to a negative power / 2 negative base
;;;                with a fractional exponent
;;; rt_fmod        in: xmm0 = x, xmm1 = y (y must not be 0, the caller checks)   out: xmm0 = x mod y, sign of x (like C fmod)
;;; rt_fmod
  movq rsi, xmm0
  movq rdi, xmm1
  mov r10, rsi
  shr r10, 63                    ; sign of x
  mov r8, rsi
  shr r8, 52
  and r8, 0x7FF                  ; exponent of x
  mov r9, rdi
  shr r9, 52
  and r9, 0x7FF                  ; exponent of y
  cmp r8, 0x7FF
  je make_nan
  mov rdx, rsi
  shl rdx, 1
  mov r11, rdi
  shl r11, 1
  cmp rdx, r11
  ja reduce
  jne return_x                   ; |x| < |y|: the result is x
  jmp zero_result                ; |x| = |y|: zero
return_x:
  ret
make_nan:
  mov rax, 0x7FF8000000000000
  movq xmm0, rax
  ret
reduce:
  test r8, r8
  jnz x_norm
  mov rdx, rsi
  shl rdx, 12
x_dn:
  test rdx, rdx
  js x_dn_done
  dec r8
  shl rdx, 1
  jmp x_dn
x_dn_done:
  mov rcx, 1
  sub rcx, r8
  shl rsi, cl
  jmp y_part
x_norm:
  mov rax, 0x000FFFFFFFFFFFFF
  and rsi, rax
  mov rax, 0x0010000000000000
  or rsi, rax
y_part:
  test r9, r9
  jnz y_norm
  mov rdx, rdi
  shl rdx, 12
y_dn:
  test rdx, rdx
  js y_dn_done
  dec r9
  shl rdx, 1
  jmp y_dn
y_dn_done:
  mov rcx, 1
  sub rcx, r9
  shl rdi, cl
  jmp loop_start
y_norm:
  mov rax, 0x000FFFFFFFFFFFFF
  and rdi, rax
  mov rax, 0x0010000000000000
  or rdi, rax
loop_start:                      ; shift and subtract, one bit at a time (exact)
  cmp r8, r9
  jle lp_done
  mov rdx, rsi
  sub rdx, rdi
  js lp_nosub
  jz zero_result
  mov rsi, rdx
lp_nosub:
  shl rsi, 1
  dec r8
  jmp loop_start
lp_done:
  mov rdx, rsi
  sub rdx, rdi
  js fin_norm
  jz zero_result
  mov rsi, rdx
fin_norm:
  mov rax, 0x0010000000000000
nrm:
  cmp rsi, rax
  jae scaled
  shl rsi, 1
  dec r8
  jmp nrm
scaled:
  test r8, r8
  jle denorm_out
  sub rsi, rax
  shl r8, 52
  or rsi, r8
  jmp out
denorm_out:
  mov rcx, 1
  sub rcx, r8
  shr rsi, cl
out:
  shl r10, 63
  or rsi, r10
  movq xmm0, rsi
  ret
zero_result:
  mov rax, r10
  shl rax, 63
  movq xmm0, rax
  ret


;;; rt_fpow
  xor edx, edx
  movq r9, xmm0                  ; original x (for the zero test)
  movq rax, xmm1
  mov rcx, rax
  shl rcx, 1
  jnz y_nonzero
  mov rax, 0x3FF0000000000000    ; x^0 = 1
  movq xmm0, rax
  ret
y_nonzero:
  cvttsd2si rcx, xmm1            ; is y an integer that fits in 64 bits?
  cvtsi2sd xmm2, rcx
  ucomisd xmm2, xmm1
  jne fractional
  jp fractional
  mov r8, rcx                    ; sign of the exponent
  test rcx, rcx
  jns abs_done
  neg rcx
abs_done:
  sub rsp, 24
  mov word ptr [rsp+16], 0x37F   ; extended precision, round to nearest
  fldcw word ptr [rsp+16]
  movsd qword ptr [rsp], xmm0
  fld1                           ; R = 1
  fld qword ptr [rsp]            ; B = x   (st0 = B, st1 = R)
sq_loop:
  test rcx, rcx
  jz sq_done
  test cl, 1
  jz sq_skip
  fmul st(1), st                 ; R = R * B
sq_skip:
  fmul st, st(0)                 ; B = B * B
  shr rcx, 1
  jmp sq_loop
sq_done:
  fstp st(0)                     ; drop B, st0 = R
  test r8, r8
  jns store_result
  mov rax, r9
  shl rax, 1
  jnz inv_ok
  fstp st(0)
  add rsp, 24
  mov edx, 1                     ; 0 ^ negative
  ret
inv_ok:
  fld1
  fxch st(1)
  fdivp st(1), st                ; 1 / R
store_result:
  fstp qword ptr [rsp]
  movsd xmm0, qword ptr [rsp]
  add rsp, 24
  xor edx, edx
  ret
fractional:
  mov rax, r9
  mov rcx, rax
  shl rcx, 1
  jz zero_base
  test rax, rax
  js domain_err
  sub rsp, 24
  mov word ptr [rsp+16], 0x37F   ; extended precision, round to nearest
  fldcw word ptr [rsp+16]
  movsd qword ptr [rsp], xmm1
  fld qword ptr [rsp]            ; y
  movsd qword ptr [rsp], xmm0
  fld qword ptr [rsp]            ; x      (st0 = x, st1 = y)
  fyl2x                          ; y * log2(x)
  fld st(0)
  frndint                        ; n
  fsub st(1), st                 ; st1 = t - n
  fxch st(1)                     ; st0 = fraction, st1 = n
  f2xm1
  fld1
  faddp st(1), st                ; 2^fraction
  fscale                         ; * 2^n
  fstp st(1)
  fstp qword ptr [rsp]
  movsd xmm0, qword ptr [rsp]
  add rsp, 24
  xor edx, edx
  ret
zero_base:
  movq rax, xmm1
  test rax, rax
  js zb_neg
  xorpd xmm0, xmm0
  ret
zb_neg:
  mov edx, 1
  ret
domain_err:
  mov edx, 2
  ret

;;; rt_fmt_float
  sub rsp, 64                    ; [rsp] x   [rsp+8] 10   [rsp+16] N   [rsp+24..39] digits   [rsp+40] control word
  mov r15, rdx                   ; start of the text
  mov rdi, rdx                   ; write position
  mov rbx, rax
  mov rcx, rbx
  shl rcx, 1
  mov rdx, 0xFFE0000000000000
  cmp rcx, rdx
  ja is_nan
  test rbx, rbx
  jns not_neg
  mov byte ptr [rdi], 0x2D
  inc rdi
not_neg:
  btr rbx, 63
  mov rcx, 0x7FF0000000000000
  cmp rbx, rcx
  je is_inf
  test rbx, rbx
  jz is_zero
  mov word ptr [rsp+40], 0x37F
  fldcw word ptr [rsp+40]
  mov qword ptr [rsp], rbx
  mov qword ptr [rsp+8], 10
  mov rax, rbx                   ; first guess of the decimal exponent from the binary one
  shr rax, 52
  sub rax, 1023
  imul rax, rax, 1233
  sar rax, 12
  mov r12, rax
retry:
  mov rcx, 14                    ; N = round(x * 10^(14 - e10)) must have 15 digits
  sub rcx, r12
  mov r8, rcx
  test rcx, rcx
  jns k_abs
  neg rcx
k_abs:
  fld qword ptr [rsp]
  fld1
  fild qword ptr [rsp+8]
pw_loop:                         ; 10^|k| by repeated squaring in extended precision
  test rcx, rcx
  jz pw_done
  test cl, 1
  jz pw_skip
  fmul st(1), st
pw_skip:
  fmul st, st(0)
  shr rcx, 1
  jmp pw_loop
pw_done:
  fstp st(0)
  test r8, r8
  js divide
  fmulp st(1), st
  jmp scaled
divide:
  fdivp st(1), st
scaled:
  frndint
  fistp qword ptr [rsp+16]
  mov r13, qword ptr [rsp+16]
  mov rax, 1000000000000000
  cmp r13, rax
  jl chk_low
  inc r12
  jmp retry
chk_low:
  mov rax, 100000000000000
  cmp r13, rax
  jge n_ok
  dec r12
  jmp retry
n_ok:
  mov r14, 15                    ; number of digits, trailing zeros removed
  mov rcx, 10
strip:
  cmp r14, 1
  jle strip_done
  mov rax, r13
  xor edx, edx
  div rcx
  test rdx, rdx
  jnz strip_done
  mov r13, rax
  dec r14
  jmp strip
strip_done:
  lea rsi, [rsp+24]              ; the digits as text
  mov rax, r13
  mov r8, r14
dig:
  xor edx, edx
  div rcx
  add dl, 0x30
  dec r8
  mov byte ptr [rsi+r8], dl
  test r8, r8
  jnz dig
  cmp r12, -4
  jl sci
  cmp r12, 14
  jg sci
  test r12, r12
  js frac_only
  lea r9, [r12+1]                ; digits before the point
  cmp r14, r9
  jle int_pad
  mov rcx, r9
  rep movsb
  mov byte ptr [rdi], 0x2E
  inc rdi
  mov rcx, r14
  sub rcx, r9
  rep movsb
  jmp done
int_pad:
  mov rcx, r14
  rep movsb
  mov rcx, r9
  sub rcx, r14
  mov al, 0x30
  rep stosb
  mov word ptr [rdi], 0x302E     ; ".0"
  add rdi, 2
  jmp done
frac_only:
  mov word ptr [rdi], 0x2E30     ; "0."
  add rdi, 2
  mov rcx, r12
  neg rcx
  dec rcx
  mov al, 0x30
  rep stosb
  mov rcx, r14
  rep movsb
  jmp done
sci:
  movsb
  cmp r14, 1
  jle sci_exp
  mov byte ptr [rdi], 0x2E
  inc rdi
  lea rcx, [r14-1]
  rep movsb
sci_exp:
  mov byte ptr [rdi], 0x65
  inc rdi
  mov rax, r12
  test rax, rax
  js sci_neg
  mov byte ptr [rdi], 0x2B
  jmp sci_sign
sci_neg:
  mov byte ptr [rdi], 0x2D
  neg rax
sci_sign:
  inc rdi
  mov rcx, 100
  xor edx, edx
  div rcx
  test rax, rax
  jz two_digits
  add al, 0x30
  mov byte ptr [rdi], al
  inc rdi
two_digits:
  mov rax, rdx
  mov rcx, 10
  xor edx, edx
  div rcx
  add al, 0x30
  mov byte ptr [rdi], al
  inc rdi
  add dl, 0x30
  mov byte ptr [rdi], dl
  inc rdi
  jmp done
is_nan:
  mov dword ptr [rdi], 0x006E616E
  add rdi, 3
  jmp done
is_inf:
  mov dword ptr [rdi], 0x00666E69
  add rdi, 3
  jmp done
is_zero:
  mov dword ptr [rdi], 0x00302E30
  add rdi, 3
done:
  mov rax, rdi
  sub rax, r15
  add rsp, 64
  ret
