//! ABRAHAM VM LAUNCHER 0.33 (D-ABR-024): a host-side Windows utility that boots a pinned Abraham kernel in the pinned
//! QEMU with the 0.33 harness's validated configuration, shows the kernel's serial console with a live status panel,
//! shuts the VM down through QMP, and seals a record of every launch.
//!
//! It launches the virtual machine only. It is not part of Abraham, it is not Abraham's internal application launcher
//! (that is `work-0.33/kernel/src/launch*.rs`, which it never touches), it provides no graphical desktop, and it runs
//! no Windows program inside Abraham.

mod hash;
mod json;
mod observe;
mod pins;
mod qmp;
mod ui;
mod util;
mod win;

use json::{Obj, J};
use observe::{Boot, Observer, Verdict};
use pins::{Build, KernelPin};
use std::fs::{self, File};
use std::io::{Read, Seek, SeekFrom};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::mpsc::{channel, Receiver};
use std::sync::{Condvar, Mutex};
use std::time::{Duration, Instant};
use ui::{Color, PanelRow, Ui};

const VERSION: &str = "0.33.2";
const MUTEX_NAME: &str = "Local\\MOSKO-Abraham-VM-Launcher-0.33";
const PANEL_HEIGHT: usize = 8;

/// Exit codes (also in the README).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Outcome {
    Ok = 0,
    BootFailed = 1,
    Integrity = 2,
    Missing = 3,
    Duplicate = 4,
    VmTerminated = 5,
    ContractInconsistent = 6,
    LauncherError = 7,
    ShutdownNotClean = 8,
    Cancelled = 9,
    /// 0.33.1 (F-VML-02): a services problem no longer gets the contract's name.
    ServicesNotAsDesigned = 10,
    /// 0.33.2 (D-ABR-026 3A): the kernel reported a clock anomaly that host evidence does not explain.
    ClockCauseNotEstablished = 11,
}

impl Outcome {
    fn name(self) -> &'static str {
        match self {
            Outcome::Ok => "OK",
            Outcome::BootFailed => "BOOT_FAILED",
            Outcome::Integrity => "REFUSED_INTEGRITY",
            Outcome::Missing => "REFUSED_MISSING_DEPENDENCY",
            Outcome::Duplicate => "REFUSED_DUPLICATE_LAUNCH",
            Outcome::VmTerminated => "VM_TERMINATED_UNEXPECTEDLY",
            Outcome::ContractInconsistent => "LAUNCHER_CONTRACT_INCONSISTENT",
            Outcome::LauncherError => "LAUNCHER_ERROR",
            Outcome::ShutdownNotClean => "SHUTDOWN_NOT_CLEAN",
            Outcome::Cancelled => "CANCELLED",
            Outcome::ServicesNotAsDesigned => "SERVICES_NOT_AS_DESIGNED",
            Outcome::ClockCauseNotEstablished => "CLOCK_ANOMALY_CAUSE_NOT_ESTABLISHED",
        }
    }
}

// ---- console control events (Ctrl+C, closing the window, log-off) --------------------------------------------------

/// 0: none; otherwise 1 + the console control event.
static STOP_EVENT: AtomicU32 = AtomicU32::new(0);
static VM_RUNNING: AtomicBool = AtomicBool::new(false);
static CLEANUP: (Mutex<bool>, Condvar) = (Mutex::new(false), Condvar::new());

unsafe extern "system" fn on_console_event(ev: u32) -> win::BOOL {
    if !VM_RUNNING.load(Ordering::SeqCst) {
        return 0; // nothing to protect: the default handling ends the program
    }
    STOP_EVENT.store(ev + 1, Ordering::SeqCst);
    if matches!(ev, win::CTRL_CLOSE_EVENT | win::CTRL_LOGOFF_EVENT | win::CTRL_SHUTDOWN_EVENT) {
        // Windows ends the process when this returns (or after about 5 s): wait for the controlled shutdown first.
        let (m, cv) = &CLEANUP;
        if let Ok(g) = m.lock() {
            let _ = cv.wait_timeout_while(g, Duration::from_millis(4500), |done| !*done);
        }
    }
    1
}

fn cleanup_done() {
    VM_RUNNING.store(false, Ordering::SeqCst);
    let (m, cv) = &CLEANUP;
    if let Ok(mut g) = m.lock() {
        *g = true;
    }
    cv.notify_all();
}

fn stop_reason(ev: u32) -> &'static str {
    match ev.saturating_sub(1) {
        win::CTRL_C_EVENT => "Ctrl+C in the launcher window",
        win::CTRL_BREAK_EVENT => "Ctrl+Break in the launcher window",
        win::CTRL_CLOSE_EVENT => "the launcher window was closed",
        win::CTRL_LOGOFF_EVENT => "the user is logging off",
        win::CTRL_SHUTDOWN_EVENT => "Windows is shutting down",
        _ => "a console control event",
    }
}

// ---- arguments ------------------------------------------------------------------------------------------------------

struct Args {
    kernel: Option<String>,
    accel: Option<String>,
    run_id: Option<String>,
    runs_dir: Option<PathBuf>,
    home: Option<PathBuf>,
    qemu_dir: Option<PathBuf>,
    auto_stop_after: Option<f64>,
    boot_timeout: f64,
    plain: bool,
    no_wait: bool,
    check_serial: Option<PathBuf>,
    raw: Vec<String>,
}

const USAGE: &str = "ABRAHAM VM LAUNCHER 0.33.2 (host utility; MOSKO Laboratory 001)

Double-click to start: a menu offers the pinned kernels. No options are needed for normal use.

Options (for tests and diagnostics):
  --kernel production|launchpad|early-fail   boot this kernel without the menu
  --accel whpx|tcg                           accelerator (default whpx, the counted configuration)
  --auto-stop-after S                        stop the VM S seconds after OPERATIONAL or after a failed boot
  --boot-timeout S                           OPERATIONAL must be reached within S seconds (default 120)
  --run-id ID                                name of the run folder (must be unused)
  --runs-dir DIR                             where run folders go (default: runs\\ next to the program)
  --home DIR                                 Abraham home folder (default: the folder above the program)
  --qemu-dir DIR                             QEMU folder (default: %USERPROFILE%\\abraham-toolchain\\qemu\\11.1.0-weil-20260811)
  --plain                                    plain lines, no status panel
  --no-wait                                  do not wait for a key before closing
  --check-serial FILE --kernel K             apply the live checks to a saved serial log and print the verdicts
Digests are compiled in and cannot be overridden.
Exit codes: 0 OK, 1 boot failed, 2 integrity refused, 3 missing dependency, 4 duplicate launch refused,
  5 VM terminated unexpectedly, 6 launcher contract inconsistent, 7 launcher error, 8 shutdown not clean, 9 cancelled,
  10 services not as designed, 11 clock anomaly whose cause host evidence does not establish.";

fn parse_args() -> Result<Args, String> {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut a = Args {
        kernel: None,
        accel: None,
        run_id: None,
        runs_dir: None,
        home: None,
        qemu_dir: None,
        auto_stop_after: None,
        boot_timeout: 120.0,
        plain: false,
        no_wait: false,
        check_serial: None,
        raw: raw.clone(),
    };
    let mut it = raw.into_iter();
    while let Some(k) = it.next() {
        let mut val = || it.next().ok_or_else(|| format!("{k} needs a value"));
        match k.as_str() {
            "--kernel" => {
                let v = val()?;
                if pins::kernel(&v).is_none() {
                    return Err(format!("unknown kernel {v}"));
                }
                a.kernel = Some(v)
            }
            "--accel" => {
                let v = val()?;
                if v != "whpx" && v != "tcg" {
                    return Err(format!("unknown accelerator {v}"));
                }
                a.accel = Some(v)
            }
            "--run-id" => {
                let v = val()?;
                if v.is_empty() || !v.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c)) || v.starts_with('.') {
                    return Err(format!("bad run id {v}"));
                }
                a.run_id = Some(v)
            }
            "--runs-dir" => a.runs_dir = Some(PathBuf::from(val()?)),
            "--home" => a.home = Some(PathBuf::from(val()?)),
            "--qemu-dir" => a.qemu_dir = Some(PathBuf::from(val()?)),
            "--auto-stop-after" => a.auto_stop_after = Some(val()?.parse().map_err(|_| "bad --auto-stop-after")?),
            "--boot-timeout" => a.boot_timeout = val()?.parse().map_err(|_| "bad --boot-timeout")?,
            "--check-serial" => a.check_serial = Some(PathBuf::from(val()?)),
            "--plain" => a.plain = true,
            "--no-wait" => a.no_wait = true,
            "--help" | "-h" | "/?" => return Err(String::new()),
            other => return Err(format!("unknown option {other}")),
        }
    }
    Ok(a)
}

// ---- main -----------------------------------------------------------------------------------------------------------

fn main() {
    std::process::exit(real_main());
}

fn real_main() -> i32 {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            if !e.is_empty() {
                eprintln!("{e}\n");
            }
            eprintln!("{USAGE}");
            return if e.is_empty() { 0 } else { Outcome::LauncherError as i32 };
        }
    };
    if let Some(p) = &args.check_serial {
        return check_serial(p, args.kernel.as_deref().unwrap_or("production"));
    }
    let con = win::console();
    let owns_console = con.out_is_console && win::console_process_count() <= 1;
    let wait_at_end = owns_console && con.in_is_console && !args.no_wait;
    let mut ui = Ui::new(&con, args.plain);
    win::set_ctrl_handler(on_console_event);
    win::set_title("Abraham VM Launcher 0.33");
    let keys = key_reader(con.in_is_console);

    let choice = match (&args.kernel, con.in_is_console) {
        (Some(k), _) => Some((pins::kernel(k).unwrap(), args.accel.clone().unwrap_or_else(|| "whpx".into()))),
        (None, true) => menu(&mut ui, &args, &keys),
        (None, false) => Some((&pins::KERNELS[0], args.accel.clone().unwrap_or_else(|| "whpx".into()))),
    };
    let outcome = match choice {
        None => {
            ui.screen_only(Color::Normal, "Cancelled: nothing was started.");
            Outcome::Cancelled
        }
        Some((kernel, accel)) => launch(&args, &mut ui, kernel, &accel, &keys, owns_console),
    };
    cleanup_done();
    if wait_at_end {
        ui.screen_only(Color::Title, "Press any key to close this window.");
        while keys.try_recv().is_ok() {}
        let _ = keys.recv();
    }
    outcome as i32
}

/// Key presses, from the console (no Enter needed) or from redirected standard input (tests).
fn key_reader(console: bool) -> Receiver<u8> {
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        if console {
            loop {
                let c = win::getch();
                if c == 0 || c == 0xe0 {
                    let _ = win::getch(); // the second half of an arrow or function key
                    continue;
                }
                if tx.send(c as u8).is_err() {
                    break;
                }
            }
        } else {
            let mut stdin = std::io::stdin();
            let mut b = [0u8; 1];
            while let Ok(1) = stdin.read(&mut b) {
                if tx.send(b[0]).is_err() {
                    break;
                }
            }
        }
    });
    rx
}

struct Paths {
    home: PathBuf,
    qemu_dir: PathBuf,
    runs: PathBuf,
    exe: PathBuf,
    overrides: Vec<(String, String)>,
}

fn paths(args: &Args) -> Paths {
    let exe = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("Abraham-VM-Launcher.exe"));
    let exe_dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    let profile = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default();
    let mut overrides = Vec::new();
    let home = match &args.home {
        Some(h) => {
            overrides.push(("home".to_string(), h.display().to_string()));
            h.clone()
        }
        None => exe_dir.parent().map(Path::to_path_buf).unwrap_or_default(),
    };
    let qemu_dir = match &args.qemu_dir {
        Some(q) => {
            overrides.push(("qemu_dir".to_string(), q.display().to_string()));
            q.clone()
        }
        None => profile.join(pins::QEMU_DIR_UNDER_PROFILE),
    };
    let runs = match &args.runs_dir {
        Some(r) => {
            overrides.push(("runs_dir".to_string(), r.display().to_string()));
            r.clone()
        }
        None => exe_dir.join("runs"),
    };
    // QEMU gets absolute paths, as from the harness (a relative --runs-dir once reached QEMU as given: DEV-002).
    let abs = |p: PathBuf| std::path::absolute(&p).unwrap_or(p);
    Paths { home: abs(home), qemu_dir: abs(qemu_dir), runs: abs(runs), exe, overrides }
}

fn kernel_state(home: &Path, k: &KernelPin) -> &'static str {
    match fs::read(home.join(k.rel_path)) {
        Err(_) => "MISSING",
        Ok(b) if hash::sha256_hex(&b) == k.sha256 => "verified",
        Ok(_) => "DIGEST MISMATCH",
    }
}

fn menu(ui: &mut Ui, args: &Args, keys: &Receiver<u8>) -> Option<(&'static KernelPin, String)> {
    let p = paths(args);
    let mut accel = args.accel.clone().unwrap_or_else(|| "whpx".into());
    let states: Vec<&str> = pins::KERNELS.iter().map(|k| kernel_state(&p.home, k)).collect();
    loop {
        ui.screen_only(Color::Title, "");
        ui.screen_only(Color::Title, "  ABRAHAM VM LAUNCHER 0.33.2   MOSKO Laboratory 001 - Pripyat");
        ui.screen_only(Color::Normal, "  A host-side utility: it boots the native Abraham kernel in QEMU and shows its serial console.");
        ui.screen_only(Color::Dim, "  It does not give Abraham a graphical desktop, and it runs no Windows program inside Abraham.");
        ui.screen_only(Color::Normal, "");
        ui.screen_only(Color::Normal, "  Choose the kernel to boot:");
        for (i, k) in pins::KERNELS.iter().enumerate() {
            let c = if states[i] == "verified" { Color::Normal } else { Color::Bad };
            ui.screen_only(c, &format!("    {}  {:<72} {}...  [{}]", i + 1, k.menu, &k.sha256[..12], states[i]));
        }
        ui.screen_only(
            Color::Normal,
            &format!(
                "    A  accelerator: {}   (press A to switch; WHPX is the counted configuration, TCG is slower and informational)",
                accel.to_uppercase()
            ),
        );
        ui.screen_only(Color::Normal, "    Esc  close without starting anything");
        ui.screen_only(Color::Title, "  Press 1, 2 or 3 (Enter = 1).");
        loop {
            let c = match keys.recv() {
                Ok(c) => c,
                Err(_) => return None,
            };
            match c {
                b'1' | b'\r' | b'\n' => return Some((&pins::KERNELS[0], accel)),
                b'2' => return Some((&pins::KERNELS[1], accel)),
                b'3' => return Some((&pins::KERNELS[2], accel)),
                b'a' | b'A' => {
                    accel = if accel == "whpx" { "tcg".into() } else { "whpx".into() };
                    break;
                }
                27 | b'q' | b'Q' => return None,
                _ => {}
            }
        }
    }
}

// ---- one launch -----------------------------------------------------------------------------------------------------

struct Rec {
    t0: Instant,
    timeline: Vec<(f64, String)>,
}

impl Rec {
    fn mark(&mut self, what: impl Into<String>) {
        self.timeline.push((self.t0.elapsed().as_secs_f64(), what.into()));
    }
}

struct Input {
    name: &'static str,
    path: PathBuf,
    expected: &'static str,
    actual: Option<String>,
    status: &'static str,
    bytes: Option<Vec<u8>>,
}

fn check_input(name: &'static str, path: PathBuf, expected: &'static str, keep: bool) -> Input {
    let mut i = Input { name, path, expected, actual: None, status: "OK", bytes: None };
    if !i.path.exists() {
        i.status = "MISSING";
        return i;
    }
    if !i.path.is_file() {
        i.status = "NOT A FILE";
        return i;
    }
    let digest = if keep {
        match fs::read(&i.path) {
            Ok(b) => {
                let d = hash::sha256_hex(&b);
                i.bytes = Some(b);
                Ok(d)
            }
            Err(e) => Err(e),
        }
    } else {
        hash::sha256_file(&i.path)
    };
    match digest {
        Err(_) => i.status = "UNREADABLE",
        Ok(d) => {
            if d != expected {
                i.status = "DIGEST MISMATCH";
            }
            i.actual = Some(d);
        }
    }
    i
}

fn host_info() -> J {
    let bios = r"HARDWARE\DESCRIPTION\System\BIOS";
    let nt = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion";
    let mut o = Obj::new();
    o.put("computer_manufacturer", J::opt_s(win::reg_string(bios, "SystemManufacturer")))
        .put("computer_model", J::opt_s(win::reg_string(bios, "SystemProductName")))
        .put("windows_product", J::opt_s(win::reg_string(nt, "ProductName")))
        .put("windows_display_version", J::opt_s(win::reg_string(nt, "DisplayVersion")))
        .put("windows_build", J::opt_s(win::reg_string(nt, "CurrentBuild")))
        .put(
            "windows_family",
            J::s(match win::reg_string(nt, "CurrentBuild").and_then(|b| b.parse::<u32>().ok()) {
                Some(b) if b >= 22000 => "Windows 11 (build 22000 or later; the registry ProductName still says Windows 10)",
                Some(_) => "Windows 10",
                None => "unknown",
            }),
        );
    o.build()
}

fn free_port() -> Result<u16, String> {
    let l = std::net::TcpListener::bind("127.0.0.1:0").map_err(|e| format!("no free local port: {e}"))?;
    Ok(l.local_addr().map_err(|e| e.to_string())?.port())
}

fn allocate_run(runs: &Path, wanted: &Option<String>) -> Result<(String, PathBuf), String> {
    fs::create_dir_all(runs).map_err(|e| format!("cannot create the runs folder {}: {e}", runs.display()))?;
    if let Some(id) = wanted {
        let dir = runs.join(id);
        return match fs::create_dir(&dir) {
            Ok(()) => Ok((id.clone(), dir)),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                Err(format!("run folder {} exists: run ids are never reused", dir.display()))
            }
            Err(e) => Err(format!("cannot create {}: {e}", dir.display())),
        };
    }
    let base = format!("VML-{}", util::stamp());
    for n in 1..1000 {
        let id = if n == 1 { base.clone() } else { format!("{base}-{n}") };
        let dir = runs.join(&id);
        match fs::create_dir(&dir) {
            Ok(()) => return Ok((id, dir)),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("cannot create {}: {e}", dir.display())),
        }
    }
    Err("no free run id".into())
}

fn same_path(a: &str, b: &Path) -> bool {
    let norm = |s: &str| s.replace('/', "\\").trim_end_matches('\\').to_ascii_lowercase();
    norm(a) == norm(&b.to_string_lossy())
}

struct Run<'a> {
    /// 0.33.2: per kernel-reported clock gap, the length of the launcher's own stop at the same time (host evidence of
    /// a suspension), or None when the launcher kept running.
    gap_evidence: Vec<Option<f64>>,
    /// Every stop of the launcher's own loop longer than 2 s: (seconds since resume at its end, length).
    stalls: Vec<(f64, f64)>,
    ui: &'a mut Ui,
    args: &'a Args,
    kernel: &'static KernelPin,
    accel: String,
    p: Paths,
    run_id: String,
    dir: PathBuf,
    rec: Rec,
    record: Obj,
    started: String,
}

fn launch(args: &Args, ui: &mut Ui, kernel: &'static KernelPin, accel: &str, keys: &Receiver<u8>, owns: bool) -> Outcome {
    let p = paths(args);
    let started = util::utc();
    let (run_id, dir) = match allocate_run(&p.runs, &args.run_id) {
        Ok(x) => x,
        Err(e) => {
            ui.msg(Color::Bad, &format!("CANNOT START: {e}. Nothing was started and no record could be written."));
            return Outcome::LauncherError;
        }
    };
    match File::create(dir.join("console.txt")) {
        Ok(f) => ui.set_transcript(f),
        Err(e) => ui.msg(Color::Bad, &format!("console.txt could not be created: {e}")),
    }
    win::set_title(&format!("Abraham VM Launcher 0.33 - {run_id}"));
    let mut run = Run {
        gap_evidence: Vec::new(),
        stalls: Vec::new(),
        ui,
        args,
        kernel,
        accel: accel.to_string(),
        p,
        run_id,
        dir,
        rec: Rec { t0: Instant::now(), timeline: Vec::new() },
        record: Obj::new(),
        started,
    };
    let outcome = run.go(keys, owns);
    outcome
}

impl<'a> Run<'a> {
    fn msg(&mut self, c: Color, s: &str) {
        self.ui.msg(c, s);
    }

    fn go(&mut self, keys: &Receiver<u8>, owns: bool) -> Outcome {
        let exe_sha = hash::sha256_file(&self.p.exe).unwrap_or_else(|e| format!("UNREADABLE: {e}"));
        self.msg(Color::Title, &format!("ABRAHAM VM LAUNCHER {VERSION} - run {} - started {}", self.run_id, self.started));
        self.msg(Color::Normal, &format!("record folder: {}", self.dir.display()));
        let mut l = Obj::new();
        l.put("version", J::s(VERSION))
            .put("exe", J::s(self.p.exe.display().to_string()))
            .put("exe_sha256", J::s(exe_sha))
            .put("pid", J::n(win::current_pid()))
            .put("elevated", win::elevated().map(J::Bool).unwrap_or(J::Null))
            .put("console", J::s(if self.ui.is_vt() { "status panel (VT)" } else { "plain lines" }))
            .put("console_created_for_this_program", J::Bool(owns))
            .put("arguments", J::Arr(self.args.raw.iter().map(|s| J::s(s.clone())).collect()))
            .put(
                "path_overrides",
                J::Obj(self.p.overrides.iter().map(|(k, v)| (k.clone(), J::s(v.clone()))).collect()),
            );
        self.record
            .put("record", J::s("ABRAHAM VM LAUNCHER run record (D-ABR-024)"))
            .put("run_id", J::s(self.run_id.clone()))
            .put("started_utc", J::s(self.started.clone()))
            .put("launcher", l.build())
            .put("host", host_info())
            .put("accelerator", J::s(self.accel.clone()))
            .put("cpu_model", J::s(if self.accel == "whpx" { "host" } else { "max" }));
        if !self.p.overrides.is_empty() {
            let o: Vec<String> = self.p.overrides.iter().map(|(k, v)| format!("{k}={v}")).collect();
            self.msg(Color::Warn, &format!("TEST CONFIGURATION: path overrides {} (digests are still the pinned ones)", o.join(", ")));
        }
        if win::elevated() == Some(true) {
            self.msg(Color::Warn, "this launcher is running elevated (as administrator); it does not need to");
        }

        // 1. Duplicate launches.
        let (_mutex, other) = win::named_mutex(MUTEX_NAME);
        let pinned_exe = self.p.qemu_dir.join(pins::QEMU_EXE);
        let procs = win::processes();
        let pinned: Vec<J> = procs
            .iter()
            .filter(|q| q.image.as_deref().map(|i| same_path(i, &pinned_exe)).unwrap_or(false))
            .map(|q| J::s(format!("pid {} {}", q.pid, q.image.clone().unwrap_or_default())))
            .collect();
        let others: Vec<J> = procs
            .iter()
            .filter(|q| q.exe_name.to_ascii_lowercase().starts_with("qemu-system"))
            .filter(|q| !q.image.as_deref().map(|i| same_path(i, &pinned_exe)).unwrap_or(false))
            .map(|q| J::s(format!("pid {} {}", q.pid, q.image.clone().unwrap_or_else(|| q.exe_name.clone()))))
            .collect();
        let mut d = Obj::new();
        d.put("mutex", J::s(MUTEX_NAME))
            .put("another_launcher_running", J::Bool(other))
            .put("pinned_qemu_processes_running", J::Arr(pinned.clone()))
            .put("other_qemu_processes_running", J::Arr(others.clone()));
        self.record.put("duplicate_check", d.build());
        if other {
            self.msg(Color::Bad, "REFUSED: another Abraham VM Launcher is already running. Only one VM is started at a time; nothing was started.");
            return self.refused(Outcome::Duplicate, "another launcher is running");
        }
        if !pinned.is_empty() {
            let list: Vec<String> = pinned.iter().filter_map(|j| j.as_str().map(String::from)).collect();
            self.msg(Color::Bad, &format!(
                "REFUSED: a QEMU from the pinned Abraham toolchain is already running ({}). It may be a test campaign, which must not be disturbed; nothing was started.",
                list.join("; ")
            ));
            return self.refused(Outcome::Duplicate, "a pinned QEMU is already running");
        }
        if !others.is_empty() {
            self.msg(Color::Warn, &format!("note: {} other QEMU process(es) are running (not the pinned toolchain); they are left alone", others.len()));
        }

        // 2. Earlier runs that never finished.
        let mut unsealed = Vec::new();
        if let Ok(rd) = fs::read_dir(&self.p.runs) {
            let mut v: Vec<PathBuf> = rd.flatten().map(|e| e.path()).filter(|p| p.is_dir() && *p != self.dir).collect();
            v.sort();
            for d in v {
                if !d.join("RUN_SHA256SUMS.json").exists() {
                    unsealed.push(d.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default());
                }
            }
        }
        for u in &unsealed {
            self.msg(Color::Warn, &format!("earlier run {u} was never sealed: its launcher was terminated before it finished (its folder is left as it was)"));
        }
        self.record.put("unsealed_earlier_runs", J::Arr(unsealed.iter().map(|s| J::s(s.clone())).collect()));

        // 3. Every required file, by digest. All are checked and all are reported.
        let k = self.kernel;
        self.msg(Color::Normal, &format!("selected: {} ({}), accelerator {}", k.menu, k.key, self.accel.to_uppercase()));
        let mut inputs = vec![
            check_input("kernel ELF", self.p.home.join(k.rel_path), k.sha256, true),
            check_input("QEMU executable", pinned_exe.clone(), pins::QEMU_EXE_SHA256, false),
            check_input("UEFI firmware code (edk2)", self.p.qemu_dir.join(pins::FW_CODE), pins::FW_CODE_SHA256, false),
            check_input("UEFI variable store template (edk2)", self.p.qemu_dir.join(pins::FW_VARS), pins::FW_VARS_SHA256, true),
            check_input("Limine 12.9.6 BOOTX64.EFI", self.p.home.join(pins::LIMINE_EFI), pins::LIMINE_EFI_SHA256, true),
            check_input("Limine boot-entry template limine.conf", self.p.home.join(pins::LIMINE_CONF), pins::LIMINE_CONF_SHA256, true),
        ];
        if let Some(b) = &inputs[0].bytes {
            if inputs[0].status == "OK" && !b.starts_with(b"\x7fELF") {
                inputs[0].status = "NOT AN ELF FILE";
            }
        }
        if let Some(b) = &inputs[5].bytes {
            let text = String::from_utf8_lossy(b);
            if inputs[5].status == "OK" && !text.contains(pins::LIMINE_CONF_PATH_LINE) {
                inputs[5].status = "TEMPLATE PLACEHOLDER MISSING";
            }
        }
        if !self.p.qemu_dir.is_dir() {
            self.msg(Color::Bad, &format!("QEMU folder not found: {}", self.p.qemu_dir.display()));
        }
        self.msg(Color::Normal, "required files (each must exist and match its pinned SHA-256):");
        for i in &inputs {
            let c = if i.status == "OK" { Color::Good } else { Color::Bad };
            let digest = i.actual.as_deref().map(|d| format!("{}...", &d[..16])).unwrap_or_else(|| "-".into());
            self.ui.msg(c, &format!("  {:<14} {:<40} sha256 {:<19} {}", i.status, i.name, digest, i.path.display()));
            if i.status == "DIGEST MISMATCH" {
                self.ui.msg(Color::Bad, &format!("                 expected {}", i.expected));
            }
        }
        let rows: Vec<J> = inputs
            .iter()
            .map(|i| {
                let mut o = Obj::new();
                o.put("name", J::s(i.name))
                    .put("path", J::s(i.path.display().to_string()))
                    .put("expected_sha256", J::s(i.expected))
                    .put("sha256", J::opt_s(i.actual.clone()))
                    .put("status", J::s(i.status));
                o.build()
            })
            .collect();
        self.record.put("inputs", J::Arr(rows));
        let mut sel = Obj::new();
        sel.put("key", J::s(k.key))
            .put("label", J::s(k.label))
            .put("build", J::s(format!("{:?}", k.build)))
            .put("expected_version", J::s(k.version))
            .put("path", J::s(self.p.home.join(k.rel_path).display().to_string()))
            .put("expected_sha256", J::s(k.sha256))
            .put("sha256", J::opt_s(inputs[0].actual.clone()));
        let missing = inputs.iter().any(|i| matches!(i.status, "MISSING" | "NOT A FILE" | "UNREADABLE"));
        let bad = inputs.iter().any(|i| i.status != "OK");
        if bad {
            self.record.put("selected_kernel", sel.build());
            let failing: Vec<String> =
                inputs.iter().filter(|i| i.status != "OK").map(|i| format!("{}: {}", i.name, i.status)).collect();
            let (o, why) = if missing {
                (Outcome::Missing, format!("a required file is missing or unreadable ({})", failing.join("; ")))
            } else {
                (Outcome::Integrity, format!("a required file is not the pinned one ({})", failing.join("; ")))
            };
            self.msg(Color::Bad, &format!("REFUSED: {why}. QEMU was not started. Nothing was changed outside this record folder."));
            return self.refused(o, &why);
        }
        let kernel_bytes = inputs[0].bytes.take().unwrap();
        let blake = hash::blake2b512_hex(&kernel_bytes);
        sel.put("blake2b512", J::s(blake.clone()));
        self.record.put("selected_kernel", sel.build());
        self.msg(Color::Good, &format!("kernel {} sha256 {} (pinned; verified)", k.label, k.sha256));

        // 4. QEMU's own version line.
        let version_line = Command::new(&pinned_exe)
            .arg("--version")
            .creation_flags(win::CREATE_NO_WINDOW)
            .stdin(Stdio::null())
            .stderr(Stdio::null())
            .output()
            .ok()
            .and_then(|o| String::from_utf8_lossy(&o.stdout).lines().next().map(|s| s.trim().to_string()))
            .unwrap_or_else(|| "UNAVAILABLE".into());
        let mut q = Obj::new();
        q.put("dir", J::s(self.p.qemu_dir.display().to_string()))
            .put("exe", J::s(pinned_exe.display().to_string()))
            .put("version_line", J::s(version_line.clone()))
            .put("version_line_is_the_pinned_one", J::Bool(version_line == pins::QEMU_VERSION_LINE));
        self.record.put("qemu", q.build());
        self.msg(Color::Normal, &format!("{version_line}"));

        // 5. The boot disk, staged exactly as the harness stages it.
        let staged = match self.stage(&kernel_bytes, &blake, &inputs) {
            Ok(s) => s,
            Err(e) => {
                self.msg(Color::Bad, &format!("STAGING FAILED: {e}. QEMU was not started."));
                return self.refused(Outcome::LauncherError, "staging failed");
            }
        };
        self.record.put("staged", staged);
        self.boot(keys)
    }

    fn stage(&mut self, kernel: &[u8], blake: &str, inputs: &[Input]) -> Result<J, String> {
        let esp = self.dir.join("esp");
        fs::create_dir_all(esp.join(r"EFI\BOOT")).map_err(|e| e.to_string())?;
        fs::create_dir_all(esp.join(r"boot\limine")).map_err(|e| e.to_string())?;
        fs::write(esp.join(r"EFI\BOOT\BOOTX64.EFI"), inputs[4].bytes.as_ref().unwrap()).map_err(|e| e.to_string())?;
        fs::write(esp.join(r"boot\abraham-kernel"), kernel).map_err(|e| e.to_string())?;
        let template = String::from_utf8_lossy(inputs[5].bytes.as_ref().unwrap()).replace("\r\n", "\n");
        let conf = template.replace(pins::LIMINE_CONF_PLACEHOLDER, blake);
        fs::write(esp.join(r"boot\limine\limine.conf"), conf.as_bytes()).map_err(|e| e.to_string())?;
        fs::write(self.dir.join("vars.fd"), inputs[3].bytes.as_ref().unwrap()).map_err(|e| e.to_string())?;
        // Read back what is now on disk: these are the bytes QEMU will boot.
        let k = hash::sha256_file(&esp.join(r"boot\abraham-kernel")).map_err(|e| e.to_string())?;
        let e = hash::sha256_file(&esp.join(r"EFI\BOOT\BOOTX64.EFI")).map_err(|e| e.to_string())?;
        let c = hash::sha256_file(&esp.join(r"boot\limine\limine.conf")).map_err(|e| e.to_string())?;
        let v = hash::sha256_file(&self.dir.join("vars.fd")).map_err(|e| e.to_string())?;
        if k != self.kernel.sha256 || e != pins::LIMINE_EFI_SHA256 || v != pins::FW_VARS_SHA256 {
            return Err("a staged file does not read back with its pinned digest".into());
        }
        self.msg(Color::Normal, "boot disk staged: EFI/BOOT/BOOTX64.EFI, boot/abraham-kernel, boot/limine/limine.conf (BLAKE2b pin), vars.fd; read back and verified");
        let mut o = Obj::new();
        o.put("esp/boot/abraham-kernel", J::s(k))
            .put("esp/EFI/BOOT/BOOTX64.EFI", J::s(e))
            .put("esp/boot/limine/limine.conf", J::s(c))
            .put("vars.fd", J::s(v))
            .put("kernel_blake2b_in_config", J::s(blake));
        Ok(o.build())
    }

    fn qemu_args(&self, port: u16) -> Vec<String> {
        let fw = self.p.qemu_dir.join(pins::FW_CODE);
        let cpu = if self.accel == "whpx" { "host" } else { "max" };
        vec![
            "-machine".into(), "q35".into(), "-accel".into(), self.accel.clone(), "-cpu".into(), cpu.into(),
            "-smp".into(), "1".into(), "-m".into(), "256".into(), "-display".into(), "none".into(),
            "-nodefaults".into(), "-nic".into(), "none".into(),
            "-serial".into(), format!("file:{}", self.dir.join("serial.log").display()),
            "-qmp".into(), format!("tcp:127.0.0.1:{port},server=on,wait=off"),
            "-drive".into(), format!("if=pflash,format=raw,readonly=on,file={}", fw.display()),
            "-drive".into(), format!("if=pflash,format=raw,file={}", self.dir.join("vars.fd").display()),
            "-drive".into(), format!("file=fat:ro:{},format=raw,if=virtio,readonly=on", self.dir.join("esp").display()),
            "-S".into(),
        ]
    }

    fn spawn(&mut self, port: u16) -> Result<(Child, win::Owned), String> {
        let exe = self.p.qemu_dir.join(pins::QEMU_EXE);
        let qargs = self.qemu_args(port);
        let mut cmd_line = vec![J::s(exe.display().to_string())];
        cmd_line.extend(qargs.iter().map(|a| J::s(a.clone())));
        self.record.put("qemu_command", J::Arr(cmd_line));
        let out = File::create(self.dir.join("qemu-stdout.txt")).map_err(|e| e.to_string())?;
        let err = File::create(self.dir.join("qemu-stderr.txt")).map_err(|e| e.to_string())?;
        let job = win::kill_on_close_job()?;
        let child = Command::new(&exe)
            .args(&qargs)
            .stdin(Stdio::null())
            .stdout(Stdio::from(out))
            .stderr(Stdio::from(err))
            .creation_flags(win::CREATE_SUSPENDED | win::CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("QEMU could not be started: {e}"))?;
        let mut child = child;
        let h = child.as_raw_handle() as win::HANDLE;
        if let Err(e) = win::job_assign(&job, h) {
            let _ = child.kill();
            return Err(e);
        }
        VM_RUNNING.store(true, Ordering::SeqCst);
        let (ok, error) = win::opt_out_timer_throttling(h);
        let readback = match win::read_timer_throttling(h) {
            Ok((c, s)) => {
                let mut o = Obj::new();
                o.put("control_mask", J::n(c)).put("state_mask", J::n(s));
                o.build()
            }
            Err(e) => J::s(format!("not readable (error {e})")),
        };
        let mut o = Obj::new();
        o.put("ok", J::Bool(ok))
            .put("error", error.map(J::n).unwrap_or(J::Null))
            .put("control_mask", J::n(4))
            .put("state_mask", J::n(0))
            .put("readback", readback);
        self.record.put("timer_throttling_opt_out", o.build());
        let threads = win::resume_process(child.id());
        let mut pr = Obj::new();
        pr.put("qemu_pid", J::n(child.id()))
            .put("created_suspended", J::Bool(true))
            .put("console", J::s("none (CREATE_NO_WINDOW): console events reach the launcher only"))
            .put("job_kill_on_close", J::Bool(true))
            .put("threads_resumed", match &threads { Ok(n) => J::n(*n), Err(e) => J::s(e.clone()) });
        self.record.put("process", pr.build());
        if let Err(e) = threads {
            let _ = win::job_terminate(&job, 1);
            return Err(e);
        }
        self.rec.mark("qemu started (suspended, in the kill-on-close job, timer opt-out applied, then resumed)");
        let mut live = Obj::new();
        live.put("run_id", J::s(self.run_id.clone()))
            .put("launcher_pid", J::n(win::current_pid()))
            .put("qemu_pid", J::n(child.id()))
            .put("started_utc", J::s(util::utc()));
        let _ = fs::write(self.dir.join("live.json"), live.build().pretty());
        if !ok {
            self.msg(Color::Warn, &format!("the timer-resolution opt-out failed (error {:?}): timed results of this run do not qualify", error));
        }
        Ok((child, job))
    }

    fn boot(&mut self, keys: &Receiver<u8>) -> Outcome {
        let port = match free_port() {
            Ok(p) => p,
            Err(e) => {
                self.msg(Color::Bad, &e);
                return self.refused(Outcome::LauncherError, "no local port");
            }
        };
        let (mut child, job) = match self.spawn(port) {
            Ok(x) => x,
            Err(e) => {
                VM_RUNNING.store(false, Ordering::SeqCst);
                self.msg(Color::Bad, &format!("QEMU START FAILED: {e}"));
                return self.refused(Outcome::LauncherError, "QEMU could not be started");
            }
        };
        let pid = child.id();
        self.msg(Color::Normal, &format!("QEMU 11.1.0 started, pid {pid}, {} (paused at start; opt-out applied first)", self.accel.to_uppercase()));
        let mut alive = || matches!(child.try_wait(), Ok(None));
        let connected = qmp::Qmp::connect(port, &self.dir.join("qmp.jsonl"), self.rec.t0, Duration::from_secs(30), &mut alive);
        let mut qmp = match connected {
            Ok(q) => {
                self.rec.mark("qmp connected");
                Some(q)
            }
            Err(e) => {
                self.msg(Color::Bad, &format!("QMP: {e}"));
                None
            }
        };
        let mut cont_ok = false;
        if let Some(q) = qmp.as_mut() {
            match q.command("cont", None, Duration::from_secs(10)) {
                Ok(_) => {
                    self.rec.mark("cont sent (after timer opt-out)");
                    cont_ok = true;
                }
                Err(e) => self.msg(Color::Bad, &format!("QMP cont: {e}")),
            }
        }
        let t_cont = Instant::now();
        let mut obs = Observer::new(self.kernel.build, self.kernel.version);
        self.ui.start_panel(PANEL_HEIGHT);
        if cont_ok {
            self.msg(Color::Normal, &format!("VM resumed. Serial console of {} follows. [Q] shuts the VM down.", self.kernel.label));
        } else {
            self.msg(Color::Bad, "the VM was NOT resumed: QEMU's control channel did not answer");
        }

        let serial_path = self.dir.join("serial.log");
        let mut serial: Option<File> = None;
        let mut asm = observe::LineAssembler::default();
        let mut show_ticks = true;
        let mut stop_at: Option<Instant> = None;
        let mut stop_why: Option<String> = None;
        let mut announced_op = false;
        let mut announced_fail = false;
        let mut exited: Option<i32> = None;
        let mut last_panel = Instant::now() - Duration::from_secs(1);
        let mut rows_shown = 0usize;
        let mut events_seen = 0usize;
        if !cont_ok {
            stop_why = Some("the VM could not be resumed through QMP".into());
        }

        let mut prev_i = Instant::now();
        let mut prev_w = std::time::SystemTime::now();
        loop {
            // 0.33.2 (3A): the launcher's own stops are host evidence. When Windows suspends programs (a standby), the
            // launcher stops too, and its loop sees the time jump; when only QEMU is stopped, or the guest stalls, the
            // launcher keeps running. Wall time is used as well as the monotonic clock, which may not count a sleep.
            let now_i = Instant::now();
            let now_w = std::time::SystemTime::now();
            let d = now_i.duration_since(prev_i).as_secs_f64().max(now_w.duration_since(prev_w).map(|x| x.as_secs_f64()).unwrap_or(0.0));
            if d > 2.0 {
                self.stalls.push((t_cont.elapsed().as_secs_f64(), d));
                self.msg(Color::Warn, &format!("the launcher itself was not running for {d:.1} s (the host suspended or stopped it)"));
            }
            prev_i = now_i;
            prev_w = now_w;
            // Serial output.
            if serial.is_none() && serial_path.exists() {
                serial = File::open(&serial_path).ok();
            }
            let mut fresh = Vec::new();
            if let Some(f) = serial.as_mut() {
                let mut buf = Vec::new();
                let _ = f.read_to_end(&mut buf);
                if !buf.is_empty() {
                    fresh = asm.push(&buf);
                }
            }
            let t = t_cont.elapsed().as_secs_f64();
            for l in fresh {
                obs.feed(&l, t);
                self.show(&l, show_ticks);
                while rows_shown < obs.rows.len() {
                    let e = Observer::explain(&obs.rows[rows_shown]);
                    self.ui.line(if obs.rows[rows_shown].state == "REFUSED" { Color::Warn } else { Color::Good }, &format!("      {e}"));
                    rows_shown += 1;
                }
                self.judge_new_gaps(&obs, t);
            }
            // QMP events.
            if let Some(q) = &qmp {
                let ev = q.events();
                for e in ev.iter().skip(events_seen) {
                    let name = e.get("event").and_then(J::as_str).unwrap_or("?").to_string();
                    if matches!(name.as_str(), "SHUTDOWN" | "RESET" | "GUEST_PANICKED" | "STOP") && stop_why.is_none() {
                        self.msg(Color::Warn, &format!("QMP event {name}: {}", e.get("data").map(|d| d.compact()).unwrap_or_default()));
                    }
                }
                events_seen = ev.len();
            }
            // Keys and console events.
            while let Ok(c) = keys.try_recv() {
                match c {
                    b'q' | b'Q' if stop_why.is_none() => stop_why = Some("the operator pressed Q".into()),
                    b'l' | b'L' => {
                        let _ = Command::new("explorer.exe").arg(&self.dir).spawn();
                    }
                    b'h' | b'H' => {
                        show_ticks = !show_ticks;
                        self.msg(Color::Dim, if show_ticks { "heartbeat lines shown" } else { "heartbeat lines hidden (still recorded)" });
                    }
                    _ => {}
                }
            }
            let ev = STOP_EVENT.load(Ordering::SeqCst);
            if ev != 0 && stop_why.is_none() {
                stop_why = Some(stop_reason(ev).into());
            }
            // QEMU itself.
            if let Ok(Some(status)) = child.try_wait() {
                exited = Some(status.code().unwrap_or(-1));
                break;
            }
            // Boot progress.
            let b = obs.boot(t, self.args.boot_timeout, false);
            if b == Boot::Operational && !announced_op {
                announced_op = true;
                self.rec.mark(format!("operational={} after {:.3} s", true, obs.operational_at.unwrap_or(t)));
                self.msg(Color::Good, &format!("Abraham reached OPERATIONAL {:.1} s after the VM was resumed.", obs.operational_at.unwrap_or(t)));
                if let Some(s) = self.args.auto_stop_after {
                    stop_at = Some(Instant::now() + Duration::from_secs_f64(s));
                }
            }
            if let Boot::Failed(why) = &b {
                if !announced_fail {
                    announced_fail = true;
                    let designed = self.kernel.build == Build::EarlyFail && obs.early_fail_as_designed();
                    self.rec.mark(format!("boot failed: {why}"));
                    self.msg(Color::Bad, &format!("KERNEL BOOT FAILED: {why}{}", if designed { " - the designed outcome of this DIAGNOSTIC build" } else { "" }));
                    if let Some(s) = self.args.auto_stop_after {
                        stop_at = Some(Instant::now() + Duration::from_secs_f64(s));
                    } else {
                        self.msg(Color::Normal, "the VM is left as it is so you can read the output; press Q to shut it down");
                    }
                }
            }
            if let Some(at) = stop_at {
                if Instant::now() >= at && stop_why.is_none() {
                    stop_why = Some(format!("automatic stop (--auto-stop-after {})", self.args.auto_stop_after.unwrap_or(0.0)));
                }
            }
            if last_panel.elapsed() >= Duration::from_millis(250) {
                let rows = self.panel(&obs, t, pid, false, None);
                self.ui.panel(&rows);
                last_panel = Instant::now();
            }
            if stop_why.is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        // Shutdown.
        let mut sh = Obj::new();
        let mut clean = false;
        let mut forced = false;
        let unexpected = exited.is_some();
        let requested_by = stop_why.clone();
        let mut status_before_quit = J::Null;
        let mut registers = J::Null;
        if let Some(code) = exited {
            self.rec.mark(format!("qemu exited by itself, code {code}"));
            self.msg(Color::Bad, &format!("QEMU TERMINATED UNEXPECTEDLY (exit code {code}); the launcher did not ask it to stop."));
        } else {
            let why = stop_why.clone().unwrap_or_default();
            self.rec.mark(format!("shutdown requested: {why}"));
            self.msg(Color::Normal, &format!("shutting the VM down ({why}): QMP quit"));
            let names = win::processes();
            let in_job: Vec<J> = win::job_pids(&job)
                .iter()
                .map(|p| J::s(format!("pid {p} {}", names.iter().find(|q| q.pid == *p).map(|q| q.exe_name.clone()).unwrap_or_default())))
                .collect();
            sh.put("job_processes_before_quit", J::Arr(in_job));
            if let Some(q) = qmp.as_mut() {
                match q.command("query-status", None, Duration::from_secs(5)) {
                    Ok(r) => status_before_quit = r.get("return").cloned().unwrap_or(J::Null),
                    Err(e) => self.msg(Color::Warn, &format!("query-status: {e}")),
                }
                // As the harness records `registers_boot1` (and the fault probe reads RIP/HLT from it).
                let arg = J::Obj(vec![("command-line".to_string(), J::s("info registers"))]);
                if let Ok(r) = q.command("human-monitor-command", Some(arg), Duration::from_secs(5)) {
                    registers = r.get("return").cloned().unwrap_or(J::Null);
                }
                match q.command("quit", None, Duration::from_secs(5)) {
                    Ok(_) => self.rec.mark("quit sent"),
                    Err(e) => {
                        self.rec.mark(format!("quit failed: {e}"));
                        self.msg(Color::Warn, &format!("QMP quit: {e}"));
                    }
                }
            }
            let deadline = Instant::now() + Duration::from_secs(10);
            loop {
                if let Ok(Some(st)) = child.try_wait() {
                    exited = Some(st.code().unwrap_or(-1));
                    break;
                }
                if Instant::now() > deadline {
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            if exited.is_none() {
                forced = true;
                self.rec.mark("qemu did not exit within 10 s of quit: job terminated");
                self.msg(Color::Bad, "QEMU did not stop within 10 s: terminating it (forced)");
                win::job_terminate(&job, 1);
                exited = child.wait().ok().map(|s| s.code().unwrap_or(-1));
            }
            self.rec.mark(format!("qemu exited {}", exited.map(|c| c.to_string()).unwrap_or_else(|| "?".into())));
        }
        let events = qmp.as_ref().map(|q| q.events()).unwrap_or_default();
        let shutdown_reason = events
            .iter()
            .filter(|e| e.get("event").and_then(J::as_str) == Some("SHUTDOWN"))
            .filter_map(|e| e.get("data").and_then(|d| d.get("reason")).and_then(J::as_str).map(String::from))
            .last();
        if !unexpected && !forced && exited == Some(0) && shutdown_reason.as_deref() == Some("host-qmp-quit") {
            clean = true;
        }
        drop(qmp);
        std::thread::sleep(Duration::from_millis(200));
        let counts = win::job_counts(&job);
        let pinned_exe = self.p.qemu_dir.join(pins::QEMU_EXE);
        let left: Vec<J> = win::processes()
            .iter()
            .filter(|q| q.image.as_deref().map(|i| same_path(i, &pinned_exe)).unwrap_or(false))
            .map(|q| J::s(format!("pid {}", q.pid)))
            .collect();
        let mode = if unexpected {
            "QEMU_EXITED_UNEXPECTEDLY"
        } else if forced {
            "FORCED_TERMINATION"
        } else if clean {
            "CLEAN_QMP_QUIT"
        } else {
            "QUIT_NOT_CONFIRMED"
        };
        sh.put("requested_by", J::opt_s(requested_by.clone()))
            .put("mode", J::s(mode))
            .put("qemu_exit_code", exited.map(J::n).unwrap_or(J::Null))
            .put("shutdown_event_reason", J::opt_s(shutdown_reason.clone()))
            .put("job_active_processes_after", counts.map(|c| J::n(c.0)).unwrap_or(J::Null))
            .put("job_total_processes", counts.map(|c| J::n(c.1)).unwrap_or(J::Null))
            .put("pinned_qemu_processes_after", J::Arr(left.clone()));
        drop(job);

        // The rest of the console.
        if let Some(f) = serial.as_mut() {
            let mut buf = Vec::new();
            let _ = f.seek(SeekFrom::Current(0));
            let _ = f.read_to_end(&mut buf);
            let t = t_cont.elapsed().as_secs_f64();
            for l in asm.push(&buf) {
                obs.feed(&l, t);
                self.show(&l, show_ticks);
            }
        }
        drop(serial);
        let cut = asm.flush();
        if let Some(c) = &cut {
            if !c.is_empty() {
                self.ui.line(Color::Dim, &format!("{}   <- cut by the shutdown", observe::printable(c)));
            }
        }
        obs.end_of_capture(cut);
        let t_last = t_cont.elapsed().as_secs_f64();
        self.judge_new_gaps(&obs, t_last);
        let t_end = t_cont.elapsed().as_secs_f64();
        let heartbeat_alive = obs.last_tick_at.map(|lt| t_end - lt < 5.0).unwrap_or(false);
        let rows = self.panel(&obs, t_end, pid, true, Some(mode));
        self.ui.panel(&rows);
        self.ui.end_panel();

        // Verdicts.
        let boot_state = obs.boot(t_end, self.args.boot_timeout, true);
        let boot_checks = obs.boot_checks(heartbeat_alive);
        let svc_checks = obs.service_checks();
        let boot_failed = matches!(boot_state, Boot::Failed(_));
        let contract = obs.contract(true, boot_failed);
        let designed_failure = self.kernel.build == Build::EarlyFail && obs.early_fail_as_designed();
        let boot_pass = boot_checks.iter().all(|c| c.1);
        let (boot_word, boot_text) = match (&boot_state, self.kernel.build) {
            (Boot::Failed(w), Build::EarlyFail) if designed_failure => ("FAILED AS DESIGNED", format!("{w}; this DIAGNOSTIC build exists to show a failed boot")),
            (Boot::Failed(w), _) => ("FAILED", w.clone()),
            (Boot::Operational, Build::EarlyFail) => ("UNEXPECTED", "the early-fail build reached OPERATIONAL".to_string()),
            (Boot::Operational, _) if boot_pass => (
                "PASS",
                format!(
                    "reached OPERATIONAL {:.1} s after the VM was resumed; banner {}; {} heartbeats, {}; no fault; no reset",
                    obs.operational_at.unwrap_or(0.0),
                    obs.banner_version.clone().unwrap_or_default(),
                    obs.ticks,
                    match obs.clock_summary() {
                        Some(c) => format!("continuous except as the kernel reported: {c}"),
                        None => "continuous".to_string(),
                    }
                ),
            ),
            (Boot::Operational, _) => (
                "OPERATIONAL WITH PROBLEMS",
                format!("reached OPERATIONAL, but: {}", boot_checks.iter().filter(|c| !c.1).map(|c| c.0).collect::<Vec<_>>().join(", ")),
            ),
            (other, _) => ("NOT OPERATIONAL", format!("{other:?}")),
        };
        let svc_ok = svc_checks.iter().all(|c| c.1);
        let shutdown_word = if clean { "CLEAN" } else if forced { "FORCED" } else if unexpected { "UNEXPECTED" } else { "NOT CONFIRMED" };
        let no_left = left.is_empty() && counts.map(|c| c.0 == 0).unwrap_or(false);
        let outcome = if unexpected {
            Outcome::VmTerminated
        } else if boot_failed || (self.kernel.build != Build::EarlyFail && !boot_pass) || boot_word == "UNEXPECTED" {
            Outcome::BootFailed
        } else if matches!(contract, Verdict::Inconsistent(_)) {
            Outcome::ContractInconsistent
        } else if !svc_ok {
            Outcome::ServicesNotAsDesigned
        } else if !clean || !no_left {
            Outcome::ShutdownNotClean
        } else if !self.clock_explained(&obs) {
            Outcome::ClockCauseNotEstablished
        } else {
            Outcome::Ok
        };

        let checks_obj = |v: &[(&'static str, bool)]| J::Obj(v.iter().map(|(k, b)| (k.to_string(), J::Bool(*b))).collect());
        let mut ob = Obj::new();
        ob.put("serial_lines", J::n(obs.lines))
            .put("firmware_boot_line", J::opt_s(obs.firmware_boot.clone()))
            .put("kernel_entries", J::n(obs.entries))
            .put("loader", J::opt_s(obs.loader.as_ref().map(|l| format!("{} base_revision_supported={}", l.0, l.1))))
            .put("banner_version", J::opt_s(obs.banner_version.clone()))
            .put("boot_epoch", J::opt_s(obs.banner_epoch.clone()))
            .put("operational_after_s", obs.operational_at.map(J::f3).unwrap_or(J::Null))
            .put("heartbeats", J::n(obs.ticks))
            .put("last_uptime_s", obs.last_uptime.map(J::n).unwrap_or(J::Null))
            .put("faults", J::Arr(obs.faults.iter().map(|s| J::s(s.clone())).collect()))
            .put("status_rounds", J::n(obs.rounds))
            .put("appinfo_groups_consistent", J::n(obs.appinfo_groups))
            .put("launch_results", J::n(obs.rows.len()))
            .put("launchpad_summary", J::opt_s(obs.summary.clone()))
            .put("service_problems", J::Arr(obs.counted_service_problems().into_iter().map(J::s).collect()))
            .put("contract_problems", J::Arr(obs.contract_problems.iter().map(|s| J::s(s.clone())).collect()))
            .put("execution_claims", J::Arr(obs.claims.iter().map(|s| J::s(s.clone())).collect()))
            .put("cut_line", J::opt_s(obs.cut_line.clone()))
            .put("cut_group", J::opt_s(obs.cut_group.clone()))
            .put("clock_anomalies_reported_by_the_kernel", J::Arr(obs.clock_anomalies.iter().map(|s| J::s(s.clone())).collect()))
            .put("clock_degraded", J::opt_s(obs.clock_degraded.clone()))
            .put(
                "clock_gaps_reported_by_the_kernel",
                J::Arr(
                    obs.clock_gaps
                        .iter()
                        .enumerate()
                        .map(|(i, (a, b, n))| {
                            let ev = self.gap_evidence.get(i).copied().flatten();
                            let mut o = Obj::new();
                            o.put("from_s", J::n(a))
                                .put("to_s", J::n(b))
                                .put("skipped_s", J::n(n))
                                .put("launcher_stopped_s", ev.map(J::f3).unwrap_or(J::Null))
                                .put("cause", J::s(if ev.is_some() { "HOST_SUSPENSION (the launcher was stopped too)" } else { "NOT_ESTABLISHED" }));
                            o.build()
                        })
                        .collect(),
                ),
            )
            .put(
                "launcher_stalls",
                J::Arr(self.stalls.iter().map(|(e, l)| {
                    let mut o = Obj::new();
                    o.put("ended_s", J::f3(*e)).put("length_s", J::f3(*l));
                    o.build()
                }).collect()),
            )
            .put("c12_pair_findings_not_counted_after_degradation",
                 J::Arr(if obs.clock_degraded.is_some() { obs.c12_pair_problems.iter().map(|s| J::s(s.clone())).collect() } else { vec![] }))
            .put(
                "unexplained_heartbeat_gaps",
                J::Arr(obs.unexplained_gaps.iter().map(|(a, b)| J::s(format!("{a} -> {b}"))).collect()),
            )
            .put("clock_summary", J::opt_s(obs.clock_summary()));
        let mut ch = Obj::new();
        ch.put("kernel_boot", checks_obj(&boot_checks)).put("services", checks_obj(&svc_checks));
        let mut vd = Obj::new();
        vd.put("kernel_boot", J::s(boot_word))
            .put("kernel_boot_detail", J::s(boot_text.clone()))
            .put("services", J::s(if self.kernel.build == Build::EarlyFail { "NOT REACHED" } else if svc_ok { "AS DESIGNED" } else { "PROBLEMS" }))
            .put("launcher_contract", J::s(contract.word()))
            .put("launcher_contract_detail", J::s(contract.text()))
            .put("vm_shutdown", J::s(shutdown_word))
            .put(
                "clock",
                J::s(if obs.clock_anomalies.is_empty() {
                    "OK"
                } else if self.clock_explained(&obs) {
                    "DEGRADED: every clock gap corroborated by host evidence of a suspension"
                } else {
                    "DEGRADED: cause not established by host evidence"
                }),
            )
            .put("live_checks_are", J::s("LIVE CHECKS of the launcher (a subset of the official rules), not the official C0-C13 judgment"));
        self.rec.mark("records written");
        self.record
            .put("timeline", J::Arr(self.rec.timeline.iter().map(|(t, w)| {
                let mut o = Obj::new();
                o.put("t", J::f3(*t)).put("what", J::s(w.clone()));
                o.build()
            }).collect()))
            .put("qmp_events", J::Arr(events))
            .put("status_before_quit", status_before_quit)
            .put("registers_before_quit", registers)
            .put("shutdown", sh.build())
            .put("observation", ob.build())
            .put("checks", ch.build())
            .put("verdicts", vd.build());

        // Summary.
        let short_sha = format!("{}...{}", &self.kernel.sha256[..8], &self.kernel.sha256[56..]);
        let mut summary = vec![
            (Color::Title, "==================== ABRAHAM VM LAUNCHER: RESULT ====================".to_string()),
            (Color::Normal, format!("Run               : {}   ({})", self.run_id, self.dir.display())),
            (Color::Normal, format!("Kernel            : {} {}, sha256 {} (pinned; verified before boot and after staging)", self.kernel.label, self.kernel.version, short_sha)),
            (Color::Normal, format!("Machine           : QEMU 11.1.0 {}, q35, 1 vCPU, 256 MiB; edk2 UEFI; Limine 12.9.6", self.accel.to_uppercase())),
            (if boot_word == "PASS" || boot_word == "FAILED AS DESIGNED" { Color::Good } else { Color::Bad }, format!("KERNEL BOOT       : {boot_word} - {boot_text}")),
        ];
        if self.kernel.build != Build::EarlyFail {
            let latest = obs.latest.as_ref().map(|r| {
                r.iter().map(|s| format!("{} {}/{}{}", s.id, s.state, s.status, if s.reason != "NONE" { format!(" {}", s.reason) } else { String::new() })).collect::<Vec<_>>().join("; ")
            });
            let stale_note = if obs.clock_degraded.is_some() && svc_ok {
                "; svc.counter AVAILABLE while the clock was OK, UNKNOWN/OBSERVATION_STALE once it was DEGRADED (stale data is never trusted)"
            } else {
                ""
            };
            summary.push((if svc_ok { Color::Good } else { Color::Bad }, format!(
                "SERVICES          : {} - {} status rounds{stale_note}; last: {}",
                if svc_ok { "AS DESIGNED" } else { "PROBLEMS" },
                obs.rounds,
                latest.unwrap_or_else(|| "none".into())
            )));
            for p in obs.counted_service_problems().iter().take(3) {
                summary.push((Color::Bad, format!("                    {p}")));
            }
        }
        summary.push((
            match contract { Verdict::Consistent(_) => Color::Good, Verdict::NotReached(_) => Color::Warn, _ => Color::Bad },
            format!("LAUNCHER CONTRACT : {} - {}", contract.word(), contract.text()),
        ));
        for p in obs.contract_problems.iter().skip(1).take(3) {
            summary.push((Color::Bad, format!("                    also: {p}")));
        }
        summary.push((
            if clean && no_left { Color::Good } else { Color::Bad },
            format!(
                "VM SHUTDOWN       : {shutdown_word} - {}; QEMU exit code {}; QEMU processes left: {}",
                match mode {
                    "CLEAN_QMP_QUIT" => "QMP quit, as the harness does (Abraham has no shutdown path of its own)".to_string(),
                    "QEMU_EXITED_UNEXPECTEDLY" => "QEMU stopped without being asked".to_string(),
                    "FORCED_TERMINATION" => "QEMU did not stop after QMP quit and was terminated".to_string(),
                    _ => "the QMP shutdown was not confirmed".to_string(),
                },
                exited.map(|c| c.to_string()).unwrap_or_else(|| "?".into()),
                if no_left { "none".to_string() } else { format!("{} ({:?})", left.len(), counts) }
            ),
        ));
        if let Some(c) = self.clock_text(&obs) {
            summary.push((Color::Warn, format!("CLOCK             : {c}")));
        }
        summary.push((Color::Normal, format!("RESULT            : {} (exit code {})", outcome.name(), outcome as i32)));
        summary.push((Color::Dim, "Not claimed       : the official C0-C13 judgment (tools/abr_boot_001.py); a graphical desktop; running Windows programs inside Abraham; any execution inside Abraham (0.33 executes nothing)".to_string()));
        for (c, s) in &summary {
            self.ui.line(*c, s);
        }
        let text: Vec<String> = summary.iter().map(|(_, s)| s.clone()).collect();
        let _ = fs::write(self.dir.join("verdict.txt"), text.join("\r\n") + "\r\n");
        self.finish(outcome)
    }

    /// 0.33.2 (3A): a kernel-reported gap is a host suspension only when the launcher itself was stopped for at least
    /// half its length, ending within the 30 s before the gap arrived. Otherwise its cause is not established.
    fn judge_new_gaps(&mut self, obs: &Observer, t: f64) {
        while self.gap_evidence.len() < obs.clock_gaps.len() {
            let (a, b, n) = obs.clock_gaps[self.gap_evidence.len()];
            let stop = self
                .stalls
                .iter()
                .filter(|(end, len)| *end >= t - 30.0 && *end <= t + 1.0 && *len >= 0.5 * n as f64)
                .map(|(_, len)| *len)
                .fold(None, |m: Option<f64>, x| Some(m.map_or(x, |y: f64| y.max(x))));
            self.gap_evidence.push(stop);
            match stop {
                Some(len) => self.msg(Color::Warn, &format!(
                    "the kernel reported a clock gap (heartbeat {a} -> {b}, {n} s skipped); host evidence: the launcher itself was stopped for {len:.1} s at the same time, so the host suspended programs"
                )),
                None => self.msg(Color::Warn, &format!(
                    "the kernel reported a clock gap (heartbeat {a} -> {b}, {n} s skipped); no host evidence: the launcher kept running, so the cause is not established (a host-side stop of QEMU alone and a guest-side stall look the same from inside)"
                )),
            }
        }
    }

    fn clock_text(&self, o: &Observer) -> Option<String> {
        let reason = o.clock_degraded.as_ref()?;
        let gaps: Vec<String> = o
            .clock_gaps
            .iter()
            .enumerate()
            .map(|(i, (a, b, n))| match self.gap_evidence.get(i).copied().flatten() {
                Some(len) => format!("heartbeat {a} -> {b}, {n} s skipped: host suspension (the launcher was stopped {len:.0} s too)"),
                None => format!("heartbeat {a} -> {b}, {n} s skipped: cause not established (the launcher kept running)"),
            })
            .collect();
        Some(if gaps.is_empty() {
            format!("DEGRADED ({reason}), reported by the kernel; cause not established; observations since then are stale, by design")
        } else {
            format!("DEGRADED ({reason}) | clock gap reported by the kernel: {} | stale data is never trusted", gaps.join("; "))
        })
    }

    /// The panel's CLOCK row: the latest gap's cause first, then the gap, short enough for 120 columns (the row is
    /// 12 columns of label plus this); extras are added only while they fit. The result block uses `clock_text`.
    fn clock_panel_text(&self, o: &Observer) -> Option<String> {
        const ROOM: usize = 120 - 12;
        let reason = o.clock_degraded.as_ref()?;
        let Some(&(a, b, n)) = o.clock_gaps.last() else {
            return Some(format!("DEGRADED ({reason}), reported by the kernel; cause not established; stale data is never trusted"));
        };
        let cause = match self.gap_evidence.get(o.clock_gaps.len() - 1).copied().flatten() {
            Some(len) => format!("host suspension (launcher stopped {len:.0} s)"),
            None => "cause not established".to_string(),
        };
        let mut t = format!("DEGRADED: {cause} | gap reported by the kernel, {a} -> {b} s ({n} s)");
        if o.clock_gaps.len() > 1 && t.len() + 12 <= ROOM {
            t.push_str(&format!(" (+{} earlier)", o.clock_gaps.len() - 1));
        }
        if t.len() + 27 <= ROOM {
            t.push_str(" | stale data never trusted");
        }
        Some(t)
    }

    /// Every clock anomaly is a forward jump with its gap, and every gap has host evidence of a suspension.
    fn clock_explained(&self, o: &Observer) -> bool {
        o.clock_anomalies.is_empty()
            || (!o.clock_gaps.is_empty()
                && self.gap_evidence.len() == o.clock_gaps.len()
                && self.gap_evidence.iter().all(|e| e.is_some())
                && o.clock_anomalies.iter().all(|l| l.contains("anomaly=TSC_FORWARD_JUMP|") || l.contains("anomaly=HEARTBEAT_GAP|")))
    }

    fn show(&mut self, l: &str, show_ticks: bool) {
        if l.is_empty() {
            return;
        }
        let c = if l.starts_with("ABR|FAULT") || (l.starts_with("ABR|INIT|") && l.contains("to=FAILED")) {
            Color::Bad
        } else if l == observe::OPERATIONAL || l.starts_with("ABRAHAM |") {
            Color::Good
        } else if l.starts_with("ABR|TICK|") {
            if !show_ticks {
                self.ui.record_only(l);
                return;
            }
            Color::Dim
        } else if l.starts_with("ABR|SVC") {
            Color::Info
        } else if l.starts_with("ABR|APP") {
            Color::App
        } else if l.starts_with("ABR|LAUNCH") || l.starts_with("ABR|DIAG|") {
            Color::Launch
        } else if l.starts_with("ABR|") {
            Color::Normal
        } else {
            Color::Dim
        };
        self.ui.line(c, &observe::printable(l));
    }

    fn panel(&self, o: &Observer, t: f64, pid: u32, done: bool, mode: Option<&str>) -> Vec<PanelRow> {
        let k = self.kernel;
        let mut rows = Vec::new();
        rows.push(PanelRow {
            color: Color::Title,
            text: format!(
                " ABRAHAM VM LAUNCHER {VERSION} | {} | {} {} | QEMU 11.1.0 {} | host utility",
                self.run_id, k.label, k.version, self.accel.to_uppercase()
            ),
            stable: String::new(),
        });
        // 0.33.1 (dry run DRY-P005): once the clock is DEGRADED, this row states it; at 120 columns the boot row has
        // room only for a short marker. The kernel digest stays in the title, the result and the record.
        // 0.33.2 (dry run 1, P005): the row uses the compact form, so the cause is never cut off at 120 columns; the
        // result block and the record keep the full text.
        if let Some(what) = self.clock_panel_text(o) {
            rows.push(PanelRow { color: Color::Warn, text: format!(" CLOCK    : {what}"), stable: String::new() });
        } else {
            rows.push(PanelRow {
                color: Color::Normal,
                text: format!(" KERNEL   : sha256 {}...{} VERIFIED (pinned) | QEMU pid {pid}, timer opt-out applied, kill-on-close job", &k.sha256[..12], &k.sha256[56..]),
                stable: String::new(),
            });
        }
        let b = o.boot(t, self.args.boot_timeout, done);
        let late = o.last_tick_at.map(|lt| t - lt).unwrap_or(0.0);
        let (bc, bt, bs) = match &b {
            Boot::WaitingForFirmware => (Color::Warn, format!("waiting for the UEFI firmware ({t:.0} s)"), "BOOT: waiting for firmware".to_string()),
            Boot::LoaderStarted => (Color::Warn, "firmware started the Limine loader from the boot disk".to_string(), "BOOT: loader started".to_string()),
            Boot::KernelEntered => (Color::Warn, "kernel entered (NASM entry, Rust kmain); initializing".to_string(), "BOOT: kernel entered".to_string()),
            Boot::Operational => {
                let mut s = format!(
                    "OPERATIONAL at {:.1} s | uptime {} s | heartbeat {} ({}) | faults {}",
                    o.operational_at.unwrap_or(0.0),
                    o.last_uptime.unwrap_or(0),
                    if o.ticks_continuous { "continuous" } else { "GAP" },
                    o.ticks,
                    o.faults.len()
                );
                if !o.clock_gaps.is_empty() {
                    let total: u64 = o.clock_gaps.iter().map(|p| p.2).sum();
                    s.push_str(&format!(" | clock gap {total} s"));
                }
                if !done && late > 5.0 {
                    s.push_str(&format!(" | NO HEARTBEAT FOR {late:.0} s"));
                }
                let bad = !o.faults.is_empty() || !o.ticks_continuous || !o.boot_problems.is_empty() || (!done && late > 5.0);
                let paused = !o.clock_gaps.is_empty() || o.clock_degraded.is_some();
                let st = if bad {
                    format!("BOOT: OPERATIONAL, with problems: faults {} unexplained gaps {}", o.faults.len(), o.unexplained_gaps.len())
                } else if paused {
                    format!(
                        "BOOT: OPERATIONAL; {} clock gap(s) reported by the kernel; clock {}",
                        o.clock_gaps.len(),
                        if o.clock_degraded.is_some() { "DEGRADED" } else { "OK" }
                    )
                } else {
                    "BOOT: OPERATIONAL".to_string()
                };
                (if bad { Color::Bad } else if paused { Color::Warn } else { Color::Good }, s, st)
            }
            Boot::Failed(w) => {
                let designed = k.build == Build::EarlyFail && o.early_fail_as_designed();
                let s = format!("BOOT FAILED{}: {w}", if designed { " (as this DIAGNOSTIC build is designed to)" } else { "" });
                (Color::Bad, s.clone(), s)
            }
        };
        rows.push(PanelRow { color: bc, text: format!(" KERNEL BOOT       : {bt}"), stable: bs });
        let svc = match (&o.latest, k.build) {
            (_, Build::EarlyFail) => ("not reached in this build".to_string(), String::new(), Color::Dim),
            (None, _) => ("no status round yet".to_string(), String::new(), Color::Dim),
            (Some(r), _) => {
                // The running service first; for the others, the status and its reason.
                let mut order: Vec<&observe::Svc> = r.iter().collect();
                order.sort_by_key(|s| s.status != "AVAILABLE");
                // Services with the same status and reason share one entry.
                let mut groups: Vec<(String, Vec<String>)> = Vec::new();
                for s in &order {
                    let what = if s.status == "AVAILABLE" {
                        format!("{}/AVAILABLE value={}", s.state, s.value)
                    } else {
                        format!("{} {}", s.status, s.reason)
                    };
                    match groups.iter_mut().find(|g| g.0 == what && s.status != "AVAILABLE") {
                        Some(g) => g.1.push(s.id.clone()),
                        None => groups.push((what, vec![s.id.clone()])),
                    }
                }
                let t = groups.iter().map(|(w, ids)| format!("{} {w}", ids.join(", "))).collect::<Vec<_>>().join(" | ");
                let st = r.iter().map(|s| format!("{} {}/{} {}", s.id, s.state, s.status, s.reason)).collect::<Vec<_>>().join("; ");
                (format!("round {} | {t}", o.rounds), format!("SERVICES: {st}{}", if o.counted_service_problems().is_empty() { "" } else { " - PROBLEMS" }), if o.counted_service_problems().is_empty() { Color::Info } else { Color::Bad })
            }
        };
        rows.push(PanelRow { color: svc.2, text: format!(" SERVICES          : {}", svc.0), stable: svc.1 });
        let apps = match &o.app_registry {
            None => (if k.build == Build::EarlyFail { "not reached in this build".into() } else { "no application registry yet".to_string() }, String::new()),
            Some(observe::AppReg::Refused { diag, entry, .. }) => (format!("registry REFUSED at boot: {diag} entry {entry}"), format!("APPS: registry REFUSED {diag}")),
            Some(observe::AppReg::Ok { executor, .. }) => {
                // Applications in the same state, missing the same services, share one entry.
                let mut groups: Vec<(String, Vec<String>)> = Vec::new();
                for (id, pre, un) in &o.latest_apps {
                    let what = if pre == "SATISFIED" {
                        "SATISFIED".to_string()
                    } else {
                        let svc: Vec<&str> = un.split(',').map(|m| m.split(':').next().unwrap_or(m)).collect();
                        format!("{pre} ({})", svc.join(","))
                    };
                    let name = id.trim_start_matches("app.").to_string();
                    match groups.iter_mut().find(|g| g.0 == what) {
                        Some(g) => g.1.push(name),
                        None => groups.push((what, vec![name])),
                    }
                }
                // 0.33.1 (DEV-006): grouped by state, so the row fits 120 columns also when every application is
                // UNSATISFIED (a DEGRADED clock): "SATISFIED: a | UNSATISFIED: b (svc.x); c, d (svc.y)".
                let sat: Vec<String> = groups.iter().filter(|g| g.0 == "SATISFIED").flat_map(|g| g.1.clone()).collect();
                let unsat: Vec<String> = groups
                    .iter()
                    .filter(|g| g.0 != "SATISFIED")
                    .map(|(w, n)| format!("{} {}", n.join(", "), w.split_once(' ').map(|x| x.1).unwrap_or("")))
                    .collect();
                let mut parts = Vec::new();
                if !sat.is_empty() {
                    parts.push(format!("SATISFIED: {}", sat.join(", ")));
                }
                if !unsat.is_empty() {
                    parts.push(format!("UNSATISFIED: {}", unsat.join("; ")));
                }
                let a = parts.join(" | ");
                let st = o.latest_apps.iter().map(|(id, pre, _)| format!("{id} {pre}")).collect::<Vec<_>>().join("; ");
                let ex = if executor == "ABSENT" { "no executor".to_string() } else { format!("executor {executor}") };
                (format!("registry OK, {ex} | {a}"), format!("APPS: registry OK, executor {executor}; {st}"))
            }
        };
        rows.push(PanelRow { color: Color::App, text: format!(" APPLICATIONS      : {}", apps.0), stable: apps.1 });
        let v = o.contract(done, matches!(b, Boot::Failed(_)));
        let vc = match v { Verdict::Consistent(_) => Color::Good, Verdict::Inconsistent(_) => Color::Bad, _ => Color::Warn };
        let stable = match &v {
            Verdict::Consistent(_) => format!("LAUNCHER CONTRACT: CONSISTENT ({})", if k.build == Build::Launchpad { "17 requests as designed" } else { "registry and APPINFO as designed, no request" }),
            other => format!("LAUNCHER CONTRACT: {} - {}", other.word(), other.text()),
        };
        let short = match &v {
            Verdict::Consistent(_) if k.build == Build::Launchpad => format!(
                "17 of 17 as designed: {} refused, {} not executed, 1 discovery, 1 routed; executed 0",
                o.rows.iter().filter(|r| r.state == "REFUSED").count(),
                o.rows.iter().filter(|r| r.state == "NOT_EXECUTED").count()
            ),
            Verdict::Consistent(_) => {
                format!("registry OK; APPINFO agrees with services ({} rounds); no request; nothing executed", o.appinfo_groups)
            }
            Verdict::NotReached(_) => "the kernel stopped before OPERATIONAL: no application registry in this boot".to_string(),
            other => other.text().to_string(),
        };
        rows.push(PanelRow { color: vc, text: format!(" LAUNCHER CONTRACT : {} - {short}", v.word()), stable });
        rows.push(PanelRow {
            color: Color::Normal,
            text: if done {
                format!(" VM stopped: {} | the result and the record folder are below", mode.unwrap_or(""))
            } else {
                format!(" [Q] shut the VM down  [L] open the record folder  [H] heartbeat lines | live checks | {t:.0} s")
            },
            stable: String::new(),
        });
        rows.push(PanelRow { color: Color::Dim, text: "-".repeat(200), stable: String::new() });
        rows
    }

    /// A launch refused before QEMU started: the record says why, and is sealed.
    fn refused(&mut self, o: Outcome, why: &str) -> Outcome {
        let mut vd = Obj::new();
        vd.put("kernel_boot", J::s("NOT STARTED"))
            .put("launcher_contract", J::s("NOT STARTED"))
            .put("vm_shutdown", J::s("NOT STARTED (QEMU was never started)"))
            .put("refusal", J::s(why));
        self.record.put("verdicts", vd.build());
        self.ui.line(Color::Bad, &format!("RESULT: {} (exit code {}) - {why}", o.name(), o as i32));
        let _ = fs::write(self.dir.join("verdict.txt"), format!("RESULT: {} (exit code {}) - {why}\r\n", o.name(), o as i32));
        self.finish(o)
    }

    fn finish(&mut self, o: Outcome) -> Outcome {
        let ended = util::utc();
        let mut rec = std::mem::replace(&mut self.record, Obj::new());
        rec.put("result", J::s(o.name()))
            .put("exit_code", J::n(o as i32))
            .put("ended_utc", J::s(ended))
            .put("evidence_label", J::s("VM_MEASURED (operator launch through the host VM launcher), or a host check when refused before start"))
            .put(
                "not_claimed",
                J::Arr(vec![
                    J::s("the official C0-C13 judgment: the verdicts here are the launcher's live checks"),
                    J::s("a graphical desktop or framebuffer: Abraham has none in 0.33"),
                    J::s("running Windows programs inside Abraham: the launcher runs the virtual machine only"),
                    J::s("execution of anything inside Abraham: the 0.33 executor is ABSENT"),
                    J::s("acceptance of 0.33 (Jadin decides)"),
                ]),
            );
        let _ = fs::write(self.dir.join("launch.json"), rec.build().pretty());
        self.ui.line(Color::Normal, &format!("record: {}", self.dir.display()));
        self.ui.close_transcript();
        let (n, ok) = util::seal(&self.dir);
        self.ui.screen_only(
            if ok { Color::Normal } else { Color::Bad },
            &format!("[launcher] {n} files sealed in RUN_SHA256SUMS.json, re-read {}", if ok { "OK" } else { "FAILED" }),
        );
        o
    }
}

/// Offline: the live checks applied to a saved serial log (for audit: does the launcher's view agree with the judges?).
fn check_serial(path: &Path, key: &str) -> i32 {
    let k = match pins::kernel(key) {
        Some(k) => k,
        None => return Outcome::LauncherError as i32,
    };
    let bytes = match fs::read(path) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("{}: {e}", path.display());
            return Outcome::LauncherError as i32;
        }
    };
    let mut a = observe::LineAssembler::default();
    let mut o = Observer::new(k.build, k.version);
    for l in a.push(&bytes) {
        o.feed(&l, 0.0);
    }
    o.end_of_capture(a.flush());
    let b = o.boot(0.0, f64::INFINITY, true);
    let failed = matches!(b, Boot::Failed(_));
    let v = o.contract(true, failed);
    let checks = |v: &[(&'static str, bool)]| J::Obj(v.iter().map(|(k, b)| (k.to_string(), J::Bool(*b))).collect());
    let mut r = Obj::new();
    r.put("serial", J::s(path.display().to_string()))
        .put("serial_sha256", J::s(hash::sha256_hex(&bytes)))
        .put("kernel_expectation", J::s(k.key))
        .put("boot", J::s(format!("{b:?}")))
        .put("kernel_boot_checks", checks(&o.boot_checks(o.ticks > 0)))
        .put("service_checks", checks(&o.service_checks()))
        .put("launcher_contract", J::s(v.word()))
        .put("launcher_contract_detail", J::s(v.text()))
        .put("contract_problems", J::Arr(o.contract_problems.iter().map(|s| J::s(s.clone())).collect()))
        .put("service_problems", J::Arr(o.counted_service_problems().into_iter().map(J::s).collect()))
        .put("cut_line", J::opt_s(o.cut_line.clone()))
        .put("clock_degraded", J::opt_s(o.clock_degraded.clone()))
        .put(
            "clock_gaps_reported_by_the_kernel",
            J::Arr(o.clock_gaps.iter().map(|(a, b, n)| J::s(format!("{a} -> {b}, {n} s skipped"))).collect()),
        )
        .put("unexplained_heartbeat_gaps", J::Arr(o.unexplained_gaps.iter().map(|(a, b)| J::s(format!("{a} -> {b}"))).collect()))
        .put("note", J::s("heartbeat_alive_until_shutdown is not meaningful offline"));
    println!("{}", r.build().pretty());
    match v {
        Verdict::Consistent(_) => 0,
        Verdict::NotReached(_) if k.build == Build::EarlyFail && o.early_fail_as_designed() => 0,
        Verdict::Inconsistent(_) => Outcome::ContractInconsistent as i32,
        _ => Outcome::BootFailed as i32,
    }
}
