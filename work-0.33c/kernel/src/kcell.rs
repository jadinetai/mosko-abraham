//! Single-CPU kernel cell (0.31b): exclusive access through a re-entry flag. A second access while
//! the first is in progress (only possible from a trap handler interrupting kmain) is refused with
//! `None`, never waited on and never allowed to alias. The same pattern memory.rs uses.

use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicBool, Ordering};

pub struct KCell<T> {
    busy: AtomicBool,
    value: UnsafeCell<T>,
}

// SAFETY: one CPU; `busy` serializes every access, so no two `&mut T` can exist at once.
unsafe impl<T> Sync for KCell<T> {}

impl<T> KCell<T> {
    pub const fn new(value: T) -> Self {
        KCell { busy: AtomicBool::new(false), value: UnsafeCell::new(value) }
    }

    pub fn with<R>(&self, f: impl FnOnce(&mut T) -> R) -> Option<R> {
        if self.busy.swap(true, Ordering::Acquire) {
            return None;
        }
        // SAFETY: `busy` was false and is now ours: this is the only reference.
        let r = f(unsafe { &mut *self.value.get() });
        self.busy.store(false, Ordering::Release);
        Some(r)
    }
}
