//! COM1 (16550 UART) output: the kernel's only display path for ABR-BOOT-001 (P-14).

use crate::cpu::io::{inb, outb};
use core::fmt;

const COM1: u16 = 0x3F8;

pub fn init() {
    // SAFETY: COM1 is a fixed legacy I/O port range on the q35 machine.
    unsafe {
        outb(COM1 + 1, 0x00); // interrupts off
        outb(COM1 + 3, 0x80); // DLAB on
        outb(COM1, 0x01); // divisor 1: 115200 baud
        outb(COM1 + 1, 0x00);
        outb(COM1 + 3, 0x03); // 8N1, DLAB off
        outb(COM1 + 2, 0xC7); // FIFO on, cleared, 14-byte threshold
        outb(COM1 + 4, 0x0B); // DTR, RTS, OUT2
    }
}

fn write_byte(byte: u8) {
    // SAFETY: as in init().
    unsafe {
        while inb(COM1 + 5) & 0x20 == 0 {}
        outb(COM1, byte);
    }
}

pub struct Serial;

impl fmt::Write for Serial {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        for byte in s.bytes() {
            if byte == b'\n' {
                write_byte(b'\r');
            }
            write_byte(byte);
        }
        Ok(())
    }
}

#[macro_export]
macro_rules! kprintln {
    ($($arg:tt)*) => {{
        use core::fmt::Write as _;
        let _ = writeln!($crate::serial::Serial, $($arg)*);
    }};
}
