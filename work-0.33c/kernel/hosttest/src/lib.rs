//! Host test crate for `kernel/src/frame.rs` (ABRAHAM 0.31a). The kernel's own source file
//! is compiled here unchanged through `#[path]`; there is no copy that could drift.
//! Evidence label of everything run here: SIMULATED (hosted). It says nothing about the
//! running kernel; the VM runs do that.
//!
//! Ownership is enforced by the type system. This twin compiles (release, then never touch):
//!
//! ```
//! use abraham_frame_hosttest::frame::{FrameAllocator, Kind, Region};
//! let mut a = FrameAllocator::<1>::new();
//! a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
//! let f = a.alloc().unwrap();
//! let p = f.phys();
//! a.release(f).unwrap();
//! assert_eq!(p, 0x1000);
//! ```
//!
//! Using a frame after releasing it does not compile (moved value, E0382):
//!
//! ```compile_fail,E0382
//! use abraham_frame_hosttest::frame::{FrameAllocator, Kind, Region};
//! let mut a = FrameAllocator::<1>::new();
//! a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
//! let f = a.alloc().unwrap();
//! a.release(f).unwrap();
//! let _ = f.phys();
//! ```
//!
//! Releasing the same handle twice does not compile (E0382):
//!
//! ```compile_fail,E0382
//! use abraham_frame_hosttest::frame::{FrameAllocator, Kind, Region};
//! let mut a = FrameAllocator::<1>::new();
//! a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
//! let f = a.alloc().unwrap();
//! a.release(f).unwrap();
//! a.release(f).unwrap();
//! ```
//!
//! A frame cannot be forged outside the allocator (private field, E0451):
//!
//! ```compile_fail,E0451
//! use abraham_frame_hosttest::frame::Frame;
//! let _forged = Frame { phys: 0x5000 };
//! ```
//!
//! A frame cannot be duplicated (no Clone, E0599):
//!
//! ```compile_fail,E0599
//! use abraham_frame_hosttest::frame::{FrameAllocator, Kind, Region};
//! let mut a = FrameAllocator::<1>::new();
//! a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
//! let f = a.alloc().unwrap();
//! let g = f.clone();
//! ```
//!
//! A pinned page-table frame cannot be released afterwards: `pin` consumes the handle (E0382):
//!
//! ```compile_fail,E0382
//! use abraham_frame_hosttest::frame::{FrameAllocator, Kind, PinOwner, Region};
//! let mut a = FrameAllocator::<1>::new();
//! a.init([Region { base: 0x1000, length: 0x4000, kind: Kind::Usable }].into_iter(), &[]).unwrap();
//! let f = a.alloc().unwrap();
//! let _ = a.pin(f, PinOwner::PageTable);
//! a.release(f).unwrap();
//! ```
//!
//! 0.32 (D-ABR-019). A cyclic service table does not compile: the const check panics during evaluation (E0080).
//! This twin compiles (an acyclic table passes):
//!
//! ```
//! use abraham_frame_hosttest::svcregistry::{assert_valid, Desc, Kind, ServiceId};
//! const T: &[Desc] = &[
//!     Desc { id: ServiceId(1), name: "svc.a", kind: Kind::Service, installed: true, deps: &[], budget: 1 },
//!     Desc { id: ServiceId(2), name: "svc.b", kind: Kind::Service, installed: true, deps: &[ServiceId(1)], budget: 1 },
//! ];
//! const _: () = assert_valid(T);
//! ```
//!
//! The same table with a cycle does not:
//!
//! ```compile_fail,E0080
//! use abraham_frame_hosttest::svcregistry::{assert_valid, Desc, Kind, ServiceId};
//! const T: &[Desc] = &[
//!     Desc { id: ServiceId(1), name: "svc.a", kind: Kind::Service, installed: true, deps: &[ServiceId(2)], budget: 1 },
//!     Desc { id: ServiceId(2), name: "svc.b", kind: Kind::Service, installed: true, deps: &[ServiceId(1)], budget: 1 },
//! ];
//! const _: () = assert_valid(T);
//! ```
//!
//! A public reason is one of the 27 Appendix A codes, chosen by name in the code. This twin compiles:
//!
//! ```
//! use abraham_frame_hosttest::svcstatus::PublicReason;
//! let r = PublicReason::NotInstalled;
//! assert_eq!(r.name(), "NOT_INSTALLED");
//! ```
//!
//! A kernel diagnostic code (any string) cannot become a public reason: there is no conversion (E0277):
//!
//! ```compile_fail,E0277
//! use abraham_frame_hosttest::svcstatus::PublicReason;
//! let r: PublicReason = "FRAME_DOUBLE_RELEASE".into();
//! ```
//!
//! 0.33 (D-ABR-022): execution cannot be manufactured. Evidence of a started executable cannot be forged outside
//! launchlife.rs (private field, E0451):
//!
//! ```compile_fail,E0451
//! use abraham_frame_hosttest::launchlife::ExecutionEvidence;
//! let _forged = ExecutionEvidence { _private: () };
//! ```
//!
//! A request lifecycle cannot be moved from outside the launcher (`advance` is crate-private, E0624):
//!
//! ```compile_fail,E0624
//! use abraham_frame_hosttest::launchlife::{Life, RequestState};
//! let mut l = Life::new();
//! let _ = l.advance(RequestState::Running);
//! ```
//!
//! A launch result has no public constructor (E0599):
//!
//! ```compile_fail,E0599
//! use abraham_frame_hosttest::launch::LaunchResult;
//! let _r = LaunchResult::new();
//! ```
//!
//! The compiling twin: a lifecycle can be read and checked, and the check refuses RUNNING:
//!
//! ```
//! use abraham_frame_hosttest::launchlife::{Life, RequestState};
//! let l = Life::new();
//! assert_eq!(l.state(), RequestState::Submitted);
//! assert!(l.check(RequestState::Running).is_err());
//! ```
#![no_std]

// The cfg(test) unit tests inside the kernel modules need the test harness's std.
#[cfg(test)]
extern crate std;

#[path = "../../src/frame.rs"]
pub mod frame;
#[path = "../../src/clockguard.rs"]
pub mod clockguard;
#[path = "../../src/lifecycle.rs"]
pub mod lifecycle;
#[path = "../../src/events.rs"]
pub mod events;
// 0.32 service modules (D-ABR-019), compiled unchanged from the kernel's own sources.
#[path = "../../src/svcregistry.rs"]
pub mod svcregistry;
#[path = "../../src/svclife.rs"]
pub mod svclife;
#[path = "../../src/svcstatus.rs"]
pub mod svcstatus;
#[path = "../../src/svcrun.rs"]
pub mod svcrun;
#[path = "../../src/svctable.rs"]
pub mod svctable;
#[path = "../../src/svc_counter.rs"]
pub mod svc_counter;
// 0.33 application registry and launcher (D-ABR-022), compiled unchanged from the kernel's own sources.
#[path = "../../src/appregistry.rs"]
pub mod appregistry;
#[path = "../../src/apptable.rs"]
pub mod apptable;
#[path = "../../src/launchreq.rs"]
pub mod launchreq;
#[path = "../../src/launchlife.rs"]
pub mod launchlife;
#[path = "../../src/launch.rs"]
pub mod launch;
