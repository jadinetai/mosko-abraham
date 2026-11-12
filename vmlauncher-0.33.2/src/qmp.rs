//! A line-oriented QMP client over 127.0.0.1, as in the harness (`abr_boot_001.Qmp`). Every message is logged to
//! `qmp.jsonl` as {"kind", "message", "t"} with the host's monotonic time since the run started.

use crate::json::{self, Obj, J};
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub struct Qmp {
    writer: TcpStream,
    replies: Receiver<Option<J>>,
    log: Arc<Mutex<File>>,
    t0: Instant,
    pub events: Arc<Mutex<Vec<J>>>,
}

fn record(log: &Arc<Mutex<File>>, t0: Instant, kind: &str, message: J) {
    let mut o = Obj::new();
    o.put("kind", J::s(kind)).put("message", message).put("t", J::f3(t0.elapsed().as_secs_f64()));
    if let Ok(mut f) = log.lock() {
        let _ = f.write_all(o.build().compact().as_bytes());
        let _ = f.write_all(b"\n");
        let _ = f.flush();
    }
}

impl Qmp {
    /// `alive` is asked before every retry: once QEMU has exited there is nothing to wait for (DRY-N014).
    pub fn connect(
        port: u16,
        log_path: &std::path::Path,
        t0: Instant,
        timeout: Duration,
        alive: &mut dyn FnMut() -> bool,
    ) -> Result<Qmp, String> {
        let addr: SocketAddr = ([127, 0, 0, 1], port).into();
        let deadline = Instant::now() + timeout;
        let stream = loop {
            match TcpStream::connect_timeout(&addr, Duration::from_secs(2)) {
                Ok(s) => break s,
                Err(e) => {
                    if !alive() {
                        return Err("QEMU exited before its QMP channel answered".into());
                    }
                    if Instant::now() > deadline {
                        return Err(format!("QMP connection to 127.0.0.1:{port} failed: {e}"));
                    }
                    std::thread::sleep(Duration::from_millis(200));
                }
            }
        };
        let _ = stream.set_nodelay(true);
        let log = Arc::new(Mutex::new(File::create(log_path).map_err(|e| format!("qmp.jsonl: {e}"))?));
        let reader = stream.try_clone().map_err(|e| format!("QMP socket: {e}"))?;
        let (tx, rx) = channel();
        let events = Arc::new(Mutex::new(Vec::new()));
        {
            let log = log.clone();
            let events = events.clone();
            std::thread::spawn(move || {
                let mut r = BufReader::new(reader);
                let mut first = true;
                let mut line = String::new();
                loop {
                    line.clear();
                    match r.read_line(&mut line) {
                        Ok(0) | Err(_) => break,
                        Ok(_) => {}
                    }
                    let msg = match json::parse(line.trim()) {
                        Ok(m) => m,
                        Err(e) => {
                            record(&log, t0, "unparsed", J::s(format!("{e}: {}", line.trim())));
                            continue;
                        }
                    };
                    if first && msg.get("QMP").is_some() {
                        first = false;
                        record(&log, t0, "greeting", msg);
                    } else if msg.get("event").is_some() {
                        record(&log, t0, "event", msg.clone());
                        if let Ok(mut e) = events.lock() {
                            e.push(msg);
                        }
                    } else {
                        record(&log, t0, "reply", msg.clone());
                        let _ = tx.send(Some(msg));
                    }
                }
                let _ = tx.send(None);
            });
        }
        let mut q = Qmp { writer: stream, replies: rx, log, t0, events };
        q.command("qmp_capabilities", None, Duration::from_secs(10))?;
        Ok(q)
    }

    /// Sends one command and waits for its reply. A reply with "error" is returned as an Err.
    pub fn command(&mut self, name: &str, arguments: Option<J>, timeout: Duration) -> Result<J, String> {
        let mut o = Obj::new();
        o.put("execute", J::s(name));
        if let Some(a) = arguments {
            o.put("arguments", a);
        }
        let req = o.build();
        record(&self.log, self.t0, "command", req.clone());
        let text = req.compact() + "\n";
        self.writer.write_all(text.as_bytes()).map_err(|e| format!("QMP write ({name}): {e}"))?;
        let _ = self.writer.flush();
        match self.replies.recv_timeout(timeout) {
            Ok(Some(reply)) => {
                if let Some(err) = reply.get("error") {
                    Err(format!("QMP {name} error: {}", err.compact()))
                } else {
                    Ok(reply)
                }
            }
            Ok(None) => Err(format!("QMP closed before the reply to {name}")),
            Err(RecvTimeoutError::Timeout) => Err(format!("no QMP reply to {name} within {} s", timeout.as_secs())),
            Err(RecvTimeoutError::Disconnected) => Err(format!("QMP closed before the reply to {name}")),
        }
    }

    pub fn events(&self) -> Vec<J> {
        self.events.lock().map(|e| e.clone()).unwrap_or_default()
    }
}
