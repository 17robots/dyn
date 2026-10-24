use serde_json::{json, Value};
use std::{env, fs, io, path::Path};

fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "invalid input or counter overflow")
}
fn add(dst: &mut u64, value: u64) -> io::Result<()> {
    *dst = dst.checked_add(value).filter(|&n| n <= 9_007_199_254_740_991).ok_or_else(invalid)?;
    Ok(())
}
fn number(value: Option<&Value>, max: u64) -> io::Result<u64> {
    let value = value.and_then(Value::as_number).ok_or_else(invalid)?;
    if let Some(n) = value.as_u64() {
        return if n <= max { Ok(n) } else { Err(invalid()) };
    }
    let n = value.as_f64().ok_or_else(invalid)?;
    if n.is_finite() && n >= 0.0 && n <= max as f64 && n.fract() == 0.0 {
        Ok(n as u64)
    } else {
        Err(invalid())
    }
}
fn report(path: &Path) -> io::Result<Value> {
    let data = fs::read(path)?;
    let mut totals = [0u64; 4];
    let mut services = [[0u64; 4]; 16];
    for line in data.split(|&b| b == b'\n').filter(|line| !line.is_empty()) {
        let value: Value = serde_json::from_slice(line).map_err(|_| invalid())?;
        let obj = value.as_object().ok_or_else(invalid)?;
        let service = obj.get("service").and_then(Value::as_str).ok_or_else(invalid)?.as_bytes();
        const NAMES: [&[u8]; 16] = [
            b"svc00", b"svc01", b"svc02", b"svc03", b"svc04", b"svc05", b"svc06", b"svc07",
            b"svc08", b"svc09", b"svc10", b"svc11", b"svc12", b"svc13", b"svc14", b"svc15",
        ];
        let index = NAMES.iter().position(|&name| name == service).ok_or_else(invalid)?;
        let status = number(obj.get("status"), 599)?;
        let bytes = number(obj.get("bytes"), 9_007_199_254_740_991)?;
        let latency = number(obj.get("latency_us"), 9_007_199_254_740_991)?;
        let row = [1, bytes, latency, u64::from(status >= 500)];
        for i in 0..4 {
            add(&mut totals[i], row[i])?;
            add(&mut services[index][i], row[i])?;
        }
    }
    Ok(json!({"records":totals[0], "bytes":totals[1], "latency_us":totals[2], "errors":totals[3], "services":services}))
}
fn search_dir(path: &Path, counts: &mut [u64; 5]) -> io::Result<()> {
    use std::os::unix::ffi::OsStrExt;
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let kind = entry.file_type()?;
        if kind.is_dir() {
            search_dir(&entry.path(), counts)?;
        } else if kind.is_file() && entry.file_name().as_bytes().ends_with(b".txt") {
            let data = fs::read(entry.path())?;
            let mut lines = 0u64;
            let mut matches = 0u64;
            if !data.is_empty() {
                let content = if data.last() == Some(&b'\n') { &data[..data.len()-1] } else { &data[..] };
                for line in content.split(|&b| b == b'\n') {
                    add(&mut lines, 1)?;
                    if line.windows(5).any(|window| window == b"ERROR") { add(&mut matches, 1)?; }
                }
            }
            add(&mut counts[0], 1)?;
            add(&mut counts[1], data.len() as u64)?;
            add(&mut counts[2], lines)?;
            add(&mut counts[3], matches)?;
            add(&mut counts[4], u64::from(matches > 0))?;
        }
    }
    Ok(())
}
fn run() -> io::Result<Value> {
    let args: Vec<_> = env::args_os().collect();
    if args.len() != 3 { return Err(invalid()); }
    let path = Path::new(&args[2]);
    if args[1] == "report" { report(path) }
    else if args[1] == "search" {
        if !fs::symlink_metadata(path)?.file_type().is_dir() { return Err(invalid()); }
        let mut counts = [0u64; 5];
        search_dir(path, &mut counts)?;
        Ok(json!({"files":counts[0], "bytes":counts[1], "lines":counts[2], "matching_lines":counts[3], "matching_files":counts[4]}))
    } else { Err(invalid()) }
}
fn main() {
    match run() {
        Ok(value) => println!("{}", value),
        Err(error) => { eprintln!("{}", error); std::process::exit(1); }
    }
}
