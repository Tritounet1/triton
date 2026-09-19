use std::sync::{Arc, Mutex};
#[cfg(not(debug_assertions))]
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::ShellExt;
#[cfg(not(debug_assertions))]
use uuid::Uuid;

/// Held in memory only. The token is released to the trusted WebView after
/// the sidecar that received it over stdin reports it has started, so an
/// unrelated process on port 8000 never receives a token-bearing request.
#[derive(Clone)]
struct LocalApiTokenState(Arc<Mutex<Option<String>>>);

#[tauri::command]
fn local_api_token(state: tauri::State<'_, LocalApiTokenState>) -> Option<String> {
    state.0.lock().unwrap().clone()
}

/// Holds the running triton-server sidecar's handle so it can be killed on
/// app exit (see the RunEvent::Exit match below) - None until the sidecar
/// has actually spawned, and taken (leaving None) once killed so a repeat
/// exit event never tries to kill it twice.
#[cfg(not(debug_assertions))]
struct SidecarState(Mutex<Option<CommandChild>>);

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
    let api_token_state = LocalApiTokenState(Arc::new(Mutex::new(None)));
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_shell::init())
        .manage(api_token_state.clone())
        .invoke_handler(tauri::generate_handler![local_api_token])
        .setup(move |_app| {
            // Dev mode already runs the API separately (the root
            // package.json's "dev" script starts `uv run uvicorn
            // server:app --reload` alongside `tauri dev`) - spawning the
            // sidecar there too would just fight it for port 8000. Only a
            // release build (the actual packaged app, with no separate
            // dev process babysitting the API) needs this.
            #[cfg(not(debug_assertions))]
            {
                let token = Uuid::new_v4().to_string();
                let (mut rx, mut child) = match _app.shell().sidecar("triton-server") {
                    Ok(cmd) => match cmd.arg("--local-api-token-stdin").spawn() {
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

                if let Err(e) = child.write(format!("{token}\n").as_bytes()) {
                    eprintln!("failed to send the local API token to triton-server: {e}");
                    terminate_sidecar(child);
                    _app.manage(SidecarState(Mutex::new(None)));
                    return Ok(());
                }

                _app.manage(SidecarState(Mutex::new(Some(child))));

                // relay the sidecar's own stdout/stderr into this
                // process's - a startup crash (e.g. a missing/invalid
                // OpenRouter key on a fresh install, see api.py) is then
                // visible in the app's own logs instead of silently lost.
                let token_state = api_token_state.clone();
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                let text = String::from_utf8_lossy(&line);
                                if text.trim() == "TRITON_SIDECAR_READY" {
                                    *token_state.0.lock().unwrap() = Some(token.clone());
                                } else {
                                    print!("[triton-server] {text}");
                                }
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
