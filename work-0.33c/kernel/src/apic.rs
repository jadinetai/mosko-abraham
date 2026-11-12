//! Local APIC timer: the kernel's periodic interrupt source.
//!
//! Limine base revision 5+ masks the legacy PICs, every I/O APIC ExtINT entry and every
//! local APIC LVT entry (LINT0 included), so the 8259/PIT path never reaches the CPU.
//! The local APIC timer is used instead, in whichever mode the firmware left the APIC:
//! x2APIC through MSRs, otherwise xAPIC through its MMIO page (mapped by paging.rs).
//!
//! 0.1.1 (D-ABR-006): the APIC timer and the TSC are calibrated together against PIT channel 2
//! over 50 ms (was 10 ms: a fixed polling latency made TCG read 0.3-0.6% high). Uptime comes from
//! the TSC (clock.rs); timer interrupts drive the idle loop and are counted, never used as time.

use crate::cpu::io::{inb, outb};
use crate::cpu::{read_msr, write_msr};
use crate::{clock, paging};
use core::ptr;
use core::sync::atomic::{AtomicU64, Ordering};

const IA32_APIC_BASE: u32 = 0x1B;
const APIC_GLOBAL_ENABLE: u64 = 1 << 11;
const X2APIC_ENABLE: u64 = 1 << 10;

const REG_ID: u32 = 0x20;
const REG_EOI: u32 = 0xB0;
const REG_SVR: u32 = 0xF0;
const REG_LVT_TIMER: u32 = 0x320;
const REG_INITIAL_COUNT: u32 = 0x380;
const REG_CURRENT_COUNT: u32 = 0x390;
const REG_DIVIDE: u32 = 0x3E0;

const SVR_SOFTWARE_ENABLE: u32 = 1 << 8;
const LVT_MASKED: u32 = 1 << 16;
const LVT_PERIODIC: u32 = 1 << 17;
const DIVIDE_BY_16: u32 = 0b0011;

const PIT_HZ: u64 = 1_193_182;
pub const CALIBRATION_MS: u64 = 50;
const PIT_POLL_LIMIT: u64 = 1_000_000_000;

/// 0 = not started, 1 = x2APIC (MSRs), otherwise the xAPIC MMIO virtual address.
static MODE: AtomicU64 = AtomicU64::new(0);
const MODE_X2APIC: u64 = 1;

pub struct TimerInfo {
    pub mode: &'static str,
    pub apic_id: u32,
    pub ticks_per_10ms: u32,
    pub initial_count: u32,
    pub tsc_hz: u64,
}

fn read(register: u32) -> u32 {
    match MODE.load(Ordering::Relaxed) {
        MODE_X2APIC => read_msr(0x800 + (register >> 4)) as u32,
        // SAFETY: MODE holds the uncached mapping of the APIC page.
        base => unsafe { ptr::read_volatile((base + register as u64) as *const u32) },
    }
}

fn write(register: u32, value: u32) {
    match MODE.load(Ordering::Relaxed) {
        MODE_X2APIC => write_msr(0x800 + (register >> 4), value as u64),
        // SAFETY: as in read().
        base => unsafe { ptr::write_volatile((base + register as u64) as *mut u32, value) },
    }
}

/// APIC timer counts (divide by 16) and TSC counts in the same CALIBRATION_MS PIT window.
fn calibrate() -> Result<(u32, u64), &'static str> {
    let count = (PIT_HZ * CALIBRATION_MS / 1000) as u16; // 59,659 for 50 ms: fits 16 bits
    let tsc_start;
    // SAFETY: PIT and port 0x61 are fixed legacy devices on q35.
    unsafe {
        let port_b = inb(0x61);
        outb(0x61, port_b & !0x03); // channel 2 gate low, speaker off
        outb(0x43, 0b1011_0000); // channel 2, lo/hi byte, mode 0, binary
        outb(0x42, count as u8);
        outb(0x42, (count >> 8) as u8);
        if inb(0x61) & 0x20 != 0 {
            return Err("PIT_OUT2_NOT_LOW");
        }
        write(REG_INITIAL_COUNT, u32::MAX);
        tsc_start = clock::read_tsc();
        outb(0x61, (port_b & !0x02) | 0x01); // gate high: the PIT starts counting
        let mut polls = 0u64;
        while inb(0x61) & 0x20 == 0 {
            polls += 1;
            if polls > PIT_POLL_LIMIT {
                return Err("PIT_TIMEOUT");
            }
        }
    }
    let tsc_elapsed = clock::read_tsc() - tsc_start;
    let elapsed = u32::MAX - read(REG_CURRENT_COUNT);
    write(REG_INITIAL_COUNT, 0);
    // A window below 5,000 counts or near the full range means the measurement is not real.
    if !(5_000..=0xF000_0000).contains(&elapsed) {
        return Err("CALIBRATION_OUT_OF_RANGE");
    }
    // Below 50 MHz (2.5M counts in 50 ms) the TSC is not a usable clocksource here.
    if tsc_elapsed < 2_500_000 {
        return Err("TSC_CALIBRATION_OUT_OF_RANGE");
    }
    Ok((elapsed, tsc_elapsed))
}

/// Enable the local APIC and start its timer as a periodic `hz` interrupt on `vector`.
/// Also starts the TSC clocksource from the same calibration.
pub fn start_periodic(hz: u32, vector: u8, spurious_vector: u8) -> Result<TimerInfo, &'static str> {
    let base = read_msr(IA32_APIC_BASE);
    if base & APIC_GLOBAL_ENABLE == 0 {
        return Err("APIC_GLOBALLY_DISABLED");
    }
    let mode = if base & X2APIC_ENABLE != 0 {
        MODE.store(MODE_X2APIC, Ordering::Relaxed);
        "x2apic"
    } else {
        MODE.store(paging::map_uncached(base & 0xFFFF_F000)?, Ordering::Relaxed);
        "xapic"
    };

    write(REG_SVR, SVR_SOFTWARE_ENABLE | spurious_vector as u32);
    write(REG_DIVIDE, DIVIDE_BY_16);
    write(REG_LVT_TIMER, LVT_MASKED | vector as u32); // one-shot, masked, for calibration
    let (apic_counts, tsc_counts) = calibrate()?;
    let ticks_per_10ms = (apic_counts as u64 * 10 / CALIBRATION_MS) as u32;
    let tsc_hz = tsc_counts * 1000 / CALIBRATION_MS;

    let initial_count = ((apic_counts as u64 * 1000) / (CALIBRATION_MS * hz as u64)) as u32;
    clock::start(tsc_hz);
    write(REG_LVT_TIMER, LVT_PERIODIC | vector as u32);
    write(REG_INITIAL_COUNT, initial_count);

    let raw_id = read(REG_ID);
    let apic_id = if mode == "x2apic" { raw_id } else { raw_id >> 24 };
    Ok(TimerInfo { mode, apic_id, ticks_per_10ms, initial_count, tsc_hz })
}

pub fn end_of_interrupt() {
    write(REG_EOI, 0);
}

/// Spurious interrupts, counted for diagnostics (they take no EOI).
pub static SPURIOUS: AtomicU64 = AtomicU64::new(0);
