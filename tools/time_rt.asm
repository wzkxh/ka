;;; Time and text runtime of Ka (version 6.9). Intel syntax, assembled with Keystone by tools/build_float_rt.py; the bytes are embedded in ka.py.
;;; Same rules as float_rt.asm: position independent, self-contained (no calls, no imports), every register except rbp and rsp may be changed.
;;; The Windows calls and the allocation are in ka.py (rt_time_us, rt_time_text, rt_time_str); these routines only compute, on buffers that exist already.
;;;
;;; rt_utf8_to_text   in: rsi = bytes, rcx = number of bytes, rdi = u32 buffer, rdx = room (code points)   out: rax = code points written
;;;   Decodes UTF-8. A byte that is not part of a valid sequence (a stray continuation byte, a truncated or overlong sequence, a surrogate, above 10FFFF)
;;;   becomes U+DC00 + byte (like Python's surrogateescape), so that rt_text_to_utf8 gives the same byte back.
;;; rt_text_to_utf8   in: rsi = u32 code points, rcx = how many, rdi = byte buffer (4 bytes per code point)   out: rax = number of bytes
;;;   Encodes UTF-8; U+DC80..U+DCFF (made by rt_utf8_to_text) become the single byte 80..FF.
;;; rt_time_format    in: rsi = format (u32 code points), rcx = how many, rdx = SYSTEMTIME, rdi = u32 buffer for 64 code points   out: rax = code points written (<= 64)
;;;   A format code is a letter and a digit: y2 y4 m1 m2 d1 d2 H1 H2 M1 M2 S1 S2 F1 F2 F3 w1 w2 w3 (LANGUAGE.md). Everything else is copied.
;;;   A code that does not fit in the 64 code points ends the result.
;;; rt_utf8_to_text
  xor r8d, r8d                   ; code points written
next_byte:
  test rcx, rcx
  jz done
  cmp r8, rdx
  jae done
  movzx eax, byte ptr [rsi]
  mov r11d, 1                    ; bytes used
  cmp eax, 0x80
  jb store
  cmp eax, 0xC2
  jb bad
  cmp eax, 0xE0
  jb two
  cmp eax, 0xF0
  jb three
  cmp eax, 0xF5
  jb four
  jmp bad
two:
  cmp rcx, 2
  jb bad
  and eax, 0x1F
  movzx r9d, byte ptr [rsi + 1]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  mov r11d, 2
  jmp store
three:
  cmp rcx, 3
  jb bad
  and eax, 0x0F
  movzx r9d, byte ptr [rsi + 1]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  movzx r9d, byte ptr [rsi + 2]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  cmp eax, 0x800                 ; shorter forms are not allowed
  jb bad_restore
  cmp eax, 0xD800                ; no surrogates
  jb three_ok
  cmp eax, 0xE000
  jb bad_restore
three_ok:
  mov r11d, 3
  jmp store
four:
  cmp rcx, 4
  jb bad
  and eax, 0x07
  movzx r9d, byte ptr [rsi + 1]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  movzx r9d, byte ptr [rsi + 2]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  movzx r9d, byte ptr [rsi + 3]
  mov r10d, r9d
  and r10d, 0xC0
  cmp r10d, 0x80
  jne bad_restore
  and r9d, 0x3F
  shl eax, 6
  or eax, r9d
  cmp eax, 0x10000
  jb bad_restore
  cmp eax, 0x110000
  jae bad_restore
  mov r11d, 4
  jmp store
bad_restore:
bad:
  movzx eax, byte ptr [rsi]
  add eax, 0xDC00
  mov r11d, 1
store:
  mov dword ptr [rdi + r8 * 4], eax
  inc r8
  add rsi, r11
  sub rcx, r11
  jmp next_byte
done:
  mov rax, r8
  ret
;;; rt_text_to_utf8
  mov r8, rdi                    ; start of the output
next_cp:
  test rcx, rcx
  jz done
  mov eax, dword ptr [rsi]
  add rsi, 4
  dec rcx
  cmp eax, 0x80
  jb one
  cmp eax, 0x800
  jb two
  cmp eax, 0x10000
  jb three
  mov r9d, eax                   ; four bytes
  shr r9d, 18
  or r9d, 0xF0
  mov byte ptr [rdi], r9b
  mov r9d, eax
  shr r9d, 12
  and r9d, 0x3F
  or r9d, 0x80
  mov byte ptr [rdi + 1], r9b
  mov r9d, eax
  shr r9d, 6
  and r9d, 0x3F
  or r9d, 0x80
  mov byte ptr [rdi + 2], r9b
  and eax, 0x3F
  or eax, 0x80
  mov byte ptr [rdi + 3], al
  add rdi, 4
  jmp next_cp
three:
  cmp eax, 0xDC80                ; an escaped byte
  jb three_normal
  cmp eax, 0xDCFF
  ja three_normal
  mov byte ptr [rdi], al         ; the low byte of DC80..DCFF is the original byte
  inc rdi
  jmp next_cp
three_normal:
  mov r9d, eax
  shr r9d, 12
  or r9d, 0xE0
  mov byte ptr [rdi], r9b
  mov r9d, eax
  shr r9d, 6
  and r9d, 0x3F
  or r9d, 0x80
  mov byte ptr [rdi + 1], r9b
  and eax, 0x3F
  or eax, 0x80
  mov byte ptr [rdi + 2], al
  add rdi, 3
  jmp next_cp
two:
  mov r9d, eax
  shr r9d, 6
  or r9d, 0xC0
  mov byte ptr [rdi], r9b
  and eax, 0x3F
  or eax, 0x80
  mov byte ptr [rdi + 1], al
  add rdi, 2
  jmp next_cp
one:
  mov byte ptr [rdi], al
  inc rdi
  jmp next_cp
done:
  mov rax, rdi
  sub rax, r8
  ret
;;; rt_time_format
  mov r12, rdx                   ; SYSTEMTIME: year 0, month 2, weekday 4 (0 = Sunday), day 6, hour 8, minute 10, second 12, milliseconds 14
  xor r8d, r8d                   ; code points written
next_cp:
  test rcx, rcx
  jz done
  cmp r8, 64
  jae done
  mov eax, dword ptr [rsi]
  cmp rcx, 2
  jb literal
  mov r9d, dword ptr [rsi + 4]   ; the character after the letter must be a digit 1..4
  sub r9d, 0x31
  cmp r9d, 3
  ja literal                     ; (below '1' wraps around to a big number)
  cmp eax, 0x79                  ; 'y'
  je code_y
  cmp eax, 0x6D                  ; 'm'
  je code_m
  cmp eax, 0x64                  ; 'd'
  je code_d
  cmp eax, 0x48                  ; 'H'
  je code_h
  cmp eax, 0x4D                  ; 'M'
  je code_minute
  cmp eax, 0x53                  ; 'S'
  je code_s
  cmp eax, 0x46                  ; 'F'
  je code_f
  cmp eax, 0x77                  ; 'w'
  je code_w
literal:
  mov dword ptr [rdi + r8 * 4], eax
  inc r8
  add rsi, 4
  dec rcx
  jmp next_cp
code_y:
  cmp r9d, 1
  je y2
  cmp r9d, 3
  jne literal
  movzx r10d, word ptr [r12]     ; y4
  mov r11d, 4
  jmp number
y2:
  movzx eax, word ptr [r12]
  xor edx, edx
  mov r10d, 100
  div r10d
  mov r10d, edx
  mov r11d, 2
  jmp number
code_m:
  movzx r10d, word ptr [r12 + 2]
  jmp one_or_two
code_d:
  movzx r10d, word ptr [r12 + 6]
  jmp one_or_two
code_h:
  movzx r10d, word ptr [r12 + 8]
  jmp one_or_two
code_minute:
  movzx r10d, word ptr [r12 + 10]
  jmp one_or_two
code_s:
  movzx r10d, word ptr [r12 + 12]
one_or_two:                      ; r9d = 0 (no leading zero) or 1 (two digits); other digits are not codes
  cmp r9d, 1
  ja literal
  lea r11d, [r9 + 1]
  jmp number
code_f:
  cmp r9d, 2
  ja literal
  movzx eax, word ptr [r12 + 14]
  xor edx, edx
  mov r10d, 100                  ; F1: milliseconds / 100
  cmp r9d, 0
  je f_divide
  mov r10d, 10                   ; F2: milliseconds / 10
  cmp r9d, 1
  je f_divide
  mov r10d, eax                  ; F3: milliseconds
  lea r11d, [r9 + 1]
  jmp number
f_divide:
  div r10d
  mov r10d, eax
  lea r11d, [r9 + 1]
  jmp number
code_w:
  cmp r9d, 2
  ja literal
  movzx eax, word ptr [r12 + 4]
  test eax, eax
  jnz weekday_ok
  mov eax, 7                     ; Sunday is 7
weekday_ok:
  cmp r9d, 0
  jne weekday_name
  mov r10d, eax                  ; w1: 1..7
  mov r11d, 1
  jmp number
weekday_name:                    ; w2: Mo Tu We Th Fr Sa Su    w3: Mon Tue Wed Thu Fri Sat Sun
  dec eax
  lea eax, [rax + rax * 2]       ; 3 bytes per name
  mov r10d, eax
  mov r13d, r9d
  inc r13d                       ; number of letters: 2 or 3
  mov eax, r8d
  add eax, r13d
  cmp eax, 64
  ja done
  lea rax, [rip + names]
  add rax, r10
  xor edx, edx
copy_name:
  movzx r10d, byte ptr [rax + rdx]
  mov dword ptr [rdi + r8 * 4], r10d
  inc r8
  inc rdx
  cmp edx, r13d
  jb copy_name
  add rsi, 8
  sub rcx, 2
  jmp next_cp
number:                          ; r10d = value (0..9999), r11d = least number of digits (zeros in front)
  mov r13d, r11d
  cmp r10d, 10
  jb width_1
  cmp r13d, 2
  jae width_1
  mov r13d, 2
width_1:
  cmp r10d, 100
  jb width_2
  cmp r13d, 3
  jae width_2
  mov r13d, 3
width_2:
  cmp r10d, 1000
  jb width_3
  cmp r13d, 4
  jae width_3
  mov r13d, 4
width_3:
  mov eax, r8d
  add eax, r13d
  cmp eax, 64
  ja done                        ; does not fit
  mov eax, r10d
  mov r11, r8
  shl r11, 2
  add r11, rdi                   ; where the first digit goes
  mov r10d, 10
  mov r9d, r13d
digit:                           ; the digits are made from the end
  xor edx, edx
  div r10d
  add edx, 0x30
  mov dword ptr [r11 + r9 * 4 - 4], edx
  dec r9d
  jnz digit
  add r8, r13
  add rsi, 8
  sub rcx, 2
  jmp next_cp
done:
  mov rax, r8
  ret
names:
  db 0x4D, 0x6F, 0x6E, 0x54, 0x75, 0x65, 0x57, 0x65, 0x64, 0x54, 0x68, 0x75, 0x46, 0x72, 0x69, 0x53, 0x61, 0x74, 0x53, 0x75, 0x6E
