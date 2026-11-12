//! Per-boot random epoch (P-11). RDRAND only; no fallback that would fake randomness.

use core::arch::asm;
use core::arch::x86_64::__cpuid;

fn rdrand_available() -> bool {
    // CPUID.01H:ECX bit 30 = RDRAND.
    #[allow(unused_unsafe)]
    let leaf1 = unsafe { __cpuid(1) };
    leaf1.ecx & (1 << 30) != 0
}

fn rdrand64() -> Option<u64> {
    for _ in 0..16 {
        let value: u64;
        let ok: u8;
        // SAFETY: only executed after CPUID reported RDRAND support.
        unsafe {
            asm!("rdrand {v}", "setc {ok}", v = out(reg) value, ok = out(reg_byte) ok,
                 options(nomem, nostack));
        }
        if ok == 1 {
            return Some(value);
        }
    }
    None
}

/// `None` means no usable entropy: the caller must report DEGRADED / ENTROPY_UNAVAILABLE.
pub fn boot_epoch() -> Option<u64> {
    if rdrand_available() { rdrand64() } else { None }
}
