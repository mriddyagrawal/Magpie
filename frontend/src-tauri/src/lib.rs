use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, PhysicalPosition, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
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

            // Release only: spawn the bundled Qdrant binary and wait for it.
            // Dev mode: run `just qdrant-up` separately — no bundled binary present.
            let qdrant_port: Option<u16> = if cfg!(not(debug_assertions)) {
                match spawn_qdrant(&handle, app.state::<QdrantState>()) {
                    Err(e) => {
                        eprintln!("[magpie] fatal: qdrant failed to start: {e}");
                        handle
                            .dialog()
                            .message(format!(
                                "Magpie could not start its search database.\n\n\
                                 Error: {e}\n\nPlease reinstall the app."
                            ))
                            .kind(MessageDialogKind::Error)
                            .title("Magpie failed to start")
                            .blocking_show();
                        return Err(e.into());
                    }
                    Ok(port) => {
                        if !wait_for_port(port, 30) {
                            eprintln!("[magpie] fatal: qdrant port {port} not ready after 15s");
                            handle
                                .dialog()
                                .message(
                                    "Magpie's search database took too long to start.\n\n\
                                     Please try relaunching the app.",
                                )
                                .kind(MessageDialogKind::Error)
                                .title("Magpie failed to start")
                                .blocking_show();
                            return Err("qdrant not ready".into());
                        }
                        Some(port)
                    }
                }
            } else {
                None
            };

            // Spawn Python sidecar (dev: uv run; release: PyInstaller bundle).
            let port = match spawn_sidecar(&handle, app.state::<SidecarState>(), qdrant_port) {
                Err(e) => {
                    eprintln!("[magpie] fatal: sidecar failed to start: {e}");
                    handle
                        .dialog()
                        .message(format!(
                            "Magpie could not start its search backend.\n\n\
                             Error: {e}\n\nPlease reinstall the app."
                        ))
                        .kind(MessageDialogKind::Error)
                        .title("Magpie failed to start")
                        .blocking_show();
                    return Err(e.into());
                }
                Ok(p) => p,
            };

            let init_script = format!("window.__MAGPIE_PORT__ = {};", port);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&init_script);
            } else {
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

            if let Some(window) = app.get_webview_window("main") {
                anchor_spotlight(&window);
            }

            let shortcut = Shortcut::new(Some(Modifiers::ALT), Code::Space);
            let handle_for_shortcut = app.handle().clone();
            if let Err(e) = app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, event| {
                if event.state == ShortcutState::Pressed {
                    if let Some(window) = handle_for_shortcut.get_webview_window("main") {
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
            }) {
                eprintln!("[magpie] ⌥Space handler setup failed: {e}");
            } else if let Err(e) = app.global_shortcut().register(shortcut) {
                eprintln!("[magpie] ⌥Space register failed: {e} (global summon disabled)");
            }

            // System tray icon: left-click toggles window, right-click → Quit.
            // macOS: menu-bar icon (top-right). Windows/Linux: notification-area tray.
            let quit_item = MenuItem::with_id(app, "quit", "Quit Magpie", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&quit_item])?;
            let mut tray_builder = TrayIconBuilder::new()
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .tooltip("Magpie — Alt+Space to summon")
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

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![hide_window, show_window])
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

fn spawn_qdrant(
    app: &tauri::AppHandle,
    state: tauri::State<'_, QdrantState>,
) -> Result<u16, Box<dyn std::error::Error>> {
    let port = pick_free_port()?;
    let storage = app_data_dir().join("qdrant_storage");
    std::fs::create_dir_all(&storage)?;

    let resource_dir = app.path().resource_dir()?;
    let bin = resource_dir.join(if cfg!(windows) { "qdrant.exe" } else { "qdrant" });

    let child = Command::new(&bin)
        .env("QDRANT__STORAGE__STORAGE_PATH", &storage)
        .env("QDRANT__SERVICE__HTTP_PORT", port.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;

    *state.0.lock().unwrap() = Some(child);
    Ok(port)
}

fn spawn_sidecar(
    app: &tauri::AppHandle,
    state: tauri::State<'_, SidecarState>,
    qdrant_port: Option<u16>,
) -> Result<u16, Box<dyn std::error::Error>> {
    let mut cmd = if cfg!(debug_assertions) {
        // Dev: uv manages the Python env — no sidecar binary needed.
        let mut c = Command::new("uv");
        c.args(["run", "python", "-m", "src.server"]);
        c
    } else {
        // Release: run the PyInstaller-compiled binary from the app bundle.
        let resource_dir = app.path().resource_dir()?;
        let bin =
            resource_dir.join(if cfg!(windows) { "magpie-sidecar.exe" } else { "magpie-sidecar" });
        let mut c = Command::new(&bin);
        // Pin the data dir so Python and Qdrant use the same location.
        c.env("MAGPIE_DATA_DIR", app_data_dir());
        if let Some(port) = qdrant_port {
            c.env("QDRANT_PROVIDER", "cloud")
                .env("QDRANT_CLUSTER_ENDPOINT", format!("http://127.0.0.1:{port}"));
        }
        c
    };

    let mut child = cmd.stdout(Stdio::piped()).stderr(Stdio::inherit()).spawn()?;

    let stdout = child.stdout.take().ok_or("sidecar has no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut first_line = String::new();
    reader.read_line(&mut first_line)?;

    let port: u16 = first_line
        .trim()
        .strip_prefix("MAGPIE_PORT=")
        .ok_or_else(|| format!("unexpected sidecar greeting: {:?}", first_line))?
        .parse()?;

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
