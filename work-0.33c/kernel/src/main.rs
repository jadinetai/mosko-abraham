//  __  __    ___    ____    _  __   ___
// |  \/  |  / _ \  / ___|  | |/ /  / _ \
// | |\/| | | | | | \___ \  | ' /  | | | |
// | |  | | | |_| |  ___) | | . \  | |_| |
// |_|  |_|  \___/  |____/  |_|\_\  \___/  (TM)
//
// MOSKO(TM) - MOSKO Laboratory 001, Pripyat - Digital Front
// MOSKO(TM) source signature (D-ABR-026). Comment only: no code, no output, no dependency.

//! Abraham native kernel, x86-64, Rust `no_std` (ABRAHAM 0.2: P-01, P-02).
//!
//! ABR-BOOT-001 scope: enter from the bootloader, report on COM1, install the kernel's own
//! GDT/TSS/IDT, run a local APIC timer heartbeat, and stay up.
//! 0.31a (D-ABR-009): physical frame ownership. The frame allocator owns USABLE RAM before any
//! page table is built; page-table frames are pinned; frame ownership is proven on the live
//! page tables before OPERATIONAL.
//! 0.31b (D-ABR-014..016): an initialization lifecycle that only moves forward (lifecycle.rs,
//! init.rs), a fixed-capacity diagnostic event log (events.rs, eventlog.rs), a guarded TSC clock
//! (clockguard.rs, clock.rs) and truthful fault reports (fault.rs).
//! 0.32 (D-ABR-018/019): a closed service registry with bounded cooperative services, started only after
//! OPERATIONAL (svcregistry.rs, svclife.rs, svcstatus.rs, svcrun.rs, svctable.rs, svc_counter.rs, svcmgr.rs).
//! 0.32b (D-ABR-020): four corrections (dependent stop within the cycle, unmeasured steps break the recovery
//! streak, probe timing judged like every step, a hardened C12).
//! Nothing here implements authority, storage, devices, networking, a heap, a scheduler or ring 3 yet.

#![no_std]
#![no_main]

mod apic;
// 0.33 application registry and launcher. Portable logic, also built hosted (kernel/hosttest); the production
// kernel uses only discovery, the request path only in the DIAGNOSTIC build diag-launchpad.
#[allow(dead_code)]
mod appregistry;
#[allow(dead_code)]
mod apptable;
#[allow(dead_code)]
mod launch;
#[allow(dead_code)]
mod launchlife;
mod launchpad;
#[allow(dead_code)]
mod launchreq;
mod clock;
// Portable logic, also built hosted (kernel/hosttest); not every function is used by the kernel.
#[allow(dead_code)]
mod clockguard;
mod cpu;
mod entropy;
mod eventlog;
#[allow(dead_code)]
mod events;
mod fault;
#[allow(dead_code)]
mod frame;
mod init;
mod kcell;
#[allow(dead_code)]
mod lifecycle;
mod limine;
mod memory;
#[cfg(feature = "diag-memmap")]
mod memprobe;
#[cfg(feature = "diag-mem-exhaust")]
mod memtest;
mod paging;
mod ptwalk;
mod serial;
// 0.32 services. Portable logic, also built hosted (kernel/hosttest); not every function is used by the kernel.
#[allow(dead_code)]
mod svc_counter;
#[cfg(any(feature = "diag-svc-defects", feature = "diag-svc-slow", feature = "diag-svc-stall", feature = "diag-svc-cascade"))]
mod svcdiag;
#[allow(dead_code)]
mod svclife;
mod svcmgr;
#[allow(dead_code)]
mod svcregistry;
#[allow(dead_code)]
mod svcrun;
#[allow(dead_code)]
mod svcstatus;
#[allow(dead_code)]
mod svctable;

use core::panic::PanicInfo;
use core::sync::atomic::{AtomicU64, Ordering};
use events::Kind;
use lifecycle::InitState;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const TICK_HZ: u32 = 100;
/// 0.31b (F-029-04): at most this many missing heartbeat seconds are printed one by one; a longer
/// gap is reported once (HEARTBEAT_GAP) instead of flooding the console.
const MAX_CATCHUP_SECONDS: u64 = 5;

/// Timer interrupts delivered (counted for reporting; uptime comes from clock.rs).
pub static TICKS: AtomicU64 = AtomicU64::new(0);

/// Called from `abr_entry` (asm/entry.asm) on the kernel's own stack, interrupts disabled.
/// Lifecycle state on entry: EARLY.
#[unsafe(no_mangle)]
pub extern "C" fn abr_kmain() -> ! {
    serial::init();
    kprintln!("ABR|STAGE|kmain entered (Rust no_std)");

    // Only a loader that honoured the Limine requests fills these in, so they are the
    // kernel's own evidence of which bootloader handed over.
    let revision_ok = limine::base_revision_supported();
    match limine::bootloader_info() {
        Some((name, version)) => kprintln!(
            "ABR|BOOTINFO|loader={} {}|base_revision_supported={}",
            name, version, revision_ok
        ),
        None => kprintln!("ABR|BOOTINFO|loader=UNKNOWN|base_revision_supported={}", revision_ok),
    }
    match limine::loaded_base_revision() {
        Some(r) => kprintln!("ABR|BOOTINFO|base_revision_requested={}|base_revision_loaded={}", limine::BASE_REVISION, r),
        None => kprintln!("ABR|BOOTINFO|base_revision_requested={}|base_revision_loaded=UNREPORTED", limine::BASE_REVISION),
    }
    let memory_map = limine::memory_map();
    let usable: u64 = memory_map.iter().filter(|e| e.kind == limine::MEMMAP_USABLE).map(|e| e.length).sum();
    kprintln!("ABR|BOOTINFO|memmap_entries={}|usable_bytes={}", memory_map.len(), usable);
    match limine::hhdm_offset() {
        Some(offset) => kprintln!("ABR|BOOTINFO|hhdm_offset={:#x}", offset),
        None => kprintln!("ABR|BOOTINFO|hhdm_offset=UNAVAILABLE"),
    }
    if !revision_ok {
        fault::stop("LIMINE_BASE_REVISION_UNSUPPORTED", 0, format_args!("reason=LIMINE_BASE_REVISION_UNSUPPORTED"));
    }
    init::advance(InitState::LoaderVerified);

    #[cfg(feature = "diag-memmap")]
    {
        memprobe::memory_map();
        memprobe::page_tables("before_timer");
    }

    // 0.31a: the frame allocator becomes the owner of USABLE RAM before any page table is
    // built, and ownership is proven on the live tables. Either failure stops the boot.
    memory::init();
    init::advance(InitState::MemoryOwned);

    // 0.31b DIAGNOSTIC build: an invalid lifecycle step (MEMORY_OWNED straight to OPERATIONAL).
    // It must be refused and stop the kernel; OPERATIONAL must never be reported.
    #[cfg(feature = "diag-init-skip")]
    {
        kprintln!("ABR|DIAG|injecting=init_skip|from=MEMORY_OWNED|to=OPERATIONAL");
        init::advance(InitState::Operational);
        kprintln!("ABR|DIAG|init_skip_returned=UNEXPECTED");
    }

    if memory::check("init") {
        init::advance(InitState::MemoryVerified);
    }

    cpu::init_descriptor_tables();
    kprintln!("ABR|STAGE|gdt+tss+idt loaded");
    init::advance(InitState::CpuTablesLoaded);

    let epoch = entropy::boot_epoch();

    #[cfg(not(feature = "diag-early-fail"))]
    let started = cpu::start_timer(TICK_HZ);
    // G7 diagnostic build: a controlled early-initialization failure, before interrupts are on.
    #[cfg(feature = "diag-early-fail")]
    let started: Result<apic::TimerInfo, &str> = Err("DIAG_INJECTED_EARLY_INIT_FAILURE");
    let timer = match started {
        Ok(timer) => timer,
        Err(reason) => fault::stop("TIMER_UNAVAILABLE", 0, format_args!("reason=TIMER_UNAVAILABLE|detail={}", reason)),
    };
    kprintln!(
        "ABR|STAGE|timer=lapic-periodic|apic_mode={}|apic_id={}|hz={}|calibration=pit-ch2|calibration_ms={}\
         |apic_ticks_per_10ms={}|initial_count={}|clocksource=tsc|tsc_hz={}|tsc_invariant={}\
         |page_table_frames_taken={}|legacy_pic=masked|interrupts=enabled",
        timer.mode, timer.apic_id, TICK_HZ, apic::CALIBRATION_MS, timer.ticks_per_10ms, timer.initial_count,
        timer.tsc_hz, clock::tsc_invariant(), paging::FRAMES_TAKEN.load(Ordering::Relaxed)
    );
    eventlog::record(Kind::Timing, "TIMER_STARTED", timer.tsc_hz);
    init::advance(InitState::TimerRunning);
    #[cfg(feature = "diag-memmap")]
    memprobe::page_tables("after_timer");

    // The APIC mapping may have created page tables: prove ownership again (STOP condition).
    // Only a passing check may claim OWNERSHIP_VERIFIED; a report-only DIAGNOSTIC build that
    // fails it can therefore never reach OPERATIONAL (the lifecycle refuses the skip).
    if memory::check("timer") {
        init::advance(InitState::OwnershipVerified);
    }

    // 0.32 DIAGNOSTIC build: try to start the services before OPERATIONAL. It must be refused and change nothing.
    #[cfg(feature = "diag-svc-refusals")]
    {
        kprintln!("ABR|DIAG|injecting=svc_start_before_operational|init_state={}", init::state_name());
        svcmgr::start(timer.tsc_hz, 0);
    }

    // 0.31a DIAGNOSTIC build: exhaust the allocator on the live kernel (memtest.rs).
    #[cfg(feature = "diag-mem-exhaust")]
    if !memtest::run() {
        fault::stop("MEMTEST_FAILED", 0, format_args!("reason=MEMTEST_FAILED"));
    }

    // 0.31a DIAGNOSTIC build: a deliberate double release (D-ABR-012). The allocator must latch
    // FAULTED with the free pool unchanged and the kernel must stop; OPERATIONAL never follows.
    #[cfg(feature = "diag-double-release")]
    {
        let kept = memory::alloc_frame();
        match memory::alloc_frame() {
            Ok(f) => {
                let p = f.phys();
                core::mem::forget(f);
                let ok = memory::release_raw(p).is_ok();
                let free = memory::stats().map(|s| s.free_frames).unwrap_or(0);
                kprintln!("ABR|DIAG|injecting=double_release|frame={:#x}|first_release_ok={}|free_frames_before={}|kept_frame_ok={}",
                          p, ok, free, kept.is_ok());
                let _ = memory::release_raw(p); // must not return
                kprintln!("ABR|DIAG|double_release_returned=UNEXPECTED");
            }
            Err(e) => kprintln!("ABR|DIAG|double_release_setup_failed|detail={}", e.code()),
        }
        cpu::halt_forever();
    }

    banner(epoch);

    // G6 diagnostic build: a deliberate invalid opcode before OPERATIONAL. The fault handler
    // must report vector 6 at this function's address and stop; OPERATIONAL must never follow.
    #[cfg(feature = "diag-fault-ud")]
    {
        kprintln!("ABR|DIAG|injecting=ud2|expect_vector=6|expect_rip={:#x}", diag_ud2 as usize);
        diag_ud2();
    }

    // Operational only once the first timer interrupt has actually been handled, and only
    // through the lifecycle.
    while TICKS.load(Ordering::Relaxed) == 0 {
        cpu::wait_for_interrupt();
    }
    init::advance(InitState::Operational);
    kprintln!("ABR|STATE|OPERATIONAL");
    eventlog::print_all();

    // 0.32 (D-ABR-019): services start only now, after OPERATIONAL and after the 0.31b event printout, in
    // dependency order; their own records are printed once more, separately, after the start phase.
    let printed = eventlog::recorded();
    svcmgr::start(timer.tsc_hz, printed);
    #[cfg(feature = "diag-svc-refusals")]
    svcmgr::diag_refusals();
    // 0.33 DIAGNOSTIC build: the fixed launchpad script, once, after the first status round (design §9).
    #[cfg(feature = "diag-launchpad")]
    svcmgr::diag_launchpad();

    // Heartbeat: one line per elapsed (guarded) TSC second. Every second is printed even if the
    // CPU wakes late; delivered vs expected timer interrupts are reported. 0.31b: a clock anomaly
    // is reported once, counted on every later heartbeat, and the clock is DEGRADED from then on.
    let mut last_second = 0u64;
    let mut clock_anomalies = 0u64;
    #[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
    let mut armed = false;
    loop {
        cpu::wait_for_interrupt();
        let Some(obs) = clock::observe() else { continue };
        if let Some(a) = obs.anomaly {
            kprintln!("ABR|CLOCK|anomaly={}|counts={}|uptime_ms={}", a.code(), a.counts(), obs.uptime_ms);
            clock_anomaly(&mut clock_anomalies, a.code(), a.counts());
        }
        let now_s = obs.uptime_ms / 1000;
        if now_s > last_second + MAX_CATCHUP_SECONDS {
            let skipped = now_s - last_second - 1;
            kprintln!("ABR|CLOCK|anomaly=HEARTBEAT_GAP|from_s={}|to_s={}|skipped={}", last_second, now_s, skipped);
            clock_anomaly(&mut clock_anomalies, "HEARTBEAT_GAP", skipped);
            last_second = now_s - 1;
        }
        while last_second < now_s {
            last_second += 1;
            kprintln!(
                "ABR|TICK|uptime_s={}|spurious={}|timer_irqs={}|irq_expected={}|clock_anomalies={}",
                last_second, apic::SPURIOUS.load(Ordering::Relaxed), TICKS.load(Ordering::Relaxed),
                obs.uptime_ms * TICK_HZ as u64 / 1000, clock_anomalies
            );
            // G6 diagnostic build: a deliberate page fault after three heartbeats (write to an
            // unmapped higher-half address). Expect vector 14, CR2 = that address, error bit 1.
            #[cfg(feature = "diag-fault-pf")]
            if last_second == 3 {
                const UNMAPPED: u64 = 0xffff_ffff_9000_0000;
                kprintln!("ABR|DIAG|injecting=page_fault|expect_vector=14|expect_cr2={:#x}", UNMAPPED);
                // SAFETY: deliberately faulting write in a disposable diagnostic build.
                unsafe { core::ptr::write_volatile(UNMAPPED as *mut u64, 0xABAD_1DEA) };
            }
            // 0.31b DIAGNOSTIC builds: after three heartbeats the guard starts seeing the TSC 2 s
            // behind (backward) or 1 h ahead (jump).
            #[cfg(any(feature = "diag-tsc-backward", feature = "diag-tsc-jump"))]
            if last_second == 3 && !armed {
                armed = true;
                let counts = clock::diag_arm(timer.tsc_hz);
                kprintln!("ABR|DIAG|injecting={}|counts={}",
                          if cfg!(feature = "diag-tsc-backward") { "tsc_backward" } else { "tsc_jump" }, counts);
            }
        }
        // 0.32: one bounded cooperative step per RUNNING service, then the periodic status report. Never from
        // an interrupt handler.
        svcmgr::tick();
    }
}

/// Count a clock anomaly; the first one puts the clock in DEGRADED for the rest of the boot.
fn clock_anomaly(count: &mut u64, code: &'static str, arg: u64) {
    *count += 1;
    eventlog::record(Kind::Timing, code, arg);
    if *count == 1 {
        kprintln!("ABR|CLOCK|state=DEGRADED|reason={}|uptime_claimed_accurate=false", code);
    }
}

#[cfg(feature = "diag-fault-ud")]
#[inline(never)]
fn diag_ud2() {
    // SAFETY: deliberately raises #UD in a disposable diagnostic build.
    unsafe { core::arch::asm!("ud2", options(nomem, nostack, noreturn)) };
}

fn banner(epoch: Option<u64>) {
    kprintln!("ABRAHAM | MOSKO native kernel {} | ABR-BOOT-001", VERSION);
    match epoch {
        Some(e) => kprintln!(
            "ABR|BANNER|name=ABRAHAM|version={}|arch=x86_64|kernel=rust-no_std|entry=nasm|boot=uefi+limine\
             |boot_epoch={:016x}|entropy=RDRAND|environment_id=NORMAL(SELF_REPORTED)\
             |privilege_boundary=COOPERATIVE|status=AVAILABLE",
            VERSION, e
        ),
        // P-11: no entropy source means DEGRADED, and privileged operations are refused.
        None => kprintln!(
            "ABR|BANNER|name=ABRAHAM|version={}|arch=x86_64|kernel=rust-no_std|entry=nasm|boot=uefi+limine\
             |boot_epoch=UNAVAILABLE|entropy=NONE|environment_id=NORMAL(SELF_REPORTED)\
             |privilege_boundary=COOPERATIVE|status=DEGRADED|reason=ENTROPY_UNAVAILABLE",
            VERSION
        ),
    }
}

#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    fault::stop("PANIC", 0, format_args!("reason=PANIC|{}", info));
}
