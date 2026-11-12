; Abraham kernel: entry point, descriptor-table loads and trap stubs (NASM, P-02).
; ABR-BOOT-001. Assembled with: nasm -f elf64 -o entry.o entry.asm

bits 64
default rel

section .bss
align 16
kernel_stack:       resb 65536
kernel_stack_top:

align 16
df_stack:           resb 16384
global abr_df_stack_top
abr_df_stack_top:

section .rodata
; Leading CR LF: the loader's own console output may not end its last line.
entry_msg:          db 13, 10, "ABR|ENTRY|abr_entry reached (NASM)", 13, 10
entry_len           equ $ - entry_msg

section .text
extern abr_kmain
extern abr_trap

; The bootloader jumps here with interrupts disabled and its own stack.
; Switch to the kernel's stack, prove arrival on COM1 before any Rust code runs, enter Rust.
global abr_entry
abr_entry:
    cli
    cld
    lea     rsp, [kernel_stack_top]
    xor     ebp, ebp

    lea     rsi, [entry_msg]
    mov     ecx, entry_len
.next_byte:
    mov     dx, 0x3FD               ; COM1 line status register
.wait_thre:
    in      al, dx
    test    al, 0x20                ; transmit holding register empty
    jz      .wait_thre
    mov     dx, 0x3F8               ; COM1 data register
    lodsb
    out     dx, al
    dec     ecx
    jnz     .next_byte

    call    abr_kmain               ; never returns
.halt:
    cli
    hlt
    jmp     .halt

; void abr_load_gdt(const DescriptorPointer *gdtr, u64 code_selector, u64 data_selector)
global abr_load_gdt
abr_load_gdt:
    lgdt    [rdi]
    mov     ax, dx
    mov     ds, ax
    mov     es, ax
    mov     ss, ax
    xor     eax, eax
    mov     fs, ax
    mov     gs, ax
    pop     rax                     ; return address
    push    rsi                     ; new CS
    push    rax
    retfq                           ; reload CS and return to the caller

; void abr_load_idt(const DescriptorPointer *idtr)
global abr_load_idt
abr_load_idt:
    lidt    [rdi]
    ret

; void abr_load_tss(u16 selector)
global abr_load_tss
abr_load_tss:
    ltr     di
    ret

; Trap stubs. Every vector arrives at isr_common with the same frame:
; [vector][error code] above the CPU's interrupt frame, general registers below.
%macro ISR_NOERR 1
isr_%1:
    push    0
    push    %1
    jmp     isr_common
%endmacro

%macro ISR_ERR 1
isr_%1:
    push    %1
    jmp     isr_common
%endmacro

ISR_NOERR 0
ISR_NOERR 1
ISR_NOERR 2
ISR_NOERR 3
ISR_NOERR 4
ISR_NOERR 5
ISR_NOERR 6
ISR_NOERR 7
ISR_ERR   8
ISR_NOERR 9
ISR_ERR   10
ISR_ERR   11
ISR_ERR   12
ISR_ERR   13
ISR_ERR   14
ISR_NOERR 15
ISR_NOERR 16
ISR_ERR   17
ISR_NOERR 18
ISR_NOERR 19
ISR_NOERR 20
ISR_ERR   21
ISR_NOERR 22
ISR_NOERR 23
ISR_NOERR 24
ISR_NOERR 25
ISR_NOERR 26
ISR_NOERR 27
ISR_NOERR 28
ISR_ERR   29
ISR_ERR   30
ISR_NOERR 31
ISR_NOERR 32                        ; local APIC timer
ISR_NOERR 255                       ; local APIC spurious vector (no EOI)
global abr_isr_spurious
abr_isr_spurious equ isr_255

isr_common:
    push    rax
    push    rbx
    push    rcx
    push    rdx
    push    rsi
    push    rdi
    push    rbp
    push    r8
    push    r9
    push    r10
    push    r11
    push    r12
    push    r13
    push    r14
    push    r15
    ; 5 CPU-pushed + 2 + 15 qwords = 176 bytes below a 16-byte aligned base: RSP is aligned.
    mov     rdi, rsp                ; TrapFrame *
    cld
    call    abr_trap
    pop     r15
    pop     r14
    pop     r13
    pop     r12
    pop     r11
    pop     r10
    pop     r9
    pop     r8
    pop     rbp
    pop     rdi
    pop     rsi
    pop     rdx
    pop     rcx
    pop     rbx
    pop     rax
    add     rsp, 16                 ; vector and error code
    iretq

section .rodata
align 8
global abr_isr_table
abr_isr_table:
%assign i 0
%rep 33
    dq isr_ %+ i
%assign i i + 1
%endrep
