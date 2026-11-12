//! The console window: a fixed status panel at the top and the kernel's serial console scrolling below it (when the
//! console understands VT sequences), or plain lines (when the output is redirected). Everything shown is also
//! written to the run's `console.txt`, in plain text, so the record says what the operator saw.

use crate::win;
use std::fs::File;
use std::io::Write;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Color {
    Normal,
    Dim,
    Info,
    App,
    Launch,
    Good,
    Warn,
    Bad,
    Title,
}

fn code(c: Color) -> &'static str {
    match c {
        Color::Normal => "\x1b[0m",
        Color::Dim => "\x1b[90m",
        Color::Info => "\x1b[36m",
        Color::App => "\x1b[95m",
        Color::Launch => "\x1b[33m",
        Color::Good => "\x1b[92m",
        Color::Warn => "\x1b[93m",
        Color::Bad => "\x1b[91m",
        Color::Title => "\x1b[1;96m",
    }
}

pub struct PanelRow {
    pub color: Color,
    pub text: String,
    /// The part of the row that matters for the record (no counters or timers). Plain output and console.txt print a
    /// row only when this changes.
    pub stable: String,
}

pub struct Ui {
    vt: bool,
    out: win::HANDLE,
    panel_on: bool,
    panel_h: usize,
    rows: usize,
    cols: usize,
    transcript: Option<File>,
    pending: Vec<String>,
    last_stable: Vec<String>,
    last_rows: Vec<(Color, String)>,
}

impl Ui {
    pub fn new(con: &win::Console, force_plain: bool) -> Ui {
        Ui {
            vt: con.vt && !force_plain,
            out: con.out,
            panel_on: false,
            panel_h: 0,
            rows: 0,
            cols: 0,
            transcript: None,
            pending: Vec::new(),
            last_stable: Vec::new(),
            last_rows: Vec::new(),
        }
    }

    pub fn is_vt(&self) -> bool {
        self.vt
    }

    fn out(&self, s: &str) {
        let mut o = std::io::stdout().lock();
        let _ = o.write_all(s.as_bytes());
        let _ = o.flush();
    }

    fn record(&mut self, s: &str) {
        match &mut self.transcript {
            Some(f) => {
                let _ = f.write_all(s.as_bytes());
                let _ = f.write_all(b"\r\n");
            }
            None => self.pending.push(s.to_string()),
        }
    }

    /// Recorded in console.txt, not shown (hidden heartbeat lines).
    pub fn record_only(&mut self, s: &str) {
        self.record(s);
    }

    /// Starts writing console.txt; what was shown before the run folder existed is written first.
    pub fn set_transcript(&mut self, mut f: File) {
        for s in self.pending.drain(..) {
            let _ = f.write_all(s.as_bytes());
            let _ = f.write_all(b"\r\n");
        }
        self.transcript = Some(f);
    }

    pub fn close_transcript(&mut self) {
        if let Some(f) = &mut self.transcript {
            let _ = f.flush();
        }
        self.transcript = None;
    }

    /// Prints one line (wrapping if long) and records it.
    pub fn line(&mut self, color: Color, s: &str) {
        self.record(s);
        if self.vt {
            if self.panel_on {
                self.check_size();
                self.out(&format!("\r\n{}{}\x1b[0m", code(color), s));
            } else {
                self.out(&format!("{}{}\x1b[0m\r\n", code(color), s));
            }
        } else {
            self.out(&format!("{s}\r\n"));
        }
    }

    pub fn msg(&mut self, color: Color, s: &str) {
        self.line(color, &format!("[launcher] {s}"));
    }

    /// Shown on screen only (not recorded): used for prompts.
    pub fn screen_only(&mut self, color: Color, s: &str) {
        if self.vt {
            if self.panel_on {
                self.out(&format!("\r\n{}{}\x1b[0m", code(color), s));
            } else {
                self.out(&format!("{}{}\x1b[0m\r\n", code(color), s));
            }
        } else {
            self.out(&format!("{s}\r\n"));
        }
    }

    pub fn start_panel(&mut self, height: usize) {
        if !self.vt {
            return;
        }
        if let Some((rows, cols)) = win::console_size(self.out) {
            if rows < height + 5 || cols < 40 {
                return; // too small for a fixed panel: plain lines instead
            }
            self.rows = rows;
            self.cols = cols;
            self.panel_h = height;
            self.panel_on = true;
            // The live view uses the console's alternate screen, which is exactly the window's size: on the normal
            // screen, text printed before the panel can scroll the viewport so that the panel is drawn where the
            // window is not looking (found in the dry run, DRY-A009).
            self.out(&format!("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H\x1b[{};{}r\x1b[{};1H", height + 1, rows, rows));
        }
    }

    fn check_size(&mut self) {
        if let Some((rows, cols)) = win::console_size(self.out) {
            if rows != self.rows || cols != self.cols {
                self.rows = rows;
                self.cols = cols;
                if rows < self.panel_h + 5 || cols < 40 {
                    self.out("\x1b[r");
                    self.panel_on = false;
                    return;
                }
                self.out(&format!("\x1b[{};{}r\x1b[{};1H", self.panel_h + 1, rows, rows));
            }
        }
    }

    pub fn panel(&mut self, rows: &[PanelRow]) {
        if self.last_stable.len() != rows.len() {
            self.last_stable = vec![String::new(); rows.len()];
        }
        let mut changed = Vec::new();
        for (i, r) in rows.iter().enumerate() {
            if r.stable != self.last_stable[i] {
                self.last_stable[i] = r.stable.clone();
                if !r.stable.is_empty() {
                    changed.push((r.color, r.stable.clone()));
                }
            }
        }
        if self.panel_on {
            self.check_size();
        }
        self.last_rows = rows.iter().map(|r| (r.color, r.text.clone())).collect();
        if self.panel_on {
            let width = self.cols.saturating_sub(1);
            let mut s = String::from("\x1b7");
            for (i, r) in rows.iter().take(self.panel_h).enumerate() {
                let text: String = r.text.chars().take(width).collect();
                s.push_str(&format!("\x1b[{};1H\x1b[2K{}{}\x1b[0m", i + 1, code(r.color), text));
            }
            s.push_str("\x1b8");
            self.out(&s);
            for (_, text) in changed {
                self.record(&format!("[status] {text}"));
            }
        } else {
            for (c, text) in changed {
                self.line(c, &format!("[status] {text}"));
            }
        }
    }

    /// Leaves the live view: back to the normal screen, where the final state of the panel is printed once more,
    /// above the result block, so it stays readable after the VM has stopped.
    pub fn end_panel(&mut self) {
        if self.panel_on {
            self.out("\x1b[r\x1b[?25h\x1b[?1049l");
            self.panel_on = false;
            let rows = std::mem::take(&mut self.last_rows);
            for (c, t) in rows.iter().take(self.panel_h.saturating_sub(1)) {
                self.screen_only(*c, t);
            }
        } else if self.vt {
            self.out("\x1b[?25h");
        }
    }
}
