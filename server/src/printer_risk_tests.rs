use super::*;
use std::{
    os::fd::FromRawFd,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
        mpsc,
    },
    thread,
};

struct FakePrinter {
    config: Config,
    stop: Option<mpsc::Sender<()>>,
    worker: Option<thread::JoinHandle<()>>,
    printed: Arc<AtomicUsize>,
}
impl Drop for FakePrinter {
    fn drop(&mut self) {
        drop(self.stop.take());
        self.worker.take().unwrap().join().unwrap();
    }
}
impl FakePrinter {
    fn new(config: &Config, color: u8, fail_print: bool) -> Self {
        let (mut master, mut slave) = (-1, -1);
        let mut name = [0 as libc::c_char; 256];
        unsafe {
            assert_eq!(
                libc::openpty(
                    &mut master,
                    &mut slave,
                    name.as_mut_ptr(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut()
                ),
                0
            );
            let mut attrs = std::mem::zeroed();
            assert_eq!(libc::tcgetattr(slave, &mut attrs), 0);
            libc::cfmakeraw(&mut attrs);
            assert_eq!(libc::tcsetattr(slave, libc::TCSANOW, &attrs), 0);
            libc::fcntl(master, libc::F_SETFL, libc::O_NONBLOCK);
        }
        let mut config = config.clone();
        config.printer = format!(
            "file://{}",
            unsafe { std::ffi::CStr::from_ptr(name.as_ptr()) }
                .to_str()
                .unwrap()
        );
        let (mut master, slave) = unsafe { (File::from_raw_fd(master), File::from_raw_fd(slave)) };
        let (tx, rx) = mpsc::channel();
        let printed = Arc::new(AtomicUsize::new(0));
        let counter = printed.clone();
        let worker = thread::spawn(move || {
            let _slave = slave;
            let mut input = Vec::new();
            let mut queried = false;
            let deadline = Instant::now() + Duration::from_secs(15);
            loop {
                if rx.try_recv() != Err(mpsc::TryRecvError::Empty) {
                    break;
                }
                assert!(Instant::now() < deadline, "Fake printer was not released");
                let mut bytes = [0; 16384];
                match master.read(&mut bytes) {
                    Ok(n) if n > 0 => input.extend_from_slice(&bytes[..n]),
                    Ok(_) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(e) => panic!("{e}"),
                }
                if !queried && input.len() >= 3 {
                    assert_eq!(&input[..3], b"\x1biS");
                    input.drain(..3);
                    let mut p = vec![0; 32];
                    p[..6].copy_from_slice(&[0x80, 0x20, 0x42, 0x34, 0x38, 0x30]);
                    p[10] = 62;
                    p[11] = 10;
                    p[25] = color;
                    master.write_all(&p).unwrap();
                    queried = true;
                }
                if queried && !input.is_empty() && input.last() == Some(&0x1a) {
                    counter.fetch_add(1, Ordering::SeqCst);
                    let mut p = vec![0; 32];
                    p[..6].copy_from_slice(&[0x80, 0x20, 0x42, 0x34, 0x38, 0x30]);
                    p[18] = if fail_print { 2 } else { 1 };
                    p[8] = u8::from(fail_print);
                    master.write_all(&p).unwrap();
                    if !fail_print {
                        p[18] = 6;
                        master.write_all(&p).unwrap();
                    }
                    input.clear();
                }
                thread::sleep(Duration::from_millis(2));
            }
        });
        Self {
            config,
            stop: Some(tx),
            worker: Some(worker),
            printed,
        }
    }
}
fn config(dir: &std::path::Path) -> Config {
    Config {
        data_dir: dir.into(),
        labels_dir: dir.join("labels"),
        ..Config::default()
    }
}
fn draft(fonts: &crate::fonts::Fonts) -> Value {
    json!({"content":{"kind":"text","text":"Test"},"sizeId":"62","orientation":"standard","font":fonts.default_font(),"fontSize":12,"align":"left","color":"black","margin":0,"highRes":false})
}
#[test]
fn unknown_red_requires_confirmation_and_never_allows_bulk_override() {
    for (batch, confirmed, allowed) in [
        (false, false, false),
        (false, true, true),
        (true, false, false),
        (true, true, false),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let fake = FakePrinter::new(&config(dir.path()), 0, false);
        assert_eq!(
            check_media(&fake.config, "62red", batch, confirmed).is_ok(),
            allowed
        );
        assert_eq!(fake.printed.load(Ordering::SeqCst), 0);
    }
    let dir = tempfile::tempdir().unwrap();
    let fake = FakePrinter::new(&config(dir.path()), 1, false);
    assert!(check_media(&fake.config, "62red", false, true).is_err());
}
#[test]
fn failed_sent_batch_is_recorded_and_retry_cannot_send_again() {
    let dir = tempfile::tempdir().unwrap();
    let cfg = config(dir.path());
    let fonts = crate::fonts::Fonts::load(&cfg).unwrap();
    let fake = FakePrinter::new(&cfg, 1, true);
    let job = uuid::Uuid::new_v4().to_string();
    let value = draft(&fonts);
    let drafts = [&value];
    let error = print_drafts(&fake.config, &fonts, &drafts, "each", Some(&job), false).unwrap_err();
    assert_eq!(error.downcast_ref::<PrintError>().unwrap().status, 502);
    assert_eq!(fake.printed.load(Ordering::SeqCst), 1);
    let record: Value = serde_json::from_slice(
        &fs::read(dir.path().join("bulk-jobs").join(format!("{job}.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(record, json!({"state":"submitted","count":1}));
    let error = print_drafts(&fake.config, &fonts, &drafts, "each", Some(&job), false).unwrap_err();
    assert_eq!(error.downcast_ref::<PrintError>().unwrap().status, 409);
    assert_eq!(fake.printed.load(Ordering::SeqCst), 1);
}
#[test]
fn simulation_cut_end_cuts_only_final_page() {
    let dir = tempfile::tempdir().unwrap();
    let cfg = config(dir.path());
    let fonts = crate::fonts::Fonts::load(&cfg).unwrap();
    let result = print_drafts(
        &cfg,
        &fonts,
        &[&draft(&fonts), &draft(&fonts)],
        "end",
        None,
        false,
    )
    .unwrap();
    assert_eq!(result["copies"], 2);
    let binaries: Vec<_> = fs::read_dir(dir.path().join("simulated_labels"))
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "bin"))
        .map(|p| fs::read(p).unwrap())
        .collect();
    assert_eq!(binaries.len(), 2);
    let cut_flags: Vec<_> = binaries
        .iter()
        .map(|b| b.windows(4).find(|w| w.starts_with(b"\x1biK")).unwrap()[3] & 8)
        .collect();
    assert_eq!(cut_flags.iter().filter(|flag| **flag == 8).count(), 1);
    assert_eq!(cut_flags.iter().filter(|flag| **flag == 0).count(), 1);
}
#[test]
fn oversized_batch_sends_nothing_and_does_not_consume_job_id() {
    let dir = tempfile::tempdir().unwrap();
    let mut cfg = config(dir.path());
    cfg.model = "QL-1100".into();
    let fonts = crate::fonts::Fonts::load(&cfg).unwrap();
    let mut d = draft(&fonts);
    d["sizeId"] = "102x152".into();
    d["highRes"] = true.into();
    let job = uuid::Uuid::new_v4().to_string();
    let error = print_drafts(&cfg, &fonts, &[&d; 9], "each", Some(&job), false).unwrap_err();
    assert!(error.to_string().contains("Batch images are too large"));
    assert!(!dir.path().join("simulated_labels").exists());
    assert!(
        !dir.path()
            .join("bulk-jobs")
            .join(format!("{job}.json"))
            .exists()
    );
}

#[test]
fn one_hundred_high_resolution_copies_reuse_a_single_rendered_page() {
    let dir = tempfile::tempdir().unwrap();
    let cfg = config(dir.path());
    let fonts = crate::fonts::Fonts::load(&cfg).unwrap();
    let mut document = draft(&fonts);
    document["sizeId"] = "62x100".into();
    document["highRes"] = true.into();
    let result = print_copies(&cfg, &fonts, &document, 100, "end", false).unwrap();
    assert_eq!(result["copies"], 100);
    let binaries: Vec<_> = fs::read_dir(dir.path().join("simulated_labels"))
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "bin"))
        .collect();
    assert_eq!(binaries.len(), 100);
    let cuts = binaries
        .iter()
        .filter(|p| {
            fs::read(p)
                .unwrap()
                .windows(4)
                .any(|w| w.starts_with(b"\x1biK") && w[3] & 8 != 0)
        })
        .count();
    assert_eq!(cuts, 1);
}
