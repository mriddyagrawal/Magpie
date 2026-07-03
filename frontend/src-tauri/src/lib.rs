use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::menu::{Menu, MenuItem};
#[cfg(target_os = "macos")]
use tauri::menu::Submenu;
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, PhysicalPosition, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_autostart::{ManagerExt as AutostartManagerExt, MacosLauncher};
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

// Process-lifetime flag: true once `anchor_spotlight_once` has run. The
// atomic dies with the process so Cmd-Q → relaunch re-anchors fresh,
// while hide → resummon within the same session preserves whatever
// position the user dragged the window to. See Specs/window_lifecycle.md.
static SPOTLIGHT_ANCHORED: AtomicBool = AtomicBool::new(false);

// Anchor the window to the Spotlight position only the first time this
// fires per process. All show / re-summon paths must call this — bare
// `anchor_spotlight()` calls override the user's dragged position on
// every summon, which was the v0 design and is no longer wanted.
fn anchor_spotlight_once(window: &WebviewWindow) {
    if !SPOTLIGHT_ANCHORED.swap(true, Ordering::Relaxed) {
        anchor_spotlight(window);
    }
}

struct SidecarState(Mutex<Option<Child>>);
struct QdrantState(Mutex<Option<Child>>);

/// The port the Python sidecar is listening on. Picked once in setup()
/// and read by the macOS menu / tray menu handlers when opening the
/// settings window (those callers don't have the port as a function
/// arg the way the frontend's invoke does).
struct SidecarPort(Mutex<u16>);

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
                    anchor_spotlight_once(&window);
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
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            // A second instance tried to launch. Two flows:
            //   - `magpie --toggle` (or just `--toggle` as second-instance
            //     argv): toggle window visibility silently. Useful for
            //     autostart-launching a hidden Magpie that the user can
            //     later summon by re-running the launcher binary, or for
            //     scripted toggle from outside the app.
            //   - Anything else: focus the existing window and show the
            //     "already running" dialog.
            let is_toggle = argv.iter().any(|s| s == "--toggle" || s == "toggle");
            if let Some(window) = app.get_webview_window("main") {
                if is_toggle {
                    let is_visible = window.is_visible().unwrap_or(false);
                    if is_visible {
                        let _ = window.hide();
                    } else {
                        anchor_spotlight_once(&window);
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                    return;
                }
                anchor_spotlight_once(&window);
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
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        // Plan #10 P10-6 — auto-updater. The frontend triggers checks via
        // `check()` from @tauri-apps/plugin-updater (see frontend/src/auto-updater.ts).
        // Endpoint + public key live in tauri.conf.json's plugins.updater block.
        .plugin(tauri_plugin_updater::Builder::new().build())
        // process plugin is the Rust counterpart that backs `relaunch()` from
        // @tauri-apps/plugin-process — used after the updater installs to bring
        // the new version up. Without this, JS calls error at runtime.
        .plugin(tauri_plugin_process::init())
        .manage(SidecarState(Mutex::new(None)))
        .manage(QdrantState(Mutex::new(None)))
        .manage(SidecarPort(Mutex::new(0)))
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
            *app.state::<SidecarPort>().0.lock().unwrap() = sidecar_port;
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
                anchor_spotlight_once(&window);
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
                anchor_spotlight_once(&window);
            }

            // Shortcut registration runs in a background thread so the picker
            // dialog (if Alt+Space is taken) appears after the event loop starts.
            let shortcut_handle = app.handle().clone();
            thread::spawn(move || {
                // Brief pause so the window is visible before any dialog appears.
                thread::sleep(Duration::from_millis(400));
                setup_global_shortcut(&shortcut_handle);
            });

            // System tray icon: left-click toggles window, right-click →
            // Settings… / Quit. macOS: menu-bar icon (top-right). Windows/
            // Linux: notification-area tray. Same menu on all three platforms.
            // Always built — the "Show in menu bar" Settings toggle was
            // removed 2026-05-08 to keep the surface simple.
            let settings_tray_item = MenuItem::with_id(
                app, "tray_settings", "Settings…", true, None::<&str>,
            )?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Magpie", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&settings_tray_item, &quit_item])?;

            // macOS application menu (the menubar at the top of the screen).
            // The "Settings…" item gets `Cmd ,` as its accelerator — the
            // standard macOS preferences shortcut. On Windows + Linux the
            // ask bar's frontend listens for `Ctrl ,` instead (see
            // useSettingsShortcut hook in MagpieWindow.tsx); the native
            // app-menu pattern only applies on macOS.
            #[cfg(target_os = "macos")]
            {
                use tauri::menu::PredefinedMenuItem;
                let app_settings_item = MenuItem::with_id(
                    app, "menu_settings", "Settings…", true, Some("Cmd+,"),
                )?;
                let magpie_menu = Submenu::with_items(
                    app, "Magpie", true, &[&app_settings_item],
                )?;
                // Edit menu. Without it, the standard Cmd+C / Cmd+V / Cmd+X /
                // Cmd+A accelerators never reach the webview on macOS, so copy,
                // cut, paste, and select-all silently do nothing in the ask bar.
                // These PredefinedMenuItems register the OS-standard accelerators
                // and route them to the focused text field. Windows/Linux get
                // these from the webview natively, so this menu is macOS-only.
                let edit_menu = Submenu::with_items(
                    app,
                    "Edit",
                    true,
                    &[
                        &PredefinedMenuItem::undo(app, None)?,
                        &PredefinedMenuItem::redo(app, None)?,
                        &PredefinedMenuItem::separator(app)?,
                        &PredefinedMenuItem::cut(app, None)?,
                        &PredefinedMenuItem::copy(app, None)?,
                        &PredefinedMenuItem::paste(app, None)?,
                        &PredefinedMenuItem::select_all(app, None)?,
                    ],
                )?;
                let app_menu = Menu::with_items(app, &[&magpie_menu, &edit_menu])?;
                app.set_menu(app_menu)?;
                let app_handle_for_menu = app.handle().clone();
                app.on_menu_event(move |_app, event| {
                    if event.id() == "menu_settings" {
                        open_settings_internal(&app_handle_for_menu, None);
                    }
                });
            }

            let mut tray_builder = TrayIconBuilder::new()
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .tooltip("Magpie")
                .on_menu_event(|app, event| {
                    if event.id() == "tray_settings" {
                        open_settings_internal(app, None);
                    } else if event.id() == "quit" {
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
                                anchor_spotlight_once(&window);
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
        .invoke_handler(tauri::generate_handler![
            hide_window,
            show_window,
            toggle_main_window,
            pick_folder,
            pick_file,
            open_settings,
            open_settings_with_action,
            get_autostart,
            set_autostart,
        ])
        .build(tauri::generate_context!())
        .expect("error building magpie");

    // Kill both child processes when the app actually exits (force-quit,
    // system shutdown, etc.) so they don't linger as orphans.
    app.run(|app_handle, event| {
        match &event {
            tauri::RunEvent::Exit => {
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
            // macOS-specific: a "reopen" fires when the user activates an
            // already-running app via Spotlight, the Dock (if we had a Dock
            // icon), or `open -a Magpie` from the shell. With
            // ActivationPolicy::Accessory we have no Dock icon, but Spotlight
            // can still reach us. Honor it as a summon — same anchor + show
            // + focus the global shortcut does.
            #[cfg(target_os = "macos")]
            tauri::RunEvent::Reopen { has_visible_windows, .. } => {
                if !has_visible_windows {
                    if let Some(window) = app_handle.get_webview_window("main") {
                        anchor_spotlight_once(&window);
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            _ => {}
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
        // Dev mode: spawn the Python sidecar via `uv run`. The cwd
        // *must* be the repo root — `python -m src.server` relies on
        // `src/` being importable, and at runtime Tauri's cwd is
        // `frontend/src-tauri/` (where cargo run lives). Without
        // current_dir(), the user sees the ask bar stuck on
        // "Starting Magpie…" indefinitely because the sidecar
        // crashes on import and /healthz never comes up.
        //
        // The repo root is computed at compile time from
        // CARGO_MANIFEST_DIR (= frontend/src-tauri/) by walking up
        // two directories. This hardcodes the layout, but dev mode
        // always runs from this exact path; production uses the
        // bundled PyInstaller binary which doesn't go through this
        // branch at all.
        let repo_root = concat!(env!("CARGO_MANIFEST_DIR"), "/../..");
        let mut c = Command::new("uv");
        c.current_dir(repo_root);
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

/// Open the settings window. Optionally inject a one-shot deep-link
/// action that the SettingsWindow component reads on mount via
/// `window.__MAGPIE_SETTINGS_ACTION__`. Used by the not-found CTA in the
/// ask bar (`action="add-folder"` triggers the folder picker on open)
/// and by the macOS menu / tray menu (`action=None` is just an open).
fn open_settings_internal(app: &tauri::AppHandle, action: Option<&str>) {
    // Read the sidecar port from app state — set once in setup() when
    // the port is picked. Falls back to 8765 (the dev-default) if state
    // isn't initialized yet (degenerate race during boot).
    let port: u16 = app
        .try_state::<SidecarPort>()
        .map(|s| *s.0.lock().unwrap())
        .filter(|p| *p != 0)
        .unwrap_or(8765);
    let action_js = action
        .map(|a| format!("window.__MAGPIE_SETTINGS_ACTION__ = '{}';", escape_for_js(a)))
        .unwrap_or_default();
    let init = format!(
        "window.__MAGPIE_PORT__ = {}; window.__MAGPIE_WINDOW_TYPE__ = 'settings'; {}",
        port, action_js
    );
    if let Some(win) = app.get_webview_window("settings") {
        // Already open: re-inject the action so the SettingsWindow
        // component picks it up on its next effect tick. Eval is safe
        // since `action` is whitelisted at the command boundary.
        let _ = win.eval(&init);
        let _ = win.show();
        let _ = win.set_focus();
        return;
    }
    // Build the window from a BACKGROUND thread — never the main thread.
    //
    // On Windows, every caller of this function (the `open_settings`
    // command, the tray-menu click, the macOS app menu) runs on the main
    // thread. Creating a webview window there deadlocks (wry#583): the
    // native window frame gets created, but WebView2 initialization needs
    // the main thread to pump messages — and the main thread is blocked
    // inside this very call. Symptom: a permanently white, unclosable
    // "Magpie Settings" window with no web content, no console, no
    // devtools. macOS's WKWebView initializes differently and never hit
    // this, which is why settings worked on Mac and not on Windows.
    //
    // From a background thread, `.build()` safely dispatches the work to
    // the (free) main event loop on both platforms.
    let app = app.clone();
    std::thread::spawn(move || {
        let built = WebviewWindowBuilder::new(&app, "settings", WebviewUrl::App("settings.html".into()))
            .title("Magpie Settings")
            // Sized for the new three-tab layout (Specs/UI/settings_window.md).
            // The mockups assume ~720×640 to comfortably show the sidebar +
            // main content area; min 620×560 keeps the data tab's folder
            // rows readable when the user shrinks the window.
            .inner_size(720.0, 640.0)
            .min_inner_size(620.0, 560.0)
            .resizable(true)
            .decorations(true)
            .transparent(false)
            .always_on_top(false)
            .initialization_script(&init)
            .build();
        if let Err(e) = &built {
            eprintln!("[magpie] settings window failed to open: {e}");
        }
    });
}

/// Whitelist for action strings injected into JS init scripts. Keeps
/// the frontend's contract narrow — adding a new action is a
/// deliberate edit here, not a freeform string passed through.
fn escape_for_js(action: &str) -> String {
    // Allow only known actions. Reject everything else.
    match action {
        "add-folder" => action.to_string(),
        _ => String::new(),
    }
}

#[tauri::command]
fn open_settings(app: tauri::AppHandle, port: u16) {
    let _ = port; // Port is read from the main window; the explicit arg
                  // is preserved for backward compat with the existing
                  // frontend caller.
    open_settings_internal(&app, None);
}

#[tauri::command]
fn open_settings_with_action(app: tauri::AppHandle, action: String) {
    open_settings_internal(&app, Some(&action));
}

#[tauri::command]
fn hide_window(window: tauri::Window) {
    let _ = window.hide();
}

/// Toggle main-window visibility. Same logic as the Rust-registered
/// global-shortcut callback — used by:
///   - the JS-registered global-shortcut callback after the user
///     changes the binding via Settings (runtime re-register flow,
///     pattern borrowed from Kunkun's frontend hotkey.ts);
///   - the single-instance handler when launched with `--toggle`
///     (autostart-with-hidden-window pattern);
///   - any future trigger that wants the spotlight toggle behavior.
#[tauri::command]
fn toggle_main_window(app: tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let is_visible = window.is_visible().unwrap_or(false);
        if is_visible {
            let _ = window.hide();
        } else {
            anchor_spotlight_once(&window);
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}

// Launch-at-login wiring. The Settings → Shortcut & App tab's
// "Launch at login" toggle calls these. The plugin handles all three
// platforms behind one API: macOS LaunchAgent plist, Windows registry
// Run key, Linux .desktop autostart entry. Source of truth is the OS
// state, not the settings.json field — Settings UI calls
// `get_autostart` to populate the toggle on open and `set_autostart`
// on flip.
#[tauri::command]
fn get_autostart(app: tauri::AppHandle) -> bool {
    app.autolaunch().is_enabled().unwrap_or(false)
}

#[tauri::command]
fn set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    let manager = app.autolaunch();
    let result = if enabled { manager.enable() } else { manager.disable() };
    result.map_err(|e| e.to_string())
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
