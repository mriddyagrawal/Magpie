use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, PhysicalPosition, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

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

struct SidecarState(Mutex<Option<Child>>);
struct QdrantState(Mutex<Option<Child>>);

// ── Global shortcut: picker + persistence ────────────────────────────────────

fn shortcut_config_path() -> PathBuf {
    app_data_dir().join("shortcut.json")
}

fn load_saved_shortcut() -> Option<String> {
    let content = std::fs::read_to_string(shortcut_config_path()).ok()?;
    let v: serde_json::Value = serde_json::from_str(&content).ok()?;
    v["shortcut"].as_str().map(|s| s.to_owned())
}

fn save_shortcut(label: &str) {
    let path = shortcut_config_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&path, format!(r#"{{"shortcut":"{}"}}"#, label));
}

fn preset_shortcuts() -> Vec<(&'static str, Option<Modifiers>, Code)> {
    vec![
        ("Alt+Space", Some(Modifiers::ALT), Code::Space),
        ("Alt+Q",     Some(Modifiers::ALT), Code::KeyQ),
        ("Ctrl+Space", Some(Modifiers::CONTROL), Code::Space),
        ("Ctrl+Alt+Space", Some(Modifiers::ALT | Modifiers::CONTROL), Code::Space),
    ]
}

/// Try to register a shortcut that toggles the main window. Returns true on success.
fn try_register_shortcut(app: &tauri::AppHandle, modifiers: Option<Modifiers>, code: Code) -> bool {
    let shortcut = Shortcut::new(modifiers, code);
    let handle = app.clone();
    let result = app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, event| {
        if event.state == ShortcutState::Pressed {
            if let Some(window) = handle.get_webview_window("main") {
                let is_visible = window.is_visible().unwrap_or(false);
                if is_visible {
                    let _ = window.hide();
                } else {
                    anchor_spotlight(&window);
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        }
    });
    if result.is_err() { return false; }
    let _ = app.global_shortcut().register(shortcut);
    true
}

/// Runs in a background thread after the event loop is up.
/// Tries the saved/default shortcut; if it fails, offers a preset picker.
fn setup_global_shortcut(app: &tauri::AppHandle) {
    let presets = preset_shortcuts();
    let saved = load_saved_shortcut();

    // Use saved preference, or fall back to Alt+Space.
    let first = saved
        .as_deref()
        .and_then(|lbl| presets.iter().copied().find(|(l, _, _)| *l == lbl))
        .unwrap_or(presets[0]);

    if try_register_shortcut(app, first.1, first.2) {
        if saved.as_deref() != Some(first.0) {
            save_shortcut(first.0);
        }
        return;
    }

    // First choice failed — ask the user to pick an alternative.
    let failed = first.0;
    let alternatives: Vec<_> = presets.iter().copied().filter(|(l, _, _)| *l != failed).collect();

    for (label, modifiers, code) in &alternatives {
        let chose = app
            .dialog()
            .message(format!(
                "{failed} is already in use by another application.\n\n\
                 Use {label} to summon Magpie instead?"
            ))
            .title("Magpie — pick a shortcut")
            .buttons(MessageDialogButtons::YesNo)
            .blocking_show();

        if !chose { continue; }

        if try_register_shortcut(app, *modifiers, *code) {
            save_shortcut(label);
            return;
        }

        // User picked it but it also failed — tell them and try the next.
        app.dialog()
            .message(format!("{label} couldn't be registered either. Trying another option…"))
            .title("Magpie — shortcut unavailable")
            .blocking_show();
    }

    // All options exhausted or user declined everything.
    app.dialog()
        .message(
            "No global shortcut could be registered.\n\n\
             Open Magpie anytime by clicking the system tray icon.",
        )
        .title("Magpie — no shortcut")
        .blocking_show();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // A second instance tried to launch — focus the existing window instead.
            if let Some(window) = app.get_webview_window("main") {
                anchor_spotlight(&window);
                let _ = window.show();
                let _ = window.set_focus();
                let shortcut = load_saved_shortcut().unwrap_or_else(|| "Alt+Space".to_string());
                app.dialog()
                    .message(format!(
                        "Magpie is already running.\n\nYour existing window has been brought \
                         to the front. You can also summon it anytime with {shortcut}."
                    ))
                    .title("Magpie already running")
                    .blocking_show();
            }
        }))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState(Mutex::new(None)))
        .manage(QdrantState(Mutex::new(None)))
        .setup(|app| {
            #[cfg(target_os = "macos")]
            {
                let _ = app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }

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

            let handle = app.handle().clone();

            // Pre-pick ports instantly (just binds + releases a socket) so the
            // window can appear immediately with the port already known — no
            // blocking on qdrant/sidecar startup inside setup().
            let sidecar_port = pick_free_port().unwrap_or(8765);
            let qdrant_port_pre: Option<u16> = if cfg!(not(debug_assertions)) {
                pick_free_port().ok()
            } else {
                None
            };

            // Inject the port and show the window immediately.
            let init_script = format!(
                "window.__MAGPIE_PORT__ = {}; window.__MAGPIE_BOOTING__ = true;",
                sidecar_port
            );
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&init_script);
                anchor_spotlight(&window);
            } else {
                let window = WebviewWindowBuilder::new(&handle, "main", WebviewUrl::default())
                    .title("Magpie")
                    .inner_size(800.0, 96.0)
                    .min_inner_size(800.0, 96.0)
                    .resizable(false)
                    .decorations(false)
                    .transparent(true)
                    .always_on_top(true)
                    .initialization_script(&init_script)
                    .build()?;
                anchor_spotlight(&window);
            }

            // Shortcut registration runs in a background thread so the picker
            // dialog (if Alt+Space is taken) appears after the event loop starts.
            let shortcut_handle = app.handle().clone();
            thread::spawn(move || {
                // Brief pause so the window is visible before any dialog appears.
                thread::sleep(Duration::from_millis(400));
                setup_global_shortcut(&shortcut_handle);
            });

            // System tray icon: left-click toggles window, right-click → Quit.
            // macOS: menu-bar icon (top-right). Windows/Linux: notification-area tray.
            let quit_item = MenuItem::with_id(app, "quit", "Quit Magpie", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&quit_item])?;
            let mut tray_builder = TrayIconBuilder::new()
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .tooltip("Magpie")
                .on_menu_event(|app, event| {
                    if event.id() == "quit" {
                        app.exit(0);
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.hide();
                            } else {
                                anchor_spotlight(&window);
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray_builder = tray_builder.icon(icon.clone());
            }
            tray_builder.build(app)?;

            // Background thread: slow startup (qdrant + sidecar). The window is
            // already visible; the frontend polls /healthz and shows a booting
            // state until the sidecar responds.
            let bg = handle.clone();
            thread::spawn(move || {
                // Release only: start qdrant and wait for it to accept connections.
                let qdrant_port: Option<u16> = if cfg!(not(debug_assertions)) {
                    let port = match qdrant_port_pre {
                        Some(p) => p,
                        None => {
                            eprintln!("[magpie] fatal: could not pre-pick qdrant port");
                            return;
                        }
                    };
                    match spawn_qdrant(&bg, port) {
                        Err(e) => {
                            eprintln!("[magpie] fatal: qdrant failed to start: {e}");
                            bg.dialog()
                                .message(format!(
                                    "Magpie could not start its search database.\n\n\
                                     Error: {e}\n\nPlease reinstall the app."
                                ))
                                .kind(MessageDialogKind::Error)
                                .title("Magpie failed to start")
                                .blocking_show();
                            return;
                        }
                        Ok(child) => {
                            *bg.state::<QdrantState>().0.lock().unwrap() = Some(child);
                            if !wait_for_port(port, 30) {
                                eprintln!("[magpie] fatal: qdrant not ready after 15s");
                                bg.dialog()
                                    .message(
                                        "Magpie's search database took too long to start.\n\n\
                                         Please try relaunching the app.",
                                    )
                                    .kind(MessageDialogKind::Error)
                                    .title("Magpie failed to start")
                                    .blocking_show();
                                return;
                            }
                            Some(port)
                        }
                    }
                } else {
                    None
                };

                // Start the Python sidecar on the pre-picked port.
                match spawn_sidecar(&bg, sidecar_port, qdrant_port) {
                    Err(e) => {
                        eprintln!("[magpie] fatal: sidecar failed to start: {e}");
                        bg.dialog()
                            .message(format!(
                                "Magpie could not start its search backend.\n\n\
                                 Error: {e}\n\nPlease reinstall the app."
                            ))
                            .kind(MessageDialogKind::Error)
                            .title("Magpie failed to start")
                            .blocking_show();
                    }
                    Ok(child) => {
                        *bg.state::<SidecarState>().0.lock().unwrap() = Some(child);
                        eprintln!("[magpie] sidecar started on port {sidecar_port}");
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![hide_window, show_window, pick_folder, pick_file])
        .build(tauri::generate_context!())
        .expect("error building magpie");

    // Kill both child processes when the app actually exits (force-quit,
    // system shutdown, etc.) so they don't linger as orphans.
    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            if let Some(mut child) = app_handle.state::<SidecarState>().0.lock().unwrap().take() {
                eprintln!("[magpie] shutting down sidecar");
                let _ = child.kill();
                let _ = child.wait();
            }
            if let Some(mut child) = app_handle.state::<QdrantState>().0.lock().unwrap().take() {
                eprintln!("[magpie] shutting down qdrant");
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}

// Mirrors Python's platformdirs.user_data_dir("Magpie", "magpie", roaming=False)
// so Rust and Python agree on where app data lives without passing env vars in dev.
fn app_data_dir() -> PathBuf {
    #[cfg(windows)]
    {
        let base = std::env::var("LOCALAPPDATA")
            .unwrap_or_else(|_| "C:\\Users\\Public\\AppData\\Local".to_string());
        PathBuf::from(base).join("magpie").join("Magpie")
    }
    #[cfg(target_os = "macos")]
    {
        let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
        PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("Magpie")
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        let base = std::env::var("XDG_DATA_HOME").unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
            format!("{}/.local/share", home)
        });
        PathBuf::from(base).join("Magpie")
    }
}

fn pick_free_port() -> Result<u16, std::io::Error> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

// Poll until the TCP port accepts a connection or we exhaust attempts (500 ms each).
fn wait_for_port(port: u16, max_attempts: u32) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    for _ in 0..max_attempts {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(500));
    }
    false
}

// Spawn qdrant on a pre-picked port; caller is responsible for storing the child.
fn spawn_qdrant(app: &tauri::AppHandle, port: u16) -> Result<Child, String> {
    let storage = app_data_dir().join("qdrant_storage");
    std::fs::create_dir_all(&storage).map_err(|e| e.to_string())?;

    let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    let bin = resource_dir.join(if cfg!(windows) { "qdrant.exe" } else { "qdrant" });

    let mut cmd = Command::new(&bin);
    cmd.env("QDRANT__STORAGE__STORAGE_PATH", &storage)
        .env("QDRANT__SERVICE__HTTP_PORT", port.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn()
        .map_err(|e| format!("failed to spawn qdrant: {e}"))
}

// Spawn the Python sidecar on a pre-picked port; no stdout blocking.
fn spawn_sidecar(
    app: &tauri::AppHandle,
    port: u16,
    qdrant_port: Option<u16>,
) -> Result<Child, String> {
    let mut cmd = if cfg!(debug_assertions) {
        let mut c = Command::new("uv");
        c.args(["run", "python", "-m", "src.server", "--port", &port.to_string()]);
        c
    } else {
        let resource_dir = app.path().resource_dir().map_err(|e| e.to_string())?;
        let bin =
            resource_dir.join(if cfg!(windows) { "magpie-sidecar.exe" } else { "magpie-sidecar" });
        let mut c = Command::new(&bin);
        c.arg("--port").arg(port.to_string());
        c.env("MAGPIE_DATA_DIR", app_data_dir());
        if let Some(qport) = qdrant_port {
            c.env("QDRANT_PROVIDER", "cloud")
                .env("QDRANT_CLUSTER_ENDPOINT", format!("http://127.0.0.1:{qport}"));
        }
        c
    };

    cmd.stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))
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

#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let (tx, rx) = std::sync::mpsc::channel::<Option<tauri_plugin_dialog::FilePath>>();
    app.dialog()
        .file()
        .set_title("Select folder to index")
        .pick_folder(move |folder| {
            let _ = tx.send(folder);
        });
    tauri::async_runtime::spawn_blocking(move || {
        rx.recv().ok().flatten().and_then(|p| match p {
            tauri_plugin_dialog::FilePath::Path(path) => {
                Some(path.to_string_lossy().into_owned())
            }
            _ => None,
        })
    })
    .await
    .unwrap_or(None)
}

#[tauri::command]
async fn pick_file(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let (tx, rx) = std::sync::mpsc::channel::<Option<tauri_plugin_dialog::FilePath>>();
    app.dialog()
        .file()
        .set_title("Select file to index")
        .pick_file(move |file| {
            let _ = tx.send(file);
        });
    tauri::async_runtime::spawn_blocking(move || {
        rx.recv().ok().flatten().and_then(|p| match p {
            tauri_plugin_dialog::FilePath::Path(path) => {
                Some(path.to_string_lossy().into_owned())
            }
            _ => None,
        })
    })
    .await
    .unwrap_or(None)
}
