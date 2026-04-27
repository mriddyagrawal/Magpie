use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use tauri::{Manager, PhysicalPosition, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Spotlight-style: window appears at the same anchor every summon, regardless
/// of where it was previously dragged. ~22% from the top, horizontally centered
/// on the monitor that contains the window (or the primary monitor).
fn anchor_spotlight(window: &WebviewWindow) {
    let monitor = match window.current_monitor() {
        Ok(Some(m)) => m,
        _ => match window.primary_monitor() {
            Ok(Some(m)) => m,
            _ => return,
        },
    };
    let screen = monitor.size();
    let win_size = match window.outer_size() {
        Ok(s) => s,
        Err(_) => return,
    };
    let x = ((screen.width as i32) - (win_size.width as i32)) / 2;
    let y = ((screen.height as f64) * 0.22) as i32;
    let _ = window.set_position(PhysicalPosition::new(x.max(0), y.max(0)));
}

/// Child process handle for the Python sidecar. Held in app state so we can
/// shut it down cleanly on app exit.
struct SidecarState(Mutex<Option<Child>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            // macOS: run as an "accessory" app — no dock icon, no menu bar,
            // no ⌘-Tab entry. Matches Spotlight's behaviour: summoned via the
            // global shortcut, hidden otherwise.
            #[cfg(target_os = "macos")]
            {
                let _ = app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }

            // Apply macOS vibrancy (full-window blur) to make the transparent
            // window feel native. FullScreenUI (not HudWindow) is what
            // Spotlight / Raycast / Alfred use — HudWindow renders with
            // square bottom corners on macOS regardless of the radius arg
            // (legacy HUD-panel behavior). FullScreenUI honors all 4 corners.
            #[cfg(target_os = "macos")]
            {
                use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial, NSVisualEffectState};
                if let Some(window) = app.get_webview_window("main") {
                    let _ = apply_vibrancy(
                        &window,
                        NSVisualEffectMaterial::FullScreenUI,
                        Some(NSVisualEffectState::Active),
                        Some(18.0),
                    );
                }
            }

            // Spawn Python sidecar, read MAGPIE_PORT from its first stdout line,
            // then inject it into the webview as window.__MAGPIE_PORT__.
            let handle = app.handle().clone();
            let sidecar_state = app.state::<SidecarState>();
            let port = spawn_sidecar(sidecar_state)?;
            // Rebuild the webview window *after* we know the port, so the init
            // script can inject it deterministically.
            if let Some(_existing) = app.get_webview_window("main") {
                let init_script = format!("window.__MAGPIE_PORT__ = {};", port);
                // Inject after-the-fact via eval.
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.eval(&init_script);
                }
            } else {
                let init_script = format!("window.__MAGPIE_PORT__ = {};", port);
                let _ = WebviewWindowBuilder::new(&handle, "main", WebviewUrl::default())
                    .title("Magpie")
                    .inner_size(800.0, 96.0)
                    .min_inner_size(800.0, 96.0)
                    .resizable(false)
                    .decorations(false)
                    .transparent(true)
                    .always_on_top(true)
                    .initialization_script(&init_script)
                    .build()?;
            }

            // Position the window Spotlight-style on first launch. The ⌥Space
            // handler re-anchors on every subsequent summon so user-drag never
            // sticks across hides — matches Spotlight / Raycast / Alfred.
            if let Some(window) = app.get_webview_window("main") {
                anchor_spotlight(&window);
            }

            // Register the global shortcut: ⌥Space. Toggles the window on each
            // press (hide if visible, show+focus if hidden) so the user can
            // dismiss the same way they summoned it. Non-fatal on failure.
            let shortcut = Shortcut::new(Some(Modifiers::ALT), Code::Space);
            let handle_for_shortcut = app.handle().clone();
            if let Err(e) = app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, event| {
                if event.state == ShortcutState::Pressed {
                    if let Some(window) = handle_for_shortcut.get_webview_window("main") {
                        let is_visible = window.is_visible().unwrap_or(false);
                        if is_visible {
                            let _ = window.hide();
                        } else {
                            // Re-anchor before showing so the window always
                            // appears in the same Spotlight spot, even if the
                            // user dragged it around in a previous session.
                            anchor_spotlight(&window);
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                }
            }) {
                eprintln!("[magpie] ⌥Space handler setup failed: {e}");
            } else if let Err(e) = app.global_shortcut().register(shortcut) {
                eprintln!("[magpie] ⌥Space register failed: {e} (window still works; global summon disabled)");
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            // When the main window is told to close via keyboard / × button,
            // we hide it instead so the global shortcut can resurrect it.
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![hide_window, show_window])
        .run(tauri::generate_context!())
        .expect("error while running magpie");
}

fn spawn_sidecar(state: tauri::State<'_, SidecarState>) -> Result<u16, Box<dyn std::error::Error>> {
    // `uv run python3 -m src.server` picks a free port and prints MAGPIE_PORT=<n>
    // on the first line of stdout. We block on that line then return.
    let mut child = Command::new("uv")
        .args(["run", "python3", "-m", "src.server"])
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;

    let stdout = child.stdout.take().ok_or("sidecar has no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut first_line = String::new();
    reader.read_line(&mut first_line)?;

    let port: u16 = first_line
        .trim()
        .strip_prefix("MAGPIE_PORT=")
        .ok_or_else(|| format!("unexpected sidecar greeting: {:?}", first_line))?
        .parse()?;

    // Keep draining stdout in the background so the sidecar's pipe doesn't
    // fill up and stall. Lines after the first are logged, not parsed.
    thread::spawn(move || {
        let mut line = String::new();
        while reader.read_line(&mut line).unwrap_or(0) > 0 {
            eprint!("[magpie sidecar] {}", line);
            line.clear();
        }
    });

    *state.0.lock().unwrap() = Some(child);
    Ok(port)
}

#[tauri::command]
fn hide_window(window: tauri::Window) {
    let _ = window.hide();
}

#[tauri::command]
fn show_window(window: tauri::Window) {
    let _ = window.show();
    let _ = window.set_focus();
}
