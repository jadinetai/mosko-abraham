//! Limine boot protocol requests (P-01: an existing boot protocol, no hand-written loader).
//!
//! Checked on 2026-11-01 against Limine v12.9.6 `limine-protocol/include/limine.h` and
//! `PROTOCOL.md` (third_party/limine-12.9.6/source-docs): every ID below matches, and base
//! revision 6 is the current one (0-5 are deprecated). The bootloader writes the responses
//! into this memory before jumping to the kernel, so every read is volatile and goes
//! through an UnsafeCell.

use core::cell::UnsafeCell;
use core::ffi::c_char;
use core::ptr;

const COMMON_MAGIC: [u64; 2] = [0xc7b1dd30df4c8b88, 0x0a82e883a194f07b];
pub const BASE_REVISION: u64 = 6;
/// Second tag word as compiled; a loader supporting base revision 3 or later replaces it
/// with the revision it actually used.
const BASE_REVISION_MAGIC_1: u64 = 0x6a7b384944536bdc;

pub const MEMMAP_USABLE: u64 = 0;
pub const MEMMAP_BOOTLOADER_RECLAIMABLE: u64 = 5;

/// Memory-map type names as in limine.h (v12.9.6); anything else is reported, never guessed.
pub fn memmap_type_name(kind: u64) -> &'static str {
    match kind {
        0 => "USABLE",
        1 => "RESERVED",
        2 => "ACPI_RECLAIMABLE",
        3 => "ACPI_NVS",
        4 => "BAD_MEMORY",
        5 => "BOOTLOADER_RECLAIMABLE",
        6 => "EXECUTABLE_AND_MODULES",
        7 => "FRAMEBUFFER",
        8 => "RESERVED_MAPPED",
        _ => "UNKNOWN_TYPE",
    }
}

#[repr(transparent)]
struct LoaderCell<T>(UnsafeCell<T>);

// SAFETY: written only by the bootloader before the kernel starts; read-only afterwards.
unsafe impl<T> Sync for LoaderCell<T> {}

impl<T> LoaderCell<T> {
    const fn new(value: T) -> Self {
        Self(UnsafeCell::new(value))
    }
}

#[repr(C)]
struct Request<R> {
    id: [u64; 4],
    revision: u64,
    response: *const R,
}

impl<R> Request<R> {
    const fn new(id: [u64; 2]) -> Self {
        Self { id: [COMMON_MAGIC[0], COMMON_MAGIC[1], id[0], id[1]], revision: 0, response: ptr::null() }
    }
}

#[repr(C)]
struct BootloaderInfoResponse {
    revision: u64,
    name: *const c_char,
    version: *const c_char,
}

#[repr(C)]
pub struct MemmapEntry {
    pub base: u64,
    pub length: u64,
    pub kind: u64,
}

#[repr(C)]
struct MemmapResponse {
    revision: u64,
    entry_count: u64,
    entries: *const *const MemmapEntry,
}

#[repr(C)]
struct HhdmResponse {
    revision: u64,
    offset: u64,
}

/// 0.31a: the kernel's own physical placement. The EXECUTABLE_AND_MODULES memory-map entry
/// is "illustrative only" per PROTOCOL.md, so the kernel image reservation uses this instead.
#[repr(C)]
struct ExecutableAddressResponse {
    revision: u64,
    physical_base: u64,
    virtual_base: u64,
}

#[used]
#[unsafe(link_section = ".limine_requests_start")]
static REQUESTS_START: [u64; 4] = [0xf6b8f4b39de7d1ae, 0xfab91a6940fcb9cf, 0x785c6ed015d3e316, 0x181e920a7852b9d9];

#[used]
#[unsafe(link_section = ".limine_requests")]
static BASE_REVISION_TAG: LoaderCell<[u64; 3]> =
    LoaderCell::new([0xf9562b2d5c95a6c8, BASE_REVISION_MAGIC_1, BASE_REVISION]);

#[used]
#[unsafe(link_section = ".limine_requests")]
static BOOTLOADER_INFO: LoaderCell<Request<BootloaderInfoResponse>> =
    LoaderCell::new(Request::new([0xf55038d8e2a1202f, 0x279426fcf5f59740]));

#[used]
#[unsafe(link_section = ".limine_requests")]
static MEMMAP: LoaderCell<Request<MemmapResponse>> =
    LoaderCell::new(Request::new([0x67cf3d9d378a806f, 0xe304acdfc50c3c62]));

#[used]
#[unsafe(link_section = ".limine_requests")]
static HHDM: LoaderCell<Request<HhdmResponse>> =
    LoaderCell::new(Request::new([0x48dcf1cb8ad2b852, 0x63984e959a98244b]));

#[used]
#[unsafe(link_section = ".limine_requests")]
static EXECUTABLE_ADDRESS: LoaderCell<Request<ExecutableAddressResponse>> =
    LoaderCell::new(Request::new([0x71ba76863cc55f63, 0xb2644a48c516a487]));

#[used]
#[unsafe(link_section = ".limine_requests_end")]
static REQUESTS_END: [u64; 2] = [0xadc0e0531bb10d03, 0x9572709f31764c62];

fn tag_word(index: usize) -> u64 {
    // SAFETY: the tag is a valid, aligned [u64; 3] for the program's lifetime.
    unsafe { ptr::read_volatile(&raw const (*BASE_REVISION_TAG.0.get())[index]) }
}

/// The loader clears the third word of the tag when it supports the requested revision.
pub fn base_revision_supported() -> bool {
    tag_word(2) == 0
}

/// The base revision the loader actually used, if it reported one.
pub fn loaded_base_revision() -> Option<u64> {
    let word = tag_word(1);
    if word == BASE_REVISION_MAGIC_1 { None } else { Some(word) }
}

fn response<R>(request: &LoaderCell<Request<R>>) -> Option<&'static R> {
    // SAFETY: the response pointer is either null or set by the loader to a valid response
    // in memory it keeps mapped for the kernel.
    unsafe {
        let pointer = ptr::read_volatile(&raw const (*request.0.get()).response);
        pointer.as_ref()
    }
}

/// Loader strings are read with a bound, so a missing terminator cannot run off into memory.
const MAX_LOADER_STRING: usize = 128;

fn c_str(pointer: *const c_char) -> &'static str {
    if pointer.is_null() {
        return "?";
    }
    // SAFETY: the loader provides NUL-terminated strings that stay mapped; at most
    // MAX_LOADER_STRING bytes are read.
    unsafe {
        let bytes = pointer.cast::<u8>();
        let mut len = 0;
        while len < MAX_LOADER_STRING && *bytes.add(len) != 0 {
            len += 1;
        }
        core::str::from_utf8(core::slice::from_raw_parts(bytes, len)).unwrap_or("?")
    }
}

pub fn bootloader_info() -> Option<(&'static str, &'static str)> {
    response(&BOOTLOADER_INFO).map(|r| (c_str(r.name), c_str(r.version)))
}

/// The memory map as handed over: entries are loader-owned and stay mapped.
pub fn memory_map() -> &'static [&'static MemmapEntry] {
    match response(&MEMMAP) {
        // SAFETY: `entries` points to `entry_count` valid entry pointers.
        Some(r) if !r.entries.is_null() => unsafe {
            core::slice::from_raw_parts(r.entries.cast::<&'static MemmapEntry>(), r.entry_count as usize)
        },
        _ => &[],
    }
}

pub fn hhdm_offset() -> Option<u64> {
    response(&HHDM).map(|r| r.offset)
}

/// (physical_base, virtual_base) of the loaded kernel image, as the loader placed it.
pub fn executable_address() -> Option<(u64, u64)> {
    response(&EXECUTABLE_ADDRESS).map(|r| (r.physical_base, r.virtual_base))
}
