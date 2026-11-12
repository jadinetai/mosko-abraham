/* Abraham kernel link layout (ABR-BOOT-001).
 * Higher-half kernel at -2 GiB, as the Limine boot protocol expects. The Limine request
 * section gets its own writable segment because the bootloader fills in the responses. */

OUTPUT_FORMAT(elf64-x86-64)
ENTRY(abr_entry)

PHDRS
{
    limine_requests PT_LOAD FLAGS((1 << 1) | (1 << 2));  /* RW */
    text            PT_LOAD FLAGS((1 << 0) | (1 << 2));  /* RX */
    rodata          PT_LOAD FLAGS((1 << 2));             /* R  */
    data            PT_LOAD FLAGS((1 << 1) | (1 << 2));  /* RW */
}

SECTIONS
{
    . = 0xffffffff80000000;
    __abr_kernel_start = .;   /* 0.31a: kernel image extent, for the frame-ownership ledger */

    .limine_requests : {
        KEEP(*(.limine_requests_start))
        KEEP(*(.limine_requests))
        KEEP(*(.limine_requests_end))
    } :limine_requests

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .text : { *(.text .text.*) } :text

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .rodata : { *(.rodata .rodata.*) } :rodata

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .data : { *(.data .data.*) } :data
    .bss : { *(.bss .bss.*) *(COMMON) } :data
    __abr_kernel_end = .;

    /DISCARD/ : { *(.eh_frame*) *(.note .note.*) *(.comment) }
}
