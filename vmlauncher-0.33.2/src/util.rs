//! Time stamps, the run seal, and small file helpers.

use crate::hash;
use crate::json::J;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn parts() -> (i64, u32, u32, u64, u64, u64, u32) {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let secs = d.as_secs() as i64;
    let (y, mo, da) = civil(secs.div_euclid(86_400));
    let rem = secs.rem_euclid(86_400) as u64;
    (y, mo, da, rem / 3600, (rem / 60) % 60, rem % 60, d.subsec_micros())
}

/// ISO 8601 UTC, as Python's `datetime.now(timezone.utc).isoformat()` writes it.
pub fn utc() -> String {
    let (y, mo, d, h, mi, s, us) = parts();
    format!("{y:04}-{mo:02}-{d:02}T{h:02}:{mi:02}:{s:02}.{us:06}+00:00")
}

/// A compact UTC stamp for run ids.
pub fn stamp() -> String {
    let (y, mo, d, h, mi, s, _) = parts();
    format!("{y:04}{mo:02}{d:02}T{h:02}{mi:02}{s:02}Z")
}

fn files_under(dir: &Path, base: &Path, out: &mut Vec<PathBuf>) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        let mut entries: Vec<_> = rd.flatten().map(|e| e.path()).collect();
        entries.sort();
        for p in entries {
            if p.is_dir() {
                files_under(&p, base, out);
            } else if p.is_file() {
                out.push(p);
            }
        }
    }
}

pub fn rel_posix(p: &Path, base: &Path) -> String {
    p.strip_prefix(base).unwrap_or(p).to_string_lossy().replace('\\', "/")
}

/// The run seal: RUN_SHA256SUMS.json, {relative path: sha256} sorted by path with one-space indentation, as the
/// harness writes it. Returns (files sealed, every digest re-read and confirmed).
pub fn seal(run: &Path) -> (usize, bool) {
    let mut files = Vec::new();
    files_under(run, run, &mut files);
    let mut rows: Vec<(String, String)> = files
        .iter()
        .filter(|p| p.file_name().map(|n| n != "RUN_SHA256SUMS.json").unwrap_or(false))
        .map(|p| (rel_posix(p, run), hash::sha256_file(p).unwrap_or_else(|e| format!("UNREADABLE: {e}"))))
        .collect();
    rows.sort();
    let obj = J::Obj(rows.iter().map(|(k, v)| (k.clone(), J::s(v.clone()))).collect());
    let _ = std::fs::write(run.join("RUN_SHA256SUMS.json"), obj.pretty());
    let recheck = rows.iter().all(|(k, v)| hash::sha256_file(&run.join(k.replace('/', "\\"))).ok().as_deref() == Some(v));
    (rows.len(), recheck)
}

#[cfg(test)]
mod tests {
    #[test]
    fn civil_dates() {
        assert_eq!(super::civil(0), (1970, 1, 1));
        assert_eq!(super::civil(20_401), (2025, 11, 9));
        assert_eq!(super::civil(20_766), (2026, 11, 9));
        assert_eq!(super::civil(-1), (1969, 12, 31));
        assert_eq!(super::civil(11_016), (2000, 2, 29));
    }
}
