//! Physical frame ownership and allocation (ABRAHAM 0.31a; Echo audit F-029-01; D-ABR-009).
//!
//! Portable logic only: no `unsafe`, no hardware access, no heap. The same file is compiled
//! freestanding into the kernel (memory.rs owns the one global instance) and hosted for unit
//! tests (kernel/hosttest, baseline P-08 two-track build).
//!
//! Ownership model:
//! - `pool` bit = the frame came from a validated USABLE memory-map range and is not
//!   reserved. Only pool frames can ever be handed out.
//! - `free` bit = the pool frame is currently free. Invariant: free implies pool.
//! - A pinned frame (a page table) leaves the pool for good: it can never be released
//!   or handed out again.
//! - Everything else (other map types, ledger reservations, frame 0, memory at or above
//!   the managed limit) is never in the pool.
//!
//! Serious invariant violations (D-ABR-012): a double release, or a collision (the next
//! free frame is one the caller says is live, e.g. a page table), LATCH the allocator into
//! `State::Faulted`. From then on every operation is refused; nothing continues as if it had
//! not happened. A colliding frame is quarantined (removed from the pool) and never returned;
//! a double release leaves the free pool unchanged, so no frame is ever free twice.
//!
//! Failure codes are kernel diagnostic codes only (D-ABR-010), registered in
//! docs/KERNEL_DIAGNOSTICS.md. They must stay on kernel diagnostic lines; before one is
//! exposed through a public service, authorization or application interface it must enter
//! the Appendix A reason-code registry (D-ABR-011).

pub const PAGE: u64 = 4096;
/// Architectural limit of x86-64 physical addresses (52 bits).
pub const PHYS_LIMIT: u64 = 1 << 52;
/// Ledger entries remembered for reporting.
pub const LEDGER_CAPACITY: usize = 8;
/// Anomalies remembered in detail (all are counted).
pub const ANOMALY_LOG: usize = 8;
/// Pinned frames remembered by address (all are counted; overflow is reported).
pub const PIN_LOG: usize = 64;

/// Limine memory-map entry types (limine.h v12.9.6). Unknown values are reserved.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Usable,
    Reserved,
    AcpiReclaimable,
    AcpiNvs,
    BadMemory,
    BootloaderReclaimable,
    ExecutableAndModules,
    Framebuffer,
    ReservedMapped,
    Unknown,
}

impl Kind {
    pub const fn from_limine(t: u64) -> Kind {
        match t {
            0 => Kind::Usable,
            1 => Kind::Reserved,
            2 => Kind::AcpiReclaimable,
            3 => Kind::AcpiNvs,
            4 => Kind::BadMemory,
            5 => Kind::BootloaderReclaimable,
            6 => Kind::ExecutableAndModules,
            7 => Kind::Framebuffer,
            8 => Kind::ReservedMapped,
            _ => Kind::Unknown,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Region {
    pub base: u64,
    pub length: u64,
    pub kind: Kind,
}

/// Owners of explicit kernel reservations (the ledger), applied on top of the memory map.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum Owner {
    /// 0-1 MiB: frame 0, legacy and future trampoline space.
    Low1Mib = 1,
    /// The kernel image as placed by the loader (Executable Address request).
    KernelImage = 2,
    /// A device register page (the local APIC); not RAM.
    Mmio = 3,
    /// Host tests only.
    Test = 4,
}

impl Owner {
    pub const fn name(self) -> &'static str {
        match self {
            Owner::Low1Mib => "LOW_1MIB",
            Owner::KernelImage => "KERNEL_IMAGE",
            Owner::Mmio => "MMIO",
            Owner::Test => "TEST",
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Reservation {
    pub base: u64,
    pub length: u64,
    pub owner: Owner,
}

/// Why a pinned frame was pinned. Only page tables in 0.31a.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PinOwner {
    PageTable,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FrameError {
    /// No free frame. Nothing was written; the caller decides what to do.
    OutOfMemory,
    /// init() has not run.
    NotReady,
    AlreadyInitialized,
    Misaligned,
    /// At or above the managed limit.
    OutOfRange,
    /// Reserved, pinned, or never usable: the allocator does not own this frame.
    NotOwned,
    /// Serious (D-ABR-012): latches `Faulted`. The free pool is not changed.
    DoubleRelease,
    /// Serious (D-ABR-012): the candidate frame is live (caller's predicate). The frame is
    /// quarantined, not returned, and the allocator latches `Faulted`.
    OwnershipCollision,
    /// The allocator latched a serious violation earlier; every operation is refused.
    Faulted,
    /// Re-entered while in use (kernel glue only; there is no lock to wait on).
    Busy,
    /// A free bit without its pool bit: internal state is inconsistent; nothing handed out.
    Inconsistent,
}

impl FrameError {
    pub const fn code(self) -> &'static str {
        match self {
            FrameError::OutOfMemory => "OUT_OF_MEMORY",
            FrameError::NotReady => "FRAME_ALLOCATOR_NOT_READY",
            FrameError::AlreadyInitialized => "FRAME_ALLOCATOR_ALREADY_INITIALIZED",
            FrameError::Misaligned => "FRAME_MISALIGNED",
            FrameError::OutOfRange => "FRAME_OUT_OF_RANGE",
            FrameError::NotOwned => "FRAME_NOT_OWNED",
            FrameError::DoubleRelease => "FRAME_DOUBLE_RELEASE",
            FrameError::OwnershipCollision => "FRAME_OWNERSHIP_COLLISION",
            FrameError::Faulted => "FRAME_ALLOCATOR_FAULTED",
            FrameError::Busy => "FRAME_ALLOCATOR_BUSY",
            FrameError::Inconsistent => "FRAME_STATE_INCONSISTENT",
        }
    }
}

/// Memory-map defects. Each is accounted for safely and counted; none adds memory to the pool.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum Anomaly {
    /// Skipped.
    ZeroLength = 1,
    /// base + length overflows or passes the 52-bit limit. USABLE: rejected.
    /// Other types: reserved up to the limit.
    RangeOverflow = 2,
    /// USABLE base or length not page aligned: trimmed inward to whole frames.
    UsableMisaligned = 3,
    /// Base lower than the previous entry's. Processing is order-independent.
    Unsorted = 4,
    /// USABLE overlapping another USABLE entry: frames counted once.
    UsableDuplicate = 5,
    /// A non-USABLE entry touching a USABLE frame: the whole frame is removed (reserved wins).
    ReservedOverlapsUsable = 6,
    /// Unknown type: treated as reserved.
    UnknownType = 7,
    /// Ledger entry with zero length or overflow (overflow: reserved up to the limit).
    ReservationInvalid = 8,
}

impl Anomaly {
    pub const fn code(self) -> &'static str {
        match self {
            Anomaly::ZeroLength => "ZERO_LENGTH",
            Anomaly::RangeOverflow => "RANGE_OVERFLOW",
            Anomaly::UsableMisaligned => "USABLE_MISALIGNED",
            Anomaly::Unsorted => "UNSORTED",
            Anomaly::UsableDuplicate => "USABLE_DUPLICATE",
            Anomaly::ReservedOverlapsUsable => "RESERVED_OVERLAPS_USABLE",
            Anomaly::UnknownType => "UNKNOWN_TYPE",
            Anomaly::ReservationInvalid => "RESERVATION_INVALID",
        }
    }

    const fn from_u8(v: u8) -> Option<Anomaly> {
        match v {
            1 => Some(Anomaly::ZeroLength),
            2 => Some(Anomaly::RangeOverflow),
            3 => Some(Anomaly::UsableMisaligned),
            4 => Some(Anomaly::Unsorted),
            5 => Some(Anomaly::UsableDuplicate),
            6 => Some(Anomaly::ReservedOverlapsUsable),
            7 => Some(Anomaly::UnknownType),
            8 => Some(Anomaly::ReservationInvalid),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum State {
    Uninitialized = 0,
    /// Pool holds at least one frame.
    Ready = 1,
    /// Initialized, but nothing is allocatable: every alloc() is OUT_OF_MEMORY.
    Empty = 2,
    /// A serious invariant violation was detected (D-ABR-012). Latched: never left.
    Faulted = 3,
}

impl State {
    pub const fn name(self) -> &'static str {
        match self {
            State::Uninitialized => "UNINITIALIZED",
            State::Ready => "READY",
            State::Empty => "EMPTY",
            State::Faulted => "FAULTED",
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Stats {
    pub regions: u64,
    /// Sum of USABLE lengths as reported (saturating).
    pub usable_bytes_reported: u64,
    /// USABLE frames accepted into the pool by the map pass (below the limit, counted once).
    pub usable_frames_accepted: u64,
    /// USABLE bytes at or above the managed limit: never handed out.
    pub unmanaged_usable_bytes: u64,
    /// Pool frames removed again by non-USABLE entries that overlap them.
    pub removed_by_map: u64,
    /// Pool frames removed by ledger reservations (and frame 0).
    pub removed_by_ledger: u64,
    /// Pool size right after init().
    pub pool_frames_initial: u64,
    pub free_frames: u64,
    /// Allocated and not pinned.
    pub allocated: u64,
    pub pinned: u64,
    pub total_allocations: u64,
    pub total_releases: u64,
    pub oom_events: u64,
    pub refused_releases: u64,
    pub anomalies: u64,
    /// Frames removed from the pool by a detected collision (never handed out).
    pub quarantined: u64,
}

impl Stats {
    const ZERO: Stats = Stats {
        regions: 0, usable_bytes_reported: 0, usable_frames_accepted: 0, unmanaged_usable_bytes: 0,
        removed_by_map: 0, removed_by_ledger: 0, pool_frames_initial: 0, free_frames: 0, allocated: 0,
        pinned: 0, total_allocations: 0, total_releases: 0, oom_events: 0, refused_releases: 0, anomalies: 0,
        quarantined: 0,
    };
}

/// A frame the caller owns. It cannot be copied, cloned or built outside this module, and
/// `release`/`pin` consume it, so Rust code cannot touch a frame after giving it back.
#[must_use = "a dropped Frame is leaked: release it or pin it"]
#[derive(Debug, PartialEq, Eq)]
pub struct Frame {
    phys: u64,
}

impl Frame {
    pub fn phys(&self) -> u64 {
        self.phys
    }
}

#[derive(Clone, Copy)]
struct AnomalyRecord {
    entry: u32,
    code: u8,
}

#[derive(Clone, Copy)]
struct LedgerRecord {
    base: u64,
    length: u64,
    owner: u8,
    removed: u64,
}

/// Fixed-size frame allocator over physical addresses [0, WORDS * 64 * PAGE).
/// `new()` is all zero bytes, so a static instance lives in .bss.
pub struct FrameAllocator<const WORDS: usize> {
    pool: [u64; WORDS],
    free: [u64; WORDS],
    state: State,
    hint: usize,
    stats: Stats,
    anomaly_log: [AnomalyRecord; ANOMALY_LOG],
    ledger: [LedgerRecord; LEDGER_CAPACITY],
    ledger_len: usize,
    pin_log: [u64; PIN_LOG],
    /// 0 = no fault; otherwise 1 = double release, 2 = collision (latched).
    fault_kind: u8,
    fault_frame: u64,
}

fn get(bits: &[u64], i: u64) -> bool {
    bits[(i / 64) as usize] & (1 << (i % 64)) != 0
}

fn set(bits: &mut [u64], i: u64) {
    bits[(i / 64) as usize] |= 1 << (i % 64);
}

fn clear(bits: &mut [u64], i: u64) {
    bits[(i / 64) as usize] &= !(1 << (i % 64));
}

const fn align_up(x: u64) -> Option<u64> {
    match x.checked_add(PAGE - 1) {
        Some(v) => Some(v & !(PAGE - 1)),
        None => None,
    }
}

const fn align_down(x: u64) -> u64 {
    x & !(PAGE - 1)
}

impl<const WORDS: usize> FrameAllocator<WORDS> {
    pub const fn new() -> Self {
        FrameAllocator {
            pool: [0; WORDS],
            free: [0; WORDS],
            state: State::Uninitialized,
            hint: 0,
            stats: Stats::ZERO,
            anomaly_log: [AnomalyRecord { entry: 0, code: 0 }; ANOMALY_LOG],
            ledger: [LedgerRecord { base: 0, length: 0, owner: 0, removed: 0 }; LEDGER_CAPACITY],
            ledger_len: 0,
            pin_log: [0; PIN_LOG],
            fault_kind: 0,
            fault_frame: 0,
        }
    }

    /// The latched serious violation, if any: (error, frame address).
    pub fn fault(&self) -> Option<(FrameError, u64)> {
        match self.fault_kind {
            1 => Some((FrameError::DoubleRelease, self.fault_frame)),
            2 => Some((FrameError::OwnershipCollision, self.fault_frame)),
            _ => None,
        }
    }

    fn latch(&mut self, kind: u8, frame: u64) {
        if self.fault_kind == 0 {
            self.fault_kind = kind;
            self.fault_frame = frame;
        }
        self.state = State::Faulted;
    }

    /// First physical address not managed (WORDS * 64 frames).
    pub const fn limit() -> u64 {
        (WORDS as u64) * 64 * PAGE
    }

    pub fn state(&self) -> State {
        self.state
    }

    pub fn stats(&self) -> Stats {
        self.stats
    }

    /// Up to ANOMALY_LOG recorded anomalies as (memory-map entry index, anomaly).
    pub fn anomalies(&self) -> impl Iterator<Item = (u32, Anomaly)> + '_ {
        self.anomaly_log.iter().filter_map(|r| Anomaly::from_u8(r.code).map(|a| (r.entry, a)))
    }

    /// Ledger as (base, length, owner, pool frames it removed).
    pub fn ledger(&self) -> impl Iterator<Item = (u64, u64, &'static str, u64)> + '_ {
        self.ledger[..self.ledger_len].iter().map(|r| {
            let owner = match r.owner {
                1 => Owner::Low1Mib.name(),
                2 => Owner::KernelImage.name(),
                3 => Owner::Mmio.name(),
                _ => Owner::Test.name(),
            };
            (r.base, r.length, owner, r.removed)
        })
    }

    /// Pinned frames by address (the first PIN_LOG of them).
    pub fn pinned(&self) -> &[u64] {
        let n = core::cmp::min(self.stats.pinned as usize, PIN_LOG);
        &self.pin_log[..n]
    }

    pub fn pin_log_overflowed(&self) -> bool {
        self.stats.pinned as usize > PIN_LOG
    }

    fn note(&mut self, entry: usize, anomaly: Anomaly) {
        let n = self.stats.anomalies as usize;
        if n < ANOMALY_LOG {
            self.anomaly_log[n] = AnomalyRecord { entry: entry as u32, code: anomaly as u8 };
        }
        self.stats.anomalies += 1;
    }

    /// Clear pool bits for every frame touched by [base, end), clamped to the limit.
    /// Returns how many pool frames were removed.
    fn remove_range(&mut self, base: u64, end: u64) -> u64 {
        let first = align_down(base) / PAGE;
        let last = core::cmp::min(align_up(end).unwrap_or(u64::MAX & !(PAGE - 1)), Self::limit()) / PAGE;
        let mut removed = 0;
        let mut f = first;
        while f < last {
            if get(&self.pool, f) {
                clear(&mut self.pool, f);
                removed += 1;
            }
            f += 1;
        }
        removed
    }

    /// Build the pool from the memory map and the ledger. Runs once.
    ///
    /// Pass 1 adds whole frames inside validated USABLE entries. Pass 2 removes every frame
    /// that any non-USABLE entry touches. Pass 3 removes ledger reservations and frame 0.
    /// The result never depends on entry order.
    pub fn init<I>(&mut self, regions: I, reservations: &[Reservation]) -> Result<State, FrameError>
    where
        I: Iterator<Item = Region> + Clone,
    {
        if self.state != State::Uninitialized {
            return Err(FrameError::AlreadyInitialized);
        }
        let limit = Self::limit();

        // Pass 1: USABLE.
        let mut previous_base: Option<u64> = None;
        for (i, r) in regions.clone().enumerate() {
            self.stats.regions += 1;
            if let Some(p) = previous_base {
                if r.base < p {
                    self.note(i, Anomaly::Unsorted);
                }
            }
            previous_base = Some(r.base);
            if r.length == 0 {
                self.note(i, Anomaly::ZeroLength);
                continue;
            }
            let end = match r.base.checked_add(r.length) {
                Some(e) if e <= PHYS_LIMIT => e,
                _ => {
                    self.note(i, Anomaly::RangeOverflow);
                    continue; // USABLE rejected; other types handled in pass 2
                }
            };
            if r.kind == Kind::Unknown {
                self.note(i, Anomaly::UnknownType);
            }
            if r.kind != Kind::Usable {
                continue;
            }
            self.stats.usable_bytes_reported = self.stats.usable_bytes_reported.saturating_add(r.length);
            if r.base % PAGE != 0 || r.length % PAGE != 0 {
                self.note(i, Anomaly::UsableMisaligned);
            }
            // end <= 2^52, so align_up cannot overflow here.
            let first = align_up(r.base).unwrap_or(end);
            let last = align_down(end);
            if first >= last {
                continue;
            }
            if last > limit {
                self.stats.unmanaged_usable_bytes += last - core::cmp::max(first, limit);
            }
            let managed_last = core::cmp::min(last, limit);
            let mut duplicate = false;
            let mut f = first / PAGE;
            while f < managed_last / PAGE {
                if get(&self.pool, f) {
                    duplicate = true;
                } else {
                    set(&mut self.pool, f);
                    self.stats.usable_frames_accepted += 1;
                }
                f += 1;
            }
            if duplicate {
                self.note(i, Anomaly::UsableDuplicate);
            }
        }

        // Pass 2: every non-USABLE entry removes every frame it touches (reserved wins).
        for (i, r) in regions.enumerate() {
            if r.kind == Kind::Usable || r.length == 0 {
                continue;
            }
            let end = match r.base.checked_add(r.length) {
                Some(e) if e <= PHYS_LIMIT => e,
                _ => PHYS_LIMIT, // overflow: reserve everything from base up
            };
            let removed = self.remove_range(r.base, end);
            if removed > 0 {
                self.stats.removed_by_map += removed;
                self.note(i, Anomaly::ReservedOverlapsUsable);
            }
        }

        // Pass 3: ledger reservations, then frame 0 unconditionally.
        for (i, res) in reservations.iter().enumerate() {
            if res.length == 0 {
                self.note(i, Anomaly::ReservationInvalid);
                continue;
            }
            let end = match res.base.checked_add(res.length) {
                Some(e) if e <= PHYS_LIMIT => e,
                _ => {
                    self.note(i, Anomaly::ReservationInvalid);
                    PHYS_LIMIT
                }
            };
            let removed = self.remove_range(res.base, end);
            self.stats.removed_by_ledger += removed;
            if self.ledger_len < LEDGER_CAPACITY {
                self.ledger[self.ledger_len] =
                    LedgerRecord { base: res.base, length: res.length, owner: res.owner as u8, removed };
                self.ledger_len += 1;
            }
        }
        if limit > 0 && get(&self.pool, 0) {
            clear(&mut self.pool, 0);
            self.stats.removed_by_ledger += 1;
        }

        self.free = self.pool;
        let pool = self.pool.iter().map(|w| w.count_ones() as u64).sum();
        self.stats.pool_frames_initial = pool;
        self.stats.free_frames = pool;
        self.state = if pool == 0 { State::Empty } else { State::Ready };
        Ok(self.state)
    }

    /// Lowest free frame at or after the last allocation (next fit, wrapping). A released
    /// frame is not handed out again until the scan wraps around to it.
    pub fn alloc(&mut self) -> Result<Frame, FrameError> {
        self.alloc_checked(|_| false)
    }

    /// As `alloc`, but `is_live(phys)` is asked about the candidate before it is returned.
    /// If the candidate is live (a page table, the kernel, a device page...), that is an
    /// ownership collision: the frame is quarantined (never returned), the allocator latches
    /// `Faulted`, and `OwnershipCollision` is returned (D-ABR-012).
    pub fn alloc_checked(&mut self, is_live: impl Fn(u64) -> bool) -> Result<Frame, FrameError> {
        match self.state {
            State::Uninitialized => return Err(FrameError::NotReady),
            State::Faulted => return Err(FrameError::Faulted),
            State::Ready | State::Empty => {}
        }
        // Scan from the frame after the last one handed out: the rest of its word, every
        // other word, then (k == WORDS) the bits of the first word below the start.
        let frames = (WORDS as u64) * 64;
        let start = self.hint as u64 % frames;
        for k in 0..=WORDS {
            let w = ((start / 64) as usize + k) % WORDS;
            let mut bits = self.free[w];
            if k == 0 {
                bits &= !0u64 << (start % 64);
            } else if k == WORDS {
                bits &= !(!0u64 << (start % 64));
            }
            if bits == 0 {
                continue;
            }
            let b = bits.trailing_zeros() as u64;
            let index = w as u64 * 64 + b;
            if !get(&self.pool, index) {
                return Err(FrameError::Inconsistent);
            }
            // 0.31b (F-031a-E04 review): counters are checked before anything changes; a counter
            // that disagrees with the bitmap is refused, never wrapped.
            let Some(free_after) = self.stats.free_frames.checked_sub(1) else {
                return Err(FrameError::Inconsistent);
            };
            clear(&mut self.free, index);
            self.stats.free_frames = free_after;
            if is_live(index * PAGE) {
                clear(&mut self.pool, index);
                self.stats.quarantined += 1;
                self.latch(2, index * PAGE);
                return Err(FrameError::OwnershipCollision);
            }
            self.hint = ((index + 1) % frames) as usize;
            self.stats.allocated += 1;
            self.stats.total_allocations += 1;
            return Ok(Frame { phys: index * PAGE });
        }
        self.stats.oom_events += 1;
        Err(FrameError::OutOfMemory)
    }

    /// Give a frame back. The handle is consumed even if the release is refused.
    pub fn release(&mut self, frame: Frame) -> Result<(), FrameError> {
        self.release_raw(frame.phys)
    }

    /// Release by physical address: the checked path behind `release`, used directly only by
    /// diagnostics and tests. Refuses anything the allocator does not currently own as allocated.
    pub fn release_raw(&mut self, phys: u64) -> Result<(), FrameError> {
        let r = self.check_release(phys).and_then(|index| match self.stats.allocated.checked_sub(1) {
            Some(allocated_after) => Ok((index, allocated_after)),
            None => Err(FrameError::Inconsistent),
        });
        match r {
            Ok((index, allocated_after)) => {
                set(&mut self.free, index);
                self.stats.allocated = allocated_after;
                self.stats.free_frames += 1;
                self.stats.total_releases += 1;
                Ok(())
            }
            Err(e) => {
                self.stats.refused_releases += 1;
                if e == FrameError::DoubleRelease {
                    self.latch(1, phys); // the free pool is left exactly as it was
                }
                Err(e)
            }
        }
    }

    fn check_release(&self, phys: u64) -> Result<u64, FrameError> {
        match self.state {
            State::Uninitialized => return Err(FrameError::NotReady),
            State::Faulted => return Err(FrameError::Faulted),
            State::Ready | State::Empty => {}
        }
        if phys % PAGE != 0 {
            return Err(FrameError::Misaligned);
        }
        if phys >= Self::limit() {
            return Err(FrameError::OutOfRange);
        }
        let index = phys / PAGE;
        if !get(&self.pool, index) {
            return Err(FrameError::NotOwned);
        }
        if get(&self.free, index) {
            return Err(FrameError::DoubleRelease);
        }
        Ok(index)
    }

    /// Take a frame out of the pool permanently (a page table). Returns its address.
    /// Refused once the allocator is `Faulted` (the frame is then simply never used).
    pub fn pin(&mut self, frame: Frame, _owner: PinOwner) -> Result<u64, FrameError> {
        if self.state == State::Faulted {
            return Err(FrameError::Faulted);
        }
        let Some(allocated_after) = self.stats.allocated.checked_sub(1) else {
            return Err(FrameError::Inconsistent);
        };
        let index = frame.phys / PAGE;
        clear(&mut self.pool, index); // free is already clear: the frame is allocated
        self.stats.allocated = allocated_after;
        self.stats.pinned += 1;
        let n = self.stats.pinned as usize;
        if n <= PIN_LOG {
            self.pin_log[n - 1] = frame.phys;
        }
        Ok(frame.phys)
    }

    /// True if `phys` lies in a pool frame (free or allocated, not pinned).
    pub fn in_pool(&self, phys: u64) -> bool {
        phys < Self::limit() && get(&self.pool, phys / PAGE)
    }

    /// True if `phys` lies in a frame the allocator could hand out right now.
    pub fn is_free(&self, phys: u64) -> bool {
        phys < Self::limit() && get(&self.free, phys / PAGE)
    }

    /// 0.31b (F-031a-E04): pool frames lying in NONE of the given [base, end) ranges. Walks the pool
    /// once, so overlapping or duplicate ranges can never count a frame twice; no subtraction is
    /// involved. With the USABLE map entries as ranges, any non-zero result means some pool frame is
    /// outside USABLE memory.
    pub fn pool_frames_outside<I>(&self, ranges: I) -> u64
    where
        I: Iterator<Item = (u64, u64)> + Clone,
    {
        let mut outside = 0u64;
        for (w, &word) in self.pool.iter().enumerate() {
            let mut bits = word;
            while bits != 0 {
                let phys = (w as u64 * 64 + bits.trailing_zeros() as u64) * PAGE;
                bits &= bits - 1; // clear the lowest set bit (bits != 0 here)
                if !ranges.clone().any(|(base, end)| phys >= base && phys.saturating_add(PAGE) <= end) {
                    outside += 1;
                }
            }
        }
        outside
    }

    /// Pool frames whose address lies in [base, end). 0.31a used a sum of these over all USABLE
    /// entries, which double-counts overlaps (F-031a-E04); kept for reporting only.
    pub fn pool_frames_in(&self, base: u64, end: u64) -> u64 {
        let first = align_up(base).unwrap_or(u64::MAX) / PAGE;
        let last = core::cmp::min(align_down(end), Self::limit()) / PAGE;
        let mut n = 0;
        let mut f = first;
        while f < last {
            if get(&self.pool, f) {
                n += 1;
            }
            f += 1;
        }
        n
    }

    pub fn pool_frames_total(&self) -> u64 {
        self.pool.iter().map(|w| w.count_ones() as u64).sum()
    }

    /// Frames marked free but not in the pool. Must always be 0.
    pub fn free_outside_pool(&self) -> u64 {
        self.free.iter().zip(self.pool.iter()).map(|(f, p)| (f & !p).count_ones() as u64).sum()
    }

    pub fn free_frames_total(&self) -> u64 {
        self.free.iter().map(|w| w.count_ones() as u64).sum()
    }
}

/// 0.31b: counters forced out of step with the bitmaps. This cannot be reached through the public
/// API, so these unit tests (compiled only in the hosted test build, never in the kernel) set the
/// private fields directly and check that every operation refuses instead of wrapping.
#[cfg(test)]
mod inconsistent_counter_tests {
    use super::*;

    fn ready() -> FrameAllocator<1> {
        let mut a = FrameAllocator::<1>::new();
        a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
        a
    }

    #[test]
    fn alloc_with_zero_free_counter_is_refused_and_changes_nothing() {
        let mut a = ready();
        a.stats.free_frames = 0; // bitmap still holds 4 free frames
        let (pool, free) = (a.pool, a.free);
        assert_eq!(a.alloc(), Err(FrameError::Inconsistent));
        assert_eq!((a.pool, a.free), (pool, free));
        assert_eq!(a.stats.free_frames, 0);
    }

    #[test]
    fn release_with_zero_allocated_counter_is_refused_and_changes_nothing() {
        let mut a = ready();
        let f = a.alloc().unwrap();
        let p = f.phys();
        core::mem::forget(f);
        a.stats.allocated = 0;
        let free = a.free;
        assert_eq!(a.release_raw(p), Err(FrameError::Inconsistent));
        assert_eq!(a.free, free);
        assert_eq!(a.state(), State::Ready, "an inconsistency is refused, not latched as a double release");
    }

    #[test]
    fn pin_with_zero_allocated_counter_is_refused() {
        let mut a = ready();
        let f = a.alloc().unwrap();
        a.stats.allocated = 0;
        let pool = a.pool;
        assert_eq!(a.pin(f, PinOwner::PageTable), Err(FrameError::Inconsistent));
        assert_eq!(a.pool, pool);
        assert_eq!(a.stats.pinned, 0);
    }
}
