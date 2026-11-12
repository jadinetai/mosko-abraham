//! CPU setup: the kernel's own GDT/TSS/IDT, legacy PIC masking, timer start, trap dispatch.
//! Table loads and trap entry are NASM (asm/entry.asm); Rust uses inline asm only for
//! single instructions (in/out, rdmsr/wrmsr, sti, hlt, cli, control registers).

use crate::apic;
use core::arch::asm;
use core::sync::atomic::Ordering;

pub mod io {
    use core::arch::asm;

    /// # Safety
    /// The port must belong to a device the kernel owns.
    pub unsafe fn outb(port: u16, value: u8) {
        unsafe { asm!("out dx, al", in("dx") port, in("al") value, options(nomem, nostack, preserves_flags)) };
    }

    /// # Safety
    /// As for `outb`.
    pub unsafe fn inb(port: u16) -> u8 {
        let value: u8;
        unsafe { asm!("in al, dx", out("al") value, in("dx") port, options(nomem, nostack, preserves_flags)) };
        value
    }

    /// A write to the unused POST port: a short delay for the legacy PIC.
    pub unsafe fn io_wait() {
        unsafe { outb(0x80, 0) };
    }
}

use io::{io_wait, outb};

pub fn read_msr(msr: u32) -> u64 {
    let (low, high): (u32, u32);
    // SAFETY: callers only name architectural MSRs that exist on x86-64 with an APIC.
    unsafe { asm!("rdmsr", in("ecx") msr, out("eax") low, out("edx") high, options(nomem, nostack, preserves_flags)) };
    ((high as u64) << 32) | low as u64
}

pub fn write_msr(msr: u32, value: u64) {
    // SAFETY: as for read_msr.
    unsafe {
        asm!("wrmsr", in("ecx") msr, in("eax") value as u32, in("edx") (value >> 32) as u32,
             options(nostack, preserves_flags))
    };
}

pub fn read_cr3() -> u64 {
    let value: u64;
    // SAFETY: reading CR3 has no side effects.
    unsafe { asm!("mov {}, cr3", out(reg) value, options(nomem, nostack, preserves_flags)) };
    value
}

pub fn read_cr4() -> u64 {
    let value: u64;
    // SAFETY: reading CR4 has no side effects.
    unsafe { asm!("mov {}, cr4", out(reg) value, options(nomem, nostack, preserves_flags)) };
    value
}

const KERNEL_CODE: u64 = 0x08;
const KERNEL_DATA: u64 = 0x10;
const TSS_SELECTOR: u16 = 0x18;
const DOUBLE_FAULT_IST: u8 = 1;
pub const TIMER_VECTOR: u8 = 32;
pub const SPURIOUS_VECTOR: u8 = 0xFF;

#[repr(C, packed)]
struct DescriptorPointer {
    limit: u16,
    base: u64,
}

#[repr(C, packed)]
struct TaskStateSegment {
    reserved0: u32,
    rsp: [u64; 3],
    reserved1: u64,
    ist: [u64; 7],
    reserved2: u64,
    reserved3: u16,
    iomap_base: u16,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct IdtEntry {
    offset_low: u16,
    selector: u16,
    ist: u8,
    type_attributes: u8,
    offset_mid: u16,
    offset_high: u32,
    reserved: u32,
}

const EMPTY_GATE: IdtEntry =
    IdtEntry { offset_low: 0, selector: 0, ist: 0, type_attributes: 0, offset_mid: 0, offset_high: 0, reserved: 0 };

impl IdtEntry {
    fn interrupt_gate(handler: u64, ist: u8) -> Self {
        IdtEntry {
            offset_low: handler as u16,
            selector: KERNEL_CODE as u16,
            ist,
            type_attributes: 0x8E, // present, ring 0, 64-bit interrupt gate
            offset_mid: (handler >> 16) as u16,
            offset_high: (handler >> 32) as u32,
            reserved: 0,
        }
    }
}

// Null, 64-bit kernel code, kernel data, TSS (two slots).
static mut GDT: [u64; 5] = [0, 0x00af_9a00_0000_ffff, 0x00cf_9200_0000_ffff, 0, 0];
static mut TSS: TaskStateSegment = TaskStateSegment {
    reserved0: 0,
    rsp: [0; 3],
    reserved1: 0,
    ist: [0; 7],
    reserved2: 0,
    reserved3: 0,
    iomap_base: size_of::<TaskStateSegment>() as u16,
};
static mut IDT: [IdtEntry; 256] = [EMPTY_GATE; 256];

unsafe extern "C" {
    static abr_isr_table: [u64; 33];
    static abr_isr_spurious: u8;
    static abr_df_stack_top: u8;
    fn abr_load_gdt(gdtr: *const DescriptorPointer, code: u64, data: u64);
    fn abr_load_idt(idtr: *const DescriptorPointer);
    fn abr_load_tss(selector: u16);
}

/// Replace the bootloader's GDT (and its empty IDT) with the kernel's own. Interrupts stay
/// disabled.
pub fn init_descriptor_tables() {
    // SAFETY: single-threaded early boot with interrupts disabled; the tables are statics
    // that live for the whole run, which is what lgdt/lidt/ltr require.
    unsafe {
        let tss = &raw mut TSS;
        (*tss).ist[(DOUBLE_FAULT_IST - 1) as usize] = &raw const abr_df_stack_top as u64;

        let base = tss as u64;
        let limit = (size_of::<TaskStateSegment>() - 1) as u64;
        let gdt = &raw mut GDT;
        (*gdt)[3] = (limit & 0xffff)
            | ((base & 0xff_ffff) << 16)
            | (0x89 << 40) // present, available 64-bit TSS
            | (((limit >> 16) & 0xf) << 48)
            | (((base >> 24) & 0xff) << 56);
        (*gdt)[4] = base >> 32;

        let gdtr = DescriptorPointer { limit: (size_of::<[u64; 5]>() - 1) as u16, base: gdt as u64 };
        abr_load_gdt(&gdtr, KERNEL_CODE, KERNEL_DATA);
        abr_load_tss(TSS_SELECTOR);

        let idt = &raw mut IDT;
        for (vector, &handler) in abr_isr_table.iter().enumerate() {
            (*idt)[vector] = IdtEntry::interrupt_gate(handler, if vector == 8 { DOUBLE_FAULT_IST } else { 0 });
        }
        (*idt)[SPURIOUS_VECTOR as usize] = IdtEntry::interrupt_gate(&raw const abr_isr_spurious as u64, 0);
        let idtr = DescriptorPointer { limit: (size_of::<[IdtEntry; 256]>() - 1) as u16, base: idt as u64 };
        abr_load_idt(&idtr);
    }
}

/// Remap the 8259 PICs away from the exception vectors and leave every line masked:
/// the timer comes from the local APIC (see apic.rs for why).
fn mask_legacy_pic() {
    // SAFETY: legacy PIC ports on q35.
    unsafe {
        outb(0x20, 0x11);
        io_wait();
        outb(0xA0, 0x11);
        io_wait();
        outb(0x21, 0x20);
        io_wait();
        outb(0xA1, 0x28);
        io_wait();
        outb(0x21, 0x04);
        io_wait();
        outb(0xA1, 0x02);
        io_wait();
        outb(0x21, 0x01);
        io_wait();
        outb(0xA1, 0x01);
        io_wait();
        outb(0x21, 0xFF);
        outb(0xA1, 0xFF);
    }
}

/// Start the periodic local APIC timer and enable interrupts. On error, interrupts stay off.
pub fn start_timer(hz: u32) -> Result<apic::TimerInfo, &'static str> {
    mask_legacy_pic();
    let info = apic::start_periodic(hz, TIMER_VECTOR, SPURIOUS_VECTOR)?;
    // SAFETY: the IDT is loaded, so the timer and spurious vectors have handlers.
    unsafe { asm!("sti", options(nomem, nostack)) };
    Ok(info)
}

pub fn wait_for_interrupt() {
    // SAFETY: halts until the next interrupt; interrupts are enabled by start_timer.
    unsafe { asm!("hlt", options(nomem, nostack, preserves_flags)) };
}

pub fn halt_forever() -> ! {
    loop {
        // SAFETY: stops the CPU for good.
        unsafe { asm!("cli; hlt", options(nomem, nostack)) };
    }
}

/// Layout pushed by isr_common in asm/entry.asm, lowest address first.
#[repr(C)]
pub struct TrapFrame {
    r15: u64,
    r14: u64,
    r13: u64,
    r12: u64,
    r11: u64,
    r10: u64,
    r9: u64,
    r8: u64,
    rbp: u64,
    rdi: u64,
    rsi: u64,
    rdx: u64,
    rcx: u64,
    rbx: u64,
    rax: u64,
    vector: u64,
    error: u64,
    rip: u64,
    cs: u64,
    rflags: u64,
    rsp: u64,
    ss: u64,
}

const EXCEPTION_NAMES: [&str; 32] = [
    "DIVIDE_ERROR", "DEBUG", "NMI", "BREAKPOINT", "OVERFLOW", "BOUND_RANGE", "INVALID_OPCODE",
    "DEVICE_NOT_AVAILABLE", "DOUBLE_FAULT", "COPROCESSOR_SEGMENT", "INVALID_TSS",
    "SEGMENT_NOT_PRESENT", "STACK_FAULT", "GENERAL_PROTECTION", "PAGE_FAULT", "RESERVED_15",
    "X87_FP", "ALIGNMENT_CHECK", "MACHINE_CHECK", "SIMD_FP", "VIRTUALIZATION", "CONTROL_PROTECTION",
    "RESERVED_22", "RESERVED_23", "RESERVED_24", "RESERVED_25", "RESERVED_26", "RESERVED_27",
    "HYPERVISOR_INJECTION", "VMM_COMMUNICATION", "SECURITY", "RESERVED_31",
];

/// Common trap entry from isr_common. The timer and spurious vectors return; any CPU
/// exception is reported on COM1 and stops the kernel, so a fault is visible instead of
/// becoming a triple fault.
#[unsafe(no_mangle)]
pub extern "C" fn abr_trap(frame: &mut TrapFrame) {
    match frame.vector {
        v if v == TIMER_VECTOR as u64 => {
            crate::TICKS.fetch_add(1, Ordering::Relaxed);
            apic::end_of_interrupt();
            return;
        }
        v if v == SPURIOUS_VECTOR as u64 => {
            apic::SPURIOUS.fetch_add(1, Ordering::Relaxed);
            return;
        }
        _ => {}
    }
    let name = EXCEPTION_NAMES.get(frame.vector as usize).copied().unwrap_or("UNEXPECTED");
    let cr2: u64;
    // SAFETY: reading CR2 has no side effects.
    unsafe { asm!("mov {}, cr2", out(reg) cr2, options(nomem, nostack, preserves_flags)) };
    // 0.31b: reported through fault::stop (lifecycle state, uptime, FAILED transition, event context).
    crate::fault::stop(name, frame.vector, format_args!(
        "vector={}|name={}|error={:#x}|rip={:#x}|cs={:#x}|rflags={:#x}|rsp={:#x}|cr2={:#x}",
        frame.vector, name, frame.error, frame.rip, frame.cs, frame.rflags, frame.rsp, cr2
    ));
}
