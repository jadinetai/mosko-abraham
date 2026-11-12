//! A small JSON value: parsed from QMP messages, and written for the run records. Object keys keep their order.

#[derive(Clone, Debug, PartialEq)]
pub enum J {
    Null,
    Bool(bool),
    /// Numbers are kept as their text, so nothing is rounded.
    Num(String),
    Str(String),
    Arr(Vec<J>),
    Obj(Vec<(String, J)>),
}

impl J {
    pub fn get(&self, key: &str) -> Option<&J> {
        match self {
            J::Obj(v) => v.iter().find(|(k, _)| k == key).map(|(_, x)| x),
            _ => None,
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        match self {
            J::Str(s) => Some(s),
            _ => None,
        }
    }
    #[cfg_attr(not(test), allow(dead_code))]
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            J::Bool(b) => Some(*b),
            _ => None,
        }
    }
    pub fn s(v: impl Into<String>) -> J {
        J::Str(v.into())
    }
    pub fn n(v: impl std::fmt::Display) -> J {
        J::Num(v.to_string())
    }
    pub fn f3(v: f64) -> J {
        J::Num(format!("{:.3}", v))
    }
    pub fn opt_s(v: Option<impl Into<String>>) -> J {
        v.map(|x| J::Str(x.into())).unwrap_or(J::Null)
    }

    pub fn compact(&self) -> String {
        let mut out = String::new();
        self.write(&mut out, None, 0);
        out
    }

    /// One-space indentation, like the harness's `json.dumps(indent=1)`.
    pub fn pretty(&self) -> String {
        let mut out = String::new();
        self.write(&mut out, Some(1), 0);
        out.push('\n');
        out
    }

    fn write(&self, out: &mut String, indent: Option<usize>, depth: usize) {
        let nl = |out: &mut String, d: usize| {
            if let Some(i) = indent {
                out.push('\n');
                out.push_str(&" ".repeat(i * d));
            }
        };
        match self {
            J::Null => out.push_str("null"),
            J::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            J::Num(n) => out.push_str(n),
            J::Str(s) => escape_into(out, s),
            J::Arr(v) => {
                if v.is_empty() {
                    out.push_str("[]");
                    return;
                }
                out.push('[');
                for (i, x) in v.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                        if indent.is_none() {
                            out.push(' ');
                        }
                    }
                    nl(out, depth + 1);
                    x.write(out, indent, depth + 1);
                }
                nl(out, depth);
                out.push(']');
            }
            J::Obj(v) => {
                if v.is_empty() {
                    out.push_str("{}");
                    return;
                }
                out.push('{');
                for (i, (k, x)) in v.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                        if indent.is_none() {
                            out.push(' ');
                        }
                    }
                    nl(out, depth + 1);
                    escape_into(out, k);
                    out.push_str(": ");
                    x.write(out, indent, depth + 1);
                }
                nl(out, depth);
                out.push('}');
            }
        }
    }
}

pub fn escape_into(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                // ASCII-only output, as Python's json.dumps writes by default.
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// An object builder that keeps insertion order.
pub struct Obj(pub Vec<(String, J)>);

impl Obj {
    pub fn new() -> Self {
        Obj(Vec::new())
    }
    pub fn put(&mut self, k: &str, v: J) -> &mut Self {
        self.0.push((k.to_string(), v));
        self
    }
    pub fn build(self) -> J {
        J::Obj(self.0)
    }
}

pub fn parse(text: &str) -> Result<J, String> {
    let b = text.as_bytes();
    let mut p = 0usize;
    let v = value(b, &mut p)?;
    skip_ws(b, &mut p);
    if p != b.len() {
        return Err(format!("trailing text at byte {p}"));
    }
    Ok(v)
}

fn skip_ws(b: &[u8], p: &mut usize) {
    while *p < b.len() && matches!(b[*p], b' ' | b'\t' | b'\r' | b'\n') {
        *p += 1;
    }
}

fn value(b: &[u8], p: &mut usize) -> Result<J, String> {
    skip_ws(b, p);
    if *p >= b.len() {
        return Err("unexpected end".into());
    }
    match b[*p] {
        b'{' => {
            *p += 1;
            let mut v = Vec::new();
            skip_ws(b, p);
            if *p < b.len() && b[*p] == b'}' {
                *p += 1;
                return Ok(J::Obj(v));
            }
            loop {
                skip_ws(b, p);
                let k = match value(b, p)? {
                    J::Str(s) => s,
                    _ => return Err(format!("object key is not a string at byte {p}")),
                };
                skip_ws(b, p);
                if *p >= b.len() || b[*p] != b':' {
                    return Err(format!("expected ':' at byte {p}"));
                }
                *p += 1;
                let x = value(b, p)?;
                v.push((k, x));
                skip_ws(b, p);
                match b.get(*p) {
                    Some(b',') => *p += 1,
                    Some(b'}') => {
                        *p += 1;
                        return Ok(J::Obj(v));
                    }
                    _ => return Err(format!("expected ',' or '}}' at byte {p}")),
                }
            }
        }
        b'[' => {
            *p += 1;
            let mut v = Vec::new();
            skip_ws(b, p);
            if *p < b.len() && b[*p] == b']' {
                *p += 1;
                return Ok(J::Arr(v));
            }
            loop {
                v.push(value(b, p)?);
                skip_ws(b, p);
                match b.get(*p) {
                    Some(b',') => *p += 1,
                    Some(b']') => {
                        *p += 1;
                        return Ok(J::Arr(v));
                    }
                    _ => return Err(format!("expected ',' or ']' at byte {p}")),
                }
            }
        }
        b'"' => {
            *p += 1;
            let mut s = String::new();
            loop {
                let c = *b.get(*p).ok_or("unterminated string")?;
                *p += 1;
                match c {
                    b'"' => return Ok(J::Str(s)),
                    b'\\' => {
                        let e = *b.get(*p).ok_or("bad escape")?;
                        *p += 1;
                        match e {
                            b'"' => s.push('"'),
                            b'\\' => s.push('\\'),
                            b'/' => s.push('/'),
                            b'b' => s.push('\u{8}'),
                            b'f' => s.push('\u{c}'),
                            b'n' => s.push('\n'),
                            b'r' => s.push('\r'),
                            b't' => s.push('\t'),
                            b'u' => {
                                let hex = std::str::from_utf8(b.get(*p..*p + 4).ok_or("bad \\u")?)
                                    .map_err(|_| "bad \\u")?;
                                let unit = u32::from_str_radix(hex, 16).map_err(|_| "bad \\u")?;
                                *p += 4;
                                s.push(char::from_u32(unit).unwrap_or('\u{fffd}'));
                            }
                            _ => return Err("bad escape".into()),
                        }
                    }
                    _ => {
                        // Copy one UTF-8 sequence.
                        let start = *p - 1;
                        let len = match c {
                            0x00..=0x7f => 1,
                            0xc0..=0xdf => 2,
                            0xe0..=0xef => 3,
                            _ => 4,
                        };
                        let end = (start + len).min(b.len());
                        s.push_str(&String::from_utf8_lossy(&b[start..end]));
                        *p = end;
                    }
                }
            }
        }
        b't' if b[*p..].starts_with(b"true") => {
            *p += 4;
            Ok(J::Bool(true))
        }
        b'f' if b[*p..].starts_with(b"false") => {
            *p += 5;
            Ok(J::Bool(false))
        }
        b'n' if b[*p..].starts_with(b"null") => {
            *p += 4;
            Ok(J::Null)
        }
        b'-' | b'0'..=b'9' => {
            let start = *p;
            while *p < b.len() && matches!(b[*p], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                *p += 1;
            }
            Ok(J::Num(String::from_utf8_lossy(&b[start..*p]).into_owned()))
        }
        c => Err(format!("unexpected byte {c:#x} at {p}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_qmp_messages() {
        let g = parse(r#"{"QMP": {"version": {"qemu": {"micro": 0, "minor": 1, "major": 11}, "package": "v11.1.0"}, "capabilities": ["oob"]}}"#).unwrap();
        assert!(g.get("QMP").is_some());
        let e = parse(r#"{"timestamp": {"seconds": 1762700000, "microseconds": 5}, "event": "SHUTDOWN", "data": {"guest": false, "reason": "host-qmp-quit"}}"#).unwrap();
        assert_eq!(e.get("event").and_then(J::as_str), Some("SHUTDOWN"));
        assert_eq!(e.get("data").and_then(|d| d.get("reason")).and_then(J::as_str), Some("host-qmp-quit"));
        assert_eq!(e.get("data").and_then(|d| d.get("guest")).and_then(J::as_bool), Some(false));
        let r = parse(r#"{"return": {"status": "running", "running": true}}"#).unwrap();
        assert_eq!(r.get("return").and_then(|x| x.get("status")).and_then(J::as_str), Some("running"));
        assert_eq!(parse(r#"{"return": {}}"#).unwrap().get("return"), Some(&J::Obj(vec![])));
        assert!(parse("{\"a\": 1,}").is_err());
        assert!(parse("{\"a\": 1} x").is_err());
    }

    #[test]
    fn round_trips_and_escapes() {
        let mut o = Obj::new();
        o.put("path", J::s(r"C:\Users\x"))
            .put("quote", J::s("a\"b\n"))
            .put("list", J::Arr(vec![J::n(1), J::Bool(true), J::Null]))
            .put("empty", J::Obj(vec![]));
        let j = o.build();
        assert_eq!(parse(&j.compact()).unwrap(), j);
        assert_eq!(parse(&j.pretty()).unwrap(), j);
        assert!(j.compact().contains(r#""path": "C:\\Users\\x""#));
    }
}
