# ABRAHAM 0.34 "First Light": design proposal (D-ABR-026 Phase 6)

2026-11-10. MOSKO Laboratory 001 - Pripyat.

**Status: PROPOSAL for the owner review gate. Not approved; nothing in it is implemented.**
- 0.34 implementation awaits Jadin's explicit approval, after 0.33 acceptance (criteria A-E).
- No download, no toolchain install and no source change for 0.34 is made before then.

## 1. Goal and non-goals

**The goal.** Abraham's own pixels in QEMU: a simple screen the kernel draws itself, showing
- the Abraham/SOLOMON identity;
- uptime;
- the clock state;
- the service and application state it already reports on serial.

**Non-goals for 0.34** (directive Phase 6; P-19):
- no browser;
- no general-purpose TCP/IP stack;
- no scheduler;
- no native application executor;
- no ring 3;
- no window system;
- no font renderer beyond one fixed bitmap font.

The serial diagnostic channel stays the authority for every judge. The screen is an additional view, never the
evidence.

## 2. Owner decisions requested (with recommendations)

| Q | Decision | Recommendation |
|---|---|---|
| Q1 | The display device in QEMU | `-device VGA` (standard VGA, bochs-dispi), which edk2's QemuVideoDxe drives, so Limine gets a GOP framebuffer with no new firmware. Alternative: `ramfb` |
| Q2 | How the operator sees it | the launcher (0.34-capable version) adds a QEMU window (`-display sdl` in the pinned 11.1.0 build) beside the serial console. Automated tests use QMP `screendump`, not the window |
| Q3 | Pixel formats accepted | 32 bpp RGB with 8-bit masks only, at any shifts Limine reports. Everything else is reported as unsupported, and the kernel runs serial-only (§6) |
| Q4 | The font | a public-domain 8x16 bitmap font, embedded in `.rodata` (licence recorded), or a font drawn for MOSKO. No heap, no file loading |
| Q5 | The heap | designed in 0.34 (§7), but **not** used by First Light. It is implemented only after its own D-ABR-012-style gate is approved |
| Q6 | The new judge | C14 "first light" on serial and screendump evidence (§8). A DIAGNOSTIC deterministic-frame build for exact pixel checks |
| Q7 | The cross-C toolchain | choose one of the options in §10 before any download |
| Q8 | NetSurf | hosted feasibility only (§11). Never kernel-space |

## 3. Framebuffer discovery and validation (requirement 1)

**Discovery.** Add a Limine `FRAMEBUFFER` request (base revision 6, as today).

**Validation.** Every field is checked before any write, and every refusal is reported:
- **Response:** present; framebuffer count at least 1. Use framebuffer 0; report the count.
- **Geometry:** `width` and `height` in 1..=8192; `bpp == 32`; `pitch >= width * 4`. All products use checked
  arithmetic.
- **Memory model** RGB (1).
- **Masks:** each size is 8, each shift is at most 24, and the three are non-overlapping and within 32 bits.
- **Extent:** `pitch * height` fits in u64, and the whole range lies inside one memory-map entry of type FRAMEBUFFER
  (cross-checked against Limine's memory map, which the kernel already validates).

**Serial lines** (registered in KERNEL_DIAGNOSTICS, kernel diagnostics under D-ABR-010/011):
- `ABR|FB|state=AVAILABLE|width=..|height=..|pitch=..|bpp=32|format=..|phys=0x..|bytes=..`, or
- `ABR|FB|state=ABSENT|reason=NO_RESPONSE|NO_FRAMEBUFFER|UNSUPPORTED_FORMAT|BAD_GEOMETRY|NOT_IN_MEMORY_MAP`.

**First step of 0.34: measure before relying.** Limine 12.9.6's HHDM carries no MMIO from base revision 3 (recorded
in ABR-BOOT-001). A DIAGNOSTIC probe build first reports, without writing a pixel:
- the framebuffer response;
- the memory-map entry;
- whether the HHDM address is mapped in the live page tables.

The mapping strategy (§4) is fixed by that measurement, not by assumption.

## 4. Safe mapping and address arithmetic (requirement 2)

**Mapping:**
- The framebuffer is mapped by the kernel's own page-table editor, which today maps the APIC page uncached. The
  mapping is write-through/uncached, or write-combining if the PAT is programmed and recorded.
- It is mapped at a fixed kernel virtual window, never wherever the HHDM happens to put it.
- The frames are recorded in the ownership ledger as `FRAMEBUFFER` (device memory, never in the allocator's pool).
- A live ownership check proves they never overlap an allocator, kernel or page-table frame.

**Address arithmetic:**
- Every pixel write goes through one function: `put(x, y)`, which checks `x < width` and `y < height`.
- The offset `y * pitch + x * 4` is computed with checked arithmetic and must stay below `bytes`.
- Text and rectangles call `put`, or a row-copy that checks the same bound once per row.
- No raw pointer arithmetic outside this module. Its `unsafe` is limited to the volatile store, with a SAFETY argument.

## 5. Deterministic rendering without a heap (requirement 3)

- Static buffers only: one font in `.rodata` and no back buffer. Drawing is direct and row-ordered; partial redraw is
  limited to the uptime and status fields.
- Rendering is a pure function of the state it shows: identical state gives identical pixels.
- A DIAGNOSTIC build `diag-fb-frame` draws a fixed test frame: colour bars, the font's full glyph table and a
  checksum line. Its pixels can then be compared exactly with an expected image in a hosted test, using the same
  drawing code built for the host.
- No floating point. No allocation. The drawing happens in the existing cooperative loop, bounded by a per-step budget
  measured like a service step.

## 6. The screen, the serial channel, and no framebuffer (requirements 4, 5, 6)

**The screen:**
- a title (`ABRAHAM`, with the SOLOMON line Jadin specifies);
- the kernel version and boot epoch;
- uptime, and the clock state (OK/DEGRADED);
- each service's state, status and reason;
- each application and its prerequisites;
- `executor ABSENT`.

The values come from the same status round the serial line prints. The screen never shows a value that serial did
not report in the same round.

**The serial channel:** every existing `ABR|` line is unchanged. C0-C13 must still pass with the display enabled; that
is part of C14.

**No usable framebuffer:**
- the kernel prints `ABR|FB|state=ABSENT|reason=...` once and continues exactly as 0.33 (serial only);
- OPERATIONAL is not delayed or withheld;
- no service depends on the screen;
- the launcher says "no display: the kernel reported ABSENT (reason)" and keeps the console view.

## 7. A bounded kernel heap, behind its own gate (requirement 7)

**Design only; First Light does not use it.**
- A fixed region of N frames, proposed 256 (1 MiB), taken once from the frame allocator at a lifecycle step after
  MEMORY_VERIFIED. It is recorded in the ledger as owner `HEAP`, and the live ownership check covers it.
- Fixed-size-class allocation (for example 16..2048 bytes), with no coalescing at first:
  - allocation never blocks;
  - exhaustion returns a refusal (`HEAP_EXHAUSTED`), never a panic;
  - every allocation and free is counted.
- **D-ABR-012-style failure safety:**
  - a double free latches the heap FAULTED and changes nothing;
  - a free of a pointer outside the region, or misaligned to its class, is refused and latched;
  - a corrupted free-list link (guard word) is detected before use.

  Each case gets its own hosted test and a DIAGNOSTIC VM run on WHPX and TCG, as D-ABR-012 required for the frame
  allocator.
- **Gate G-HEAP**, approved by Jadin, before any kernel code calls the heap.

## 8. Tests: positive, negative and falsified (every major interface)

| Interface | Positive | Negative | Falsified evidence (the judge must fail) |
|---|---|---|---|
| Discovery and validation | VGA device: `state=AVAILABLE` with exact geometry | no display device (today's `-nodefaults` command): `ABSENT/NO_FRAMEBUFFER`, still OPERATIONAL. DIAGNOSTIC builds forcing each refusal: `UNSUPPORTED_FORMAT`, `BAD_GEOMETRY`, `NOT_IN_MEMORY_MAP` | a log claiming AVAILABLE with bpp 24; geometry inconsistent with pitch; AVAILABLE when the QEMU command had no display device |
| Mapping and ownership | the live check shows FRAMEBUFFER frames disjoint from all others | DIAGNOSTIC: a framebuffer range overlapping a pool frame is refused (latched, no write) | a MEMCHECK summary hiding the overlap |
| Drawing bounds | hosted: every `put` inside the bounds writes exactly one pixel | hosted: x = width, y = height, and overflowing pitch times y are each refused, with no write (property test over all edges) | — |
| Determinism | `diag-fb-frame`: QMP screendump equals the expected image exactly, on WHPX and TCG | a different expected image fails | a screendump edited by one pixel fails |
| Screen versus serial | every value on screen equals the same round's serial value (screendump OCR-free: the DIAGNOSTIC build prints the drawn field strings on serial too) | — | a screen field contradicting serial |
| Serial preservation | C0-C13 PASS with the display on, WHPX and TCG | — | the 0.33 falsification sets (J001, J005/J007) still rejected |
| No framebuffer | OPERATIONAL, serial-only, `ABSENT` reported | — | a log claiming drawing after `ABSENT` |
| Heap (gate G-HEAP) | hosted allocation and free per class | exhaustion, double free, foreign pointer, guard corruption, each latched and refused | a MEMCHECK hiding the HEAP owner |

The launcher's live checks and `verify_run.py` gain C14. The official judge gains C14 under a new harness profile
0.34. Earlier profiles stay unchanged, and earlier kernels must still pass their own profiles.

## 9. Keyboard and input, preliminary design for 0.35 (requirement 8)

- **Device:** the q35 machine's i8042 PS/2 controller, on IRQ 1 through the IOAPIC (the legacy PIC stays masked).
  Scancode set 1 is decoded to key events.
- **Buffering:** a bounded ring of key events (fixed capacity; overflow counted, never blocking).
- **No authority:** input is data. A key event never grants anything. Any action it requests goes through the 0.33
  launcher's admission and authorization path, which today refuses everything.
- **Its own gates:** the controller self-test result reported on serial; the IRQ wiring verified; a DIAGNOSTIC build
  that injects keys through QMP `send-key` and checks the decoded events exactly.

## 10. A pinned cross-C toolchain, proposal only (requirement 9)

Needed later for C libraries (NetSurf's, a libc for ring 3). **Nothing is downloaded before Jadin chooses.**

| Option | What | For | Against |
|---|---|---|---|
| A | LLVM/clang + lld, official Windows release, one pinned version, SHA-256 and signature verified | targets freestanding x86_64-elf directly; lld is the same linker family Rust uses | a large download (several hundred MB); a libc still needed separately |
| B | Zig (pinned release) as a C cross-compiler (`zig cc`), with bundled musl headers | one archive; cross-compiles hosted and freestanding | a younger toolchain; its clang version is tied to Zig's |
| C | a musl-cross-make GCC toolchain built from pinned sources | the classic free-software path | needs a POSIX build host, which this Windows machine does not have (no MSYS2 is installed) |

**Recommendation:** A, pinned and recorded like QEMU 11.1.0 (D-ABR-004). The toolchain lives under
`%USERPROFILE%\abraham-toolchain\`, never on PATH.

## 11. NetSurf, GPL-2.0, and a hosted feasibility plan (requirement 11)

**The licence:**
- NetSurf's browser core is GPL-2.0. Several of its libraries (libcss, libdom, hubbub, libparserutils, libwapcaplet)
  carry MIT-style licences. Each must be confirmed from the pinned source release's own COPYING files before any use.
- **Never in kernel space.** Linking GPL-2.0 code into the Abraham kernel would make the combined kernel binary a
  derivative work under GPL-2.0.
- **As a separate user-space program** (ring 3, 0.37-0.4), loaded as an ELF and talking to the kernel through system
  calls, NetSurf remains a separate work. Distributing it needs its complete corresponding source and the GPL-2.0
  terms, and the kernel's licence is unaffected.
- This analysis must be confirmed by Jadin, and by counsel if MOSKO distributes binaries.

**The hosted feasibility plan** (no Abraham execution):
1. With the chosen toolchain, build NetSurf's MIT libraries and its framebuffer front end on the host.
2. Measure code size, memory peak, required system calls and libc surface.
3. Map each required system call to a future Abraham contract, and to the P-rules it would need (grants, audit,
   P-19's network limits).

The output is a report, not a binary in Abraham.

**P-19 preserved (requirement 10):**
- no general-purpose TCP/IP stack;
- networking stays option (a): virtio-net, link state, and the UDP management channel to the OpenWrt VM;
- external reachability is reported by OpenWrt.

A browser that needs HTTP would therefore fetch through a proxy path decided by a ratified baseline revision, not by a
TCP stack in Abraham. That revision is an open question for the owner.

## 12. Toward 0.37-0.4: isolation, ring 3, ELF loading, execution (requirement 12)

Each step is its own gated revision. None is part of First Light.
1. **Memory isolation:**
   - per-address-space page tables;
   - kernel mappings supervisor-only;
   - NX everywhere but code;
   - SMEP/SMAP where the CPU model allows (`-cpu host` on WHPX; TCG `max`).
2. **Ring 3:**
   - a TSS stack for privilege changes (the TSS already exists);
   - `syscall`/`sysret` with a validated entry;
   - a fixed, audited system-call table.
3. **Native ELF loading:**
   - static ELF64 only;
   - every header and segment validated against bounds and permissions;
   - no W+X;
   - loaded from a module Limine passes (no filesystem yet).
4. **Execution:**
   - the 0.33 launcher's executor goes from ABSENT to present only when P-09/P-30 (grants revalidated at use),
     P-17/P-46 (an audit store and receipts) and the Appendix A gaps G-1..G-3 are resolved;
   - RUNNING and the 0.4 states (reserved in 0.33) become reachable then, and not before.

## 13. Order of work, after approval

1. Probe build: framebuffer response, memory map, HHDM mapping (measurement only).
2. Discovery, validation, mapping, ownership; their hosted tests, VM tests and falsifications.
3. Drawing primitives and font (hosted-tested), then the screen; C14 and harness profile 0.34.
4. The launcher's display window (a launcher revision, with its own campaign).
5. The heap design document to gate G-HEAP (no heap code before its approval).
6. The input and toolchain proposals refined for 0.35; NetSurf feasibility once the toolchain is approved.
