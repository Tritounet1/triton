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
                        let _ = child.kill();
                    }
                }
            }
            #[cfg(debug_assertions)]
            let _ = (app_handle, event);
        });
}
