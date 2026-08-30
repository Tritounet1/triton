#[cfg(not(debug_assertions))]
use std::sync::Mutex;
#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::ShellExt;

/// Holds the running triton-server sidecar's handle so it can be killed on
/// app exit (see the RunEvent::Exit match below) - None until the sidecar
/// has actually spawned, and taken (leaving None) once killed so a repeat
/// exit event never tries to kill it twice.
#[cfg(not(debug_assertions))]
struct SidecarState(Mutex<Option<CommandChild>>);

/// True if something is already answering on 127.0.0.1:8000. A previous
/// run's sidecar can outlive its parent if the app was force-quit/crashed
/// (SIGKILL bypasses the RunEvent::Exit cleanup below - no way around that
/// from inside the app), which would otherwise make every future launch
/// fail to bind with no obvious cause. Skipping our own spawn in that case
/// means the app just reuses whatever's already serving it instead of
/// erroring - correct whether that's a leftover sidecar or a dev-mode
/// `uv run uvicorn` someone forgot was running.
#[cfg(not(debug_assertions))]
fn port_8000_is_already_serving() -> bool {
    use std::net::{SocketAddr, TcpStream};
    use std::time::Duration;

    let addr: SocketAddr = ([127, 0, 0, 1], 8000).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok()
}

/// Terminates the sidecar, working around a real gap found by testing:
/// CommandChild::kill() always sends SIGKILL, which a PyInstaller onefile
/// build can't do anything with - the tracked PID is only its bootloader
/// (it extracts to a temp dir and runs the real interpreter as its own
/// child process), and SIGKILL gives it no chance to forward the signal
/// before dying, leaving that child running and the port held forever.
/// SIGTERM is different: the bootloader does forward it, so send that
/// first and give it a moment before falling back to the hard kill (in
/// case it's not a PyInstaller onefile binary, or it didn't exit in time).
#[cfg(not(debug_assertions))]
fn terminate_sidecar(child: CommandChild) {
    #[cfg(unix)]
    {
        let pid = child.pid();
        // SAFETY: pid came straight from the child we just spawned/are
        // holding a handle to; SIGTERM on a possibly-already-exited pid
        // just returns ESRCH, nothing unsafe about that outcome.
        unsafe {
            libc::kill(pid as libc::pid_t, libc::SIGTERM);
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    let _ = child.kill();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .setup(|_app| {
            // Dev mode already runs the API separately (the root
            // package.json's "dev" script starts `uv run uvicorn
            // server:app --reload` alongside `tauri dev`) - spawning the
            // sidecar there too would just fight it for port 8000. Only a
            // release build (the actual packaged app, with no separate
            // dev process babysitting the API) needs this.
            #[cfg(not(debug_assertions))]
            {
                if port_8000_is_already_serving() {
                    eprintln!(
                        "[triton-server] something is already listening on 127.0.0.1:8000 \
                         (a leftover sidecar, or a dev server) - reusing it instead of \
                         spawning a new one"
                    );
                    return Ok(());
                }

                let (mut rx, child) = match _app.shell().sidecar("triton-server") {
                    Ok(cmd) => match cmd.spawn() {
                        Ok(spawned) => spawned,
                        Err(e) => {
                            eprintln!("failed to spawn triton-server sidecar: {e}");
                            _app.manage(SidecarState(Mutex::new(None)));
                            return Ok(());
                        }
                    },
                    Err(e) => {
                        eprintln!("failed to prepare triton-server sidecar command: {e}");
                        _app.manage(SidecarState(Mutex::new(None)));
                        return Ok(());
                    }
                };

                _app.manage(SidecarState(Mutex::new(Some(child))));

                // relay the sidecar's own stdout/stderr into this
                // process's - a startup crash (e.g. a missing/invalid
                // OpenRouter key on a fresh install, see api.py) is then
                // visible in the app's own logs instead of silently lost.
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                print!("[triton-server] {}", String::from_utf8_lossy(&line));
                            }
                            CommandEvent::Stderr(line) => {
                                eprint!("[triton-server] {}", String::from_utf8_lossy(&line));
                            }
                            CommandEvent::Error(err) => {
                                eprintln!("[triton-server] error: {err}");
                            }
                            CommandEvent::Terminated(payload) => {
                                eprintln!("[triton-server] exited: {payload:?}");
                            }
                            _ => {}
                        }
                    }
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            #[cfg(not(debug_assertions))]
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        terminate_sidecar(child);
                    }
                }
            }
            #[cfg(debug_assertions)]
            let _ = (app_handle, event);
        });
}
