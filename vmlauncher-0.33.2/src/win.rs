//! The Windows API calls the launcher needs, declared by hand (no crate). Every call is user-mode and per-process:
//! nothing here changes a system setting, the boot configuration or PATH, or asks for elevation.

#![allow(non_snake_case, non_camel_case_types, clippy::upper_case_acronyms, dead_code)]

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;

pub type HANDLE = *mut c_void;
pub type BOOL = i32;

pub const INVALID_HANDLE_VALUE: HANDLE = -1isize as HANDLE;
pub const ERROR_ALREADY_EXISTS: u32 = 183;
pub const STD_INPUT_HANDLE: u32 = -10i32 as u32;
pub const STD_OUTPUT_HANDLE: u32 = -11i32 as u32;
pub const ENABLE_PROCESSED_OUTPUT: u32 = 0x1;
pub const ENABLE_VIRTUAL_TERMINAL_PROCESSING: u32 = 0x4;
pub const TH32CS_SNAPPROCESS: u32 = 0x2;
pub const TH32CS_SNAPTHREAD: u32 = 0x4;
pub const THREAD_SUSPEND_RESUME: u32 = 0x2;
pub const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
pub const PROCESS_TERMINATE: u32 = 0x1;
pub const CREATE_SUSPENDED: u32 = 0x4;
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
pub const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: u32 = 0x2000;
pub const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: i32 = 9;
pub const JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS: i32 = 1;
pub const PROCESS_POWER_THROTTLING_CLASS: i32 = 4;
pub const PROCESS_POWER_THROTTLING_CURRENT_VERSION: u32 = 1;
pub const PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION: u32 = 0x4;
pub const TOKEN_QUERY: u32 = 0x8;
pub const TOKEN_ELEVATION_CLASS: i32 = 20;
pub const CTRL_C_EVENT: u32 = 0;
pub const CTRL_BREAK_EVENT: u32 = 1;
pub const CTRL_CLOSE_EVENT: u32 = 2;
pub const CTRL_LOGOFF_EVENT: u32 = 5;
pub const CTRL_SHUTDOWN_EVENT: u32 = 6;
pub const HKEY_LOCAL_MACHINE: isize = 0x8000_0002u32 as i32 as isize;
pub const RRF_RT_REG_SZ: u32 = 0x2;

#[repr(C)]
pub struct PROCESSENTRY32W {
    pub dwSize: u32,
    pub cntUsage: u32,
    pub th32ProcessID: u32,
    pub th32DefaultHeapID: usize,
    pub th32ModuleID: u32,
    pub cntThreads: u32,
    pub th32ParentProcessID: u32,
    pub pcPriClassBase: i32,
    pub dwFlags: u32,
    pub szExeFile: [u16; 260],
}

#[repr(C)]
pub struct THREADENTRY32 {
    pub dwSize: u32,
    pub cntUsage: u32,
    pub th32ThreadID: u32,
    pub th32OwnerProcessID: u32,
    pub tpBasePri: i32,
    pub tpDeltaPri: i32,
    pub dwFlags: u32,
}

#[repr(C)]
#[derive(Default)]
pub struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    pub PerProcessUserTimeLimit: i64,
    pub PerJobUserTimeLimit: i64,
    pub LimitFlags: u32,
    pub MinimumWorkingSetSize: usize,
    pub MaximumWorkingSetSize: usize,
    pub ActiveProcessLimit: u32,
    pub Affinity: usize,
    pub PriorityClass: u32,
    pub SchedulingClass: u32,
}

#[repr(C)]
#[derive(Default)]
pub struct IO_COUNTERS {
    pub counts: [u64; 6],
}

#[repr(C)]
#[derive(Default)]
pub struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    pub BasicLimitInformation: JOBOBJECT_BASIC_LIMIT_INFORMATION,
    pub IoInfo: IO_COUNTERS,
    pub ProcessMemoryLimit: usize,
    pub JobMemoryLimit: usize,
    pub PeakProcessMemoryUsed: usize,
    pub PeakJobMemoryUsed: usize,
}

#[repr(C)]
#[derive(Default)]
pub struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION {
    pub TotalUserTime: i64,
    pub TotalKernelTime: i64,
    pub ThisPeriodTotalUserTime: i64,
    pub ThisPeriodTotalKernelTime: i64,
    pub TotalPageFaultCount: u32,
    pub TotalProcesses: u32,
    pub ActiveProcesses: u32,
    pub TotalTerminatedProcesses: u32,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
pub struct PROCESS_POWER_THROTTLING_STATE {
    pub Version: u32,
    pub ControlMask: u32,
    pub StateMask: u32,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
pub struct COORD {
    pub X: i16,
    pub Y: i16,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
pub struct SMALL_RECT {
    pub Left: i16,
    pub Top: i16,
    pub Right: i16,
    pub Bottom: i16,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
pub struct CONSOLE_SCREEN_BUFFER_INFO {
    pub dwSize: COORD,
    pub dwCursorPosition: COORD,
    pub wAttributes: u16,
    pub srWindow: SMALL_RECT,
    pub dwMaximumWindowSize: COORD,
}

pub type HandlerRoutine = unsafe extern "system" fn(u32) -> BOOL;

#[link(name = "kernel32")]
extern "system" {
    pub fn GetLastError() -> u32;
    pub fn CloseHandle(h: HANDLE) -> BOOL;
    pub fn CreateMutexW(attrs: *mut c_void, initial_owner: BOOL, name: *const u16) -> HANDLE;
    pub fn SetConsoleCtrlHandler(routine: Option<HandlerRoutine>, add: BOOL) -> BOOL;
    pub fn CreateJobObjectW(attrs: *mut c_void, name: *const u16) -> HANDLE;
    pub fn SetInformationJobObject(job: HANDLE, class: i32, info: *mut c_void, len: u32) -> BOOL;
    pub fn QueryInformationJobObject(job: HANDLE, class: i32, info: *mut c_void, len: u32, ret: *mut u32) -> BOOL;
    pub fn AssignProcessToJobObject(job: HANDLE, process: HANDLE) -> BOOL;
    pub fn TerminateJobObject(job: HANDLE, code: u32) -> BOOL;
    pub fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> HANDLE;
    pub fn Process32FirstW(snap: HANDLE, e: *mut PROCESSENTRY32W) -> BOOL;
    pub fn Process32NextW(snap: HANDLE, e: *mut PROCESSENTRY32W) -> BOOL;
    pub fn Thread32First(snap: HANDLE, e: *mut THREADENTRY32) -> BOOL;
    pub fn Thread32Next(snap: HANDLE, e: *mut THREADENTRY32) -> BOOL;
    pub fn OpenThread(access: u32, inherit: BOOL, tid: u32) -> HANDLE;
    pub fn ResumeThread(thread: HANDLE) -> u32;
    pub fn OpenProcess(access: u32, inherit: BOOL, pid: u32) -> HANDLE;
    pub fn QueryFullProcessImageNameW(process: HANDLE, flags: u32, name: *mut u16, size: *mut u32) -> BOOL;
    pub fn SetProcessInformation(process: HANDLE, class: i32, info: *mut c_void, len: u32) -> BOOL;
    pub fn GetProcessInformation(process: HANDLE, class: i32, info: *mut c_void, len: u32) -> BOOL;
    pub fn GetCurrentProcess() -> HANDLE;
    pub fn GetCurrentProcessId() -> u32;
    pub fn GetStdHandle(which: u32) -> HANDLE;
    pub fn GetConsoleMode(h: HANDLE, mode: *mut u32) -> BOOL;
    pub fn SetConsoleMode(h: HANDLE, mode: u32) -> BOOL;
    pub fn GetConsoleScreenBufferInfo(h: HANDLE, info: *mut CONSOLE_SCREEN_BUFFER_INFO) -> BOOL;
    pub fn SetConsoleTitleW(title: *const u16) -> BOOL;
    pub fn GetConsoleProcessList(list: *mut u32, count: u32) -> u32;
    pub fn FlushConsoleInputBuffer(h: HANDLE) -> BOOL;
}

#[link(name = "advapi32")]
extern "system" {
    pub fn OpenProcessToken(process: HANDLE, access: u32, token: *mut HANDLE) -> BOOL;
    pub fn GetTokenInformation(token: HANDLE, class: i32, info: *mut c_void, len: u32, ret: *mut u32) -> BOOL;
    pub fn RegGetValueW(
        key: isize,
        subkey: *const u16,
        value: *const u16,
        flags: u32,
        kind: *mut u32,
        data: *mut c_void,
        len: *mut u32,
    ) -> i32;
}

extern "C" {
    // The C runtime's unbuffered console key read, from the CRT that the MSVC target links anyway.
    fn _getch() -> i32;
}

pub fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

pub fn wide_path(p: &Path) -> Vec<u16> {
    p.as_os_str().encode_wide().chain(std::iter::once(0)).collect()
}

/// A handle closed when dropped.
pub struct Owned(pub HANDLE);

impl Owned {
    pub fn valid(&self) -> bool {
        !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE
    }
}

impl Drop for Owned {
    fn drop(&mut self) {
        if self.valid() {
            unsafe { CloseHandle(self.0) };
        }
    }
}

// SAFETY: a Windows kernel handle may be used from any thread.
unsafe impl Send for Owned {}
unsafe impl Sync for Owned {}

pub fn last_error() -> u32 {
    unsafe { GetLastError() }
}

/// The single-instance lock. Returns (handle, already_existed). The mutex is released when the process ends, even if
/// it is killed.
pub fn named_mutex(name: &str) -> (Owned, bool) {
    let w = wide(name);
    let h = unsafe { CreateMutexW(std::ptr::null_mut(), 0, w.as_ptr()) };
    let existed = unsafe { GetLastError() } == ERROR_ALREADY_EXISTS;
    (Owned(h), existed)
}

pub struct ProcInfo {
    pub pid: u32,
    pub parent: u32,
    pub exe_name: String,
    pub image: Option<String>,
}

pub fn processes() -> Vec<ProcInfo> {
    let mut out = Vec::new();
    let snap = Owned(unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) });
    if !snap.valid() {
        return out;
    }
    let mut e: PROCESSENTRY32W = unsafe { std::mem::zeroed() };
    e.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;
    let mut ok = unsafe { Process32FirstW(snap.0, &mut e) };
    while ok != 0 {
        let len = e.szExeFile.iter().position(|&c| c == 0).unwrap_or(e.szExeFile.len());
        let name = String::from_utf16_lossy(&e.szExeFile[..len]);
        out.push(ProcInfo { pid: e.th32ProcessID, parent: e.th32ParentProcessID, exe_name: name, image: None });
        ok = unsafe { Process32NextW(snap.0, &mut e) };
    }
    for p in out.iter_mut() {
        if p.exe_name.to_ascii_lowercase().starts_with("qemu") {
            p.image = image_path(p.pid);
        }
    }
    out
}

pub fn image_path(pid: u32) -> Option<String> {
    let h = Owned(unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) });
    if !h.valid() {
        return None;
    }
    let mut buf = vec![0u16; 1024];
    let mut size = buf.len() as u32;
    if unsafe { QueryFullProcessImageNameW(h.0, 0, buf.as_mut_ptr(), &mut size) } == 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buf[..size as usize]))
}

/// Resumes every thread of a process created suspended. Returns how many threads were resumed.
pub fn resume_process(pid: u32) -> Result<u32, String> {
    let snap = Owned(unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) });
    if !snap.valid() {
        return Err(format!("thread snapshot failed (error {})", last_error()));
    }
    let mut e: THREADENTRY32 = unsafe { std::mem::zeroed() };
    e.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
    let mut resumed = 0;
    let mut ok = unsafe { Thread32First(snap.0, &mut e) };
    while ok != 0 {
        if e.th32OwnerProcessID == pid {
            let t = Owned(unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, e.th32ThreadID) });
            if !t.valid() {
                return Err(format!("OpenThread {} failed (error {})", e.th32ThreadID, last_error()));
            }
            if unsafe { ResumeThread(t.0) } == u32::MAX {
                return Err(format!("ResumeThread {} failed (error {})", e.th32ThreadID, last_error()));
            }
            resumed += 1;
        }
        ok = unsafe { Thread32Next(snap.0, &mut e) };
    }
    if resumed == 0 {
        return Err("no thread of the QEMU process was found to resume".into());
    }
    Ok(resumed)
}

/// A job object that kills every process in it when its last handle closes, so a QEMU started by the launcher cannot
/// outlive the launcher, even if the launcher is killed.
pub fn kill_on_close_job() -> Result<Owned, String> {
    let job = Owned(unsafe { CreateJobObjectW(std::ptr::null_mut(), std::ptr::null()) });
    if !job.valid() {
        return Err(format!("CreateJobObjectW failed (error {})", last_error()));
    }
    let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let ok = unsafe {
        SetInformationJobObject(
            job.0,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            &mut info as *mut _ as *mut c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if ok == 0 {
        return Err(format!("SetInformationJobObject failed (error {})", last_error()));
    }
    Ok(job)
}

pub fn job_assign(job: &Owned, process: HANDLE) -> Result<(), String> {
    if unsafe { AssignProcessToJobObject(job.0, process) } == 0 {
        return Err(format!("AssignProcessToJobObject failed (error {})", last_error()));
    }
    Ok(())
}

pub fn job_counts(job: &Owned) -> Option<(u32, u32)> {
    let mut info = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
    let ok = unsafe {
        QueryInformationJobObject(
            job.0,
            JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            &mut info as *mut _ as *mut c_void,
            std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
            std::ptr::null_mut(),
        )
    };
    if ok == 0 {
        None
    } else {
        Some((info.ActiveProcesses, info.TotalProcesses))
    }
}

/// The process ids now in the job.
pub fn job_pids(job: &Owned) -> Vec<u32> {
    #[repr(C)]
    struct List {
        assigned: u32,
        in_list: u32,
        ids: [usize; 32],
    }
    let mut l = List { assigned: 0, in_list: 0, ids: [0; 32] };
    let ok = unsafe {
        QueryInformationJobObject(job.0, 3, &mut l as *mut _ as *mut c_void, std::mem::size_of::<List>() as u32, std::ptr::null_mut())
    };
    if ok == 0 {
        return Vec::new();
    }
    l.ids[..(l.in_list as usize).min(32)].iter().map(|&p| p as u32).collect()
}

pub fn job_terminate(job: &Owned, code: u32) -> bool {
    unsafe { TerminateJobObject(job.0, code) != 0 }
}

/// The 0.29 G4 timer-resolution opt-out (TR-0017, D-ABR-005), exactly as the harness applies it: control mask
/// IGNORE_TIMER_RESOLUTION, state 0 (do not throttle). Per process; no system setting. Returns (ok, error).
pub fn opt_out_timer_throttling(process: HANDLE) -> (bool, Option<u32>) {
    let mut st = PROCESS_POWER_THROTTLING_STATE {
        Version: PROCESS_POWER_THROTTLING_CURRENT_VERSION,
        ControlMask: PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION,
        StateMask: 0,
    };
    let ok = unsafe {
        SetProcessInformation(
            process,
            PROCESS_POWER_THROTTLING_CLASS,
            &mut st as *mut _ as *mut c_void,
            std::mem::size_of::<PROCESS_POWER_THROTTLING_STATE>() as u32,
        )
    };
    if ok != 0 {
        (true, None)
    } else {
        (false, Some(last_error()))
    }
}

/// Reads the throttling state back, where Windows supports it (informational; the harness records only the set call).
pub fn read_timer_throttling(process: HANDLE) -> Result<(u32, u32), u32> {
    let mut st = PROCESS_POWER_THROTTLING_STATE { Version: PROCESS_POWER_THROTTLING_CURRENT_VERSION, ..Default::default() };
    let ok = unsafe {
        GetProcessInformation(
            process,
            PROCESS_POWER_THROTTLING_CLASS,
            &mut st as *mut _ as *mut c_void,
            std::mem::size_of::<PROCESS_POWER_THROTTLING_STATE>() as u32,
        )
    };
    if ok != 0 {
        Ok((st.ControlMask, st.StateMask))
    } else {
        Err(last_error())
    }
}

/// Some(true) when this process runs elevated (as administrator). The launcher never asks for elevation.
pub fn elevated() -> Option<bool> {
    let mut token: HANDLE = std::ptr::null_mut();
    if unsafe { OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) } == 0 {
        return None;
    }
    let token = Owned(token);
    let mut v: u32 = 0;
    let mut ret = 0u32;
    let ok = unsafe { GetTokenInformation(token.0, TOKEN_ELEVATION_CLASS, &mut v as *mut _ as *mut c_void, 4, &mut ret) };
    if ok == 0 {
        None
    } else {
        Some(v != 0)
    }
}

pub fn reg_string(subkey: &str, value: &str) -> Option<String> {
    let sk = wide(subkey);
    let vn = wide(value);
    let mut buf = vec![0u16; 512];
    let mut len = (buf.len() * 2) as u32;
    let r = unsafe {
        RegGetValueW(
            HKEY_LOCAL_MACHINE,
            sk.as_ptr(),
            vn.as_ptr(),
            RRF_RT_REG_SZ,
            std::ptr::null_mut(),
            buf.as_mut_ptr() as *mut c_void,
            &mut len,
        )
    };
    if r != 0 {
        return None;
    }
    let n = (len as usize / 2).min(buf.len());
    let s = String::from_utf16_lossy(&buf[..n]);
    Some(s.trim_end_matches('\0').to_string())
}

pub struct Console {
    pub out: HANDLE,
    pub input: HANDLE,
    pub out_is_console: bool,
    pub in_is_console: bool,
    pub vt: bool,
}

pub fn console() -> Console {
    unsafe {
        let out = GetStdHandle(STD_OUTPUT_HANDLE);
        let input = GetStdHandle(STD_INPUT_HANDLE);
        let mut mode = 0u32;
        let out_is_console = GetConsoleMode(out, &mut mode) != 0;
        let mut vt = false;
        if out_is_console {
            vt = SetConsoleMode(out, mode | ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0;
        }
        let mut imode = 0u32;
        let in_is_console = GetConsoleMode(input, &mut imode) != 0;
        Console { out, input, out_is_console, in_is_console, vt }
    }
}

pub fn console_size(out: HANDLE) -> Option<(usize, usize)> {
    let mut info = CONSOLE_SCREEN_BUFFER_INFO::default();
    if unsafe { GetConsoleScreenBufferInfo(out, &mut info) } == 0 {
        return None;
    }
    let rows = (info.srWindow.Bottom - info.srWindow.Top + 1).max(1) as usize;
    let cols = (info.srWindow.Right - info.srWindow.Left + 1).max(1) as usize;
    Some((rows, cols))
}

pub fn set_title(t: &str) {
    let w = wide(t);
    unsafe { SetConsoleTitleW(w.as_ptr()) };
}

/// The number of processes attached to this console. 1 means the console was created for this program alone, which
/// is what happens on a double-click: the window must then stay open until the operator has read the result.
pub fn console_process_count() -> u32 {
    let mut list = [0u32; 16];
    unsafe { GetConsoleProcessList(list.as_mut_ptr(), 16) }
}

pub fn getch() -> i32 {
    unsafe { _getch() }
}

pub fn flush_input(h: HANDLE) {
    unsafe { FlushConsoleInputBuffer(h) };
}

pub fn set_ctrl_handler(f: HandlerRoutine) -> bool {
    unsafe { SetConsoleCtrlHandler(Some(f), 1) != 0 }
}

pub fn current_pid() -> u32 {
    unsafe { GetCurrentProcessId() }
}
