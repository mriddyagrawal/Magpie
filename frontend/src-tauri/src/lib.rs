use std::fs::OpenOptions;
use std::io::Write;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

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
                    // Last argument = corner radius (points) for the
                    // NSVisualEffectView backdrop on macOS. `0.0` = sharp
                    // rectangular corners. Previously `18.0` (more rounded
                    // than the macOS system default of ~10pt). Inner cards
                    // (status pill, blob, sources, etc.) keep their own
                    // CSS border-radius — only the OUTER window frame is
                    // affected here.
                    let _ = apply_vibrancy(
                        &window,
                        NSVisualEffectMaterial::FullScreenUI,
                        Some(NSVisualEffectState::Active),
                        Some(0.0),
                    );
                }
            }

            let handle = app.handle().clone();

            // Defensive cleanup BEFORE we spawn fresh children: any qdrant /
            // magpie-sidecar / llama-server left running from a prior crash
            // or force-quit would otherwise hold the storage dir / port and
            // make the new spawn fail. macOS reparents orphans to launchd
            // (PID 1), so they live forever otherwise. Logged to bootstrap.log.
            kill_orphan_subprocesses();

            // Pre-pick ports instantly (just binds + releases a socket) so the
            // window can appear immediately with the port already known — no
            // blocking on qdrant/sidecar startup inside setup().
            //
            // Qdrant needs TWO ports (HTTP + gRPC). Old code only pre-picked
            // HTTP and let qdrant default gRPC to 6334 — which collides with
            // any other qdrant-using app on the same machine (OpenWhispr's
            // qdrant binds 6333/6334 on devs' machines, e.g.). Pre-picking
            // both eliminates the collision and the silent qdrant exit it
            // caused.
            let sidecar_port = pick_free_port().unwrap_or(8765);
            *app.state::<SidecarPort>().0.lock().unwrap() = sidecar_port;
            let qdrant_ports: Option<(u16, u16)> = if cfg!(not(debug_assertions)) {
                match (pick_free_port(), pick_free_port()) {
                    (Ok(http), Ok(grpc)) => Some((http, grpc)),
                    _ => None,
                }
            } else {
                None
            };
            let qdrant_port_pre: Option<u16> = qdrant_ports.map(|(http, _)| http);
            let qdrant_grpc_pre: Option<u16> = qdrant_ports.map(|(_, grpc)| grpc);

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
                            bootstrap_log("fatal: could not pre-pick qdrant HTTP port");
                            return;
                        }
                    };
                    let grpc_port = match qdrant_grpc_pre {
                        Some(p) => p,
                        None => {
                            bootstrap_log("fatal: could not pre-pick qdrant gRPC port");
                            return;
                        }
                    };
                    bootstrap_log(format!(
                        "spawning qdrant on http={port} grpc={grpc_port}"
                    ));
                    match spawn_qdrant(&bg, port, grpc_port) {
                        Err(e) => {
                            bootstrap_log(format!("fatal: qdrant failed to start: {e}"));
                            bg.dialog()
                                .message(format!(
                                    "Magpie could not start its search database.\n\n\
                                     Error: {e}\n\n\
                                     See bootstrap log: {}",
                                    bootstrap_log_path().display(),
                                ))
                                .kind(MessageDialogKind::Error)
                                .title("Magpie failed to start")
                                .blocking_show();
                            return;
                        }
                        Ok(child) => {
                            *bg.state::<QdrantState>().0.lock().unwrap() = Some(child);
                            if !wait_for_port(port, 30) {
                                bootstrap_log(
                                    "fatal: qdrant not ready after 15s. \
                                     Check bootstrap.log for qdrant's stderr — \
                                     most likely cause is a port collision (gRPC \
                                     6334 is the historical default), a corrupt \
                                     storage dir, or qdrant exiting silently.",
                                );
                                bg.dialog()
                                    .message(format!(
                                        "Magpie's search database took too long to start.\n\n\
                                         See bootstrap log: {}\n\n\
                                         Please try relaunching the app.",
                                        bootstrap_log_path().display(),
                                    ))
                                    .kind(MessageDialogKind::Error)
                                    .title("Magpie failed to start")
                                    .blocking_show();
                                return;
                            }
                            bootstrap_log(format!("qdrant ready on http={port}"));
                            Some(port)
                        }
                    }
                } else {
                    None
                };

                // Start the Python sidecar on the pre-picked port.
                bootstrap_log(format!(
                    "spawning sidecar on port {sidecar_port} (qdrant={qdrant_port:?})"
                ));
                match spawn_sidecar(&bg, sidecar_port, qdrant_port) {
                    Err(e) => {
                        bootstrap_log(format!("fatal: sidecar failed to start: {e}"));
                        bg.dialog()
                            .message(format!(
                                "Magpie could not start its search backend.\n\n\
                                 Error: {e}\n\n\
                                 See bootstrap log: {}",
                                bootstrap_log_path().display(),
                            ))
                            .kind(MessageDialogKind::Error)
                            .title("Magpie failed to start")
                            .blocking_show();
                    }
                    Ok(child) => {
                        *bg.state::<SidecarState>().0.lock().unwrap() = Some(child);
                        bootstrap_log(format!("sidecar spawned, pid={:?}", bg.state::<SidecarState>().0.lock().unwrap().as_ref().map(|c| c.id())));
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                // macOS: when Settings is dismissed, drop back to Accessory so
                // Magpie leaves the Dock again (it was promoted to Regular in
                // open_settings_internal). The spotlight bar ("main") hides the
                // same way but never touched the policy, so only "settings"
                // reverts. No-op on Windows/Linux.
                #[cfg(target_os = "macos")]
                if window.label() == "settings" {
                    let _ = window
                        .app_handle()
                        .set_activation_policy(tauri::ActivationPolicy::Accessory);
                }
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

// ---------------------------------------------------------------------------
// Bootstrap logging — write everything Tauri's spawn paths used to
// silently drop. Old code passed `Stdio::null()` for both qdrant and
// magpie-sidecar, which meant the user got "took too long" dialogs with
// zero diagnostic. Now every spawn pipes stderr (and qdrant's stdout)
// into APP_DATA_DIR/logs/bootstrap-<utc-ts>.log. The .log path is also
// printed to stderr on first write so the user can `tail -f` it.
// ---------------------------------------------------------------------------

/// Per-launch bootstrap log path. Resolved lazily on first write to
/// `APP_DATA_DIR/logs/bootstrap-YYYYMMDDTHHMMSSZ.log`. Filesystem-safe
/// timestamp (no `:` for Windows). Never errors back to the caller —
/// logging must never block the actual spawn path.
fn bootstrap_log_path() -> PathBuf {
    static ONCE: std::sync::OnceLock<PathBuf> = std::sync::OnceLock::new();
    ONCE.get_or_init(|| {
        let logs_dir = app_data_dir().join("logs");
        let _ = std::fs::create_dir_all(&logs_dir);
        let ts = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        // Compact ISO-ish timestamp via integer seconds-since-epoch is
        // boring but unambiguous; `date -ud @<n>` decodes it cleanly.
        let path = logs_dir.join(format!("bootstrap-{ts}.log"));
        eprintln!("[magpie] bootstrap log: {}", path.display());
        path
    })
    .clone()
}

/// Append a one-line UTF-8 message with a "[magpie] " prefix to the
/// bootstrap log AND mirror to stderr. Best-effort; failures are
/// swallowed to keep the spawn path resilient.
fn bootstrap_log(msg: impl AsRef<str>) {
    let line = format!(
        "[{}] {}\n",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0),
        msg.as_ref()
    );
    eprint!("[magpie] {line}");
    if let Ok(mut f) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(bootstrap_log_path())
    {
        let _ = f.write_all(line.as_bytes());
    }
}

/// Open the bootstrap log file for `Stdio::from()` use. Spawns get
/// their stderr / stdout redirected here so any later crash leaves a
/// trail. Falls back to `Stdio::null()` if the open fails — losing
/// logs is preferable to crashing the parent.
fn bootstrap_stdio() -> Stdio {
    OpenOptions::new()
        .create(true)
        .append(true)
        .open(bootstrap_log_path())
        .map(Stdio::from)
        .unwrap_or_else(|_| Stdio::null())
}

// ---------------------------------------------------------------------------
// Orphan cleanup — kill any qdrant / magpie-sidecar / llama-server
// subprocess whose argv path resolves under our app bundle or
// APP_DATA_DIR. These are leftovers from prior crashes / force-quits /
// OS kills that the graceful Exit handler never got to clean up. macOS
// reparents orphans to launchd, so they live forever otherwise.
//
// We shell out to `ps -ax -o pid=,args=` rather than pulling in the
// `sysinfo` crate — keeps the dependency budget flat. macOS + Linux
// support this exact flag set; Windows uses `tasklist` (separate
// branch below). Worst case: the scan misses an orphan (unkillable
// edge case) and the next sync fails the same way it failed today —
// we're no worse off than before this code existed.
// ---------------------------------------------------------------------------

/// Best-effort kill of any orphaned magpie subprocess from a prior run.
/// Runs early in `setup()` before we spawn fresh children. Logs every
/// match (killed or skipped) to the bootstrap log so a future user
/// running into "took too long" can see the cleanup history.
fn kill_orphan_subprocesses() {
    let app_dir = app_data_dir();
    let app_dir_str = app_dir.to_string_lossy().to_string();
    // Resolve our .app bundle path so we can scope the match. On Mac
    // .app: <bundle>/Contents/MacOS/<name>. On Linux/Windows: directory
    // containing the running executable.
    let bundle_root = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();

    let processes = scan_magpie_processes();
    if processes.is_empty() {
        bootstrap_log("orphan scan: no leftover qdrant/sidecar/llama-server processes");
        return;
    }

    for (pid, args) in processes {
        // Decide if this PID belongs to a previous Magpie run. Heuristic:
        // (a) argv0 starts with our bundle dir, OR
        // (b) argv0 starts with APP_DATA_DIR (covers older versions that
        //     copied binaries into Application Support).
        // Otherwise leave it alone — could be another app's qdrant
        // (e.g., OpenWhispr ships its own qdrant in /Applications).
        let belongs_to_magpie = (!bundle_root.is_empty() && args.starts_with(&bundle_root))
            || args.starts_with(&app_dir_str);
        if !belongs_to_magpie {
            bootstrap_log(format!("orphan scan: skipped pid={pid} (not ours): {args}"));
            continue;
        }
        bootstrap_log(format!("orphan scan: killing pid={pid}: {args}"));
        // SIGKILL — graceful SIGTERM would be nicer but if a previous
        // SIGTERM / Exit handler already failed to clean up, SIGKILL
        // is the right escalation. Best-effort: ignore failure.
        #[cfg(unix)]
        {
            let _ = Command::new("kill").args(["-9", &pid]).status();
        }
        #[cfg(windows)]
        {
            let _ = Command::new("taskkill")
                .args(["/F", "/PID", &pid])
                .status();
        }
    }
}

/// Cross-platform process scanner. Returns `(pid, full_argv)` pairs
/// for every running process whose binary name matches `qdrant`,
/// `magpie-sidecar`, or `llama-server`. The caller filters further
/// by argv path. Empty list on any platform-specific error.
fn scan_magpie_processes() -> Vec<(String, String)> {
    #[cfg(unix)]
    {
        // `ps -ax -o pid=,args=` prints every process with PID + full
        // argv on one line. Trailing `=` removes the column header.
        let out = Command::new("ps")
            .args(["-ax", "-o", "pid=,args="])
            .output();
        let Ok(out) = out else {
            return Vec::new();
        };
        let stdout = String::from_utf8_lossy(&out.stdout);
        return parse_unix_ps(&stdout);
    }
    #[cfg(windows)]
    {
        // tasklist in CSV mode: `,"<image>","<session>","<pid>",...`. We
        // don't have full argv from tasklist alone; the image name is
        // enough since Magpie's children have unique names.
        let out = Command::new("tasklist")
            .args(["/FO", "CSV", "/NH"])
            .output();
        let Ok(out) = out else {
            return Vec::new();
        };
        let stdout = String::from_utf8_lossy(&out.stdout);
        return parse_windows_tasklist(&stdout);
    }
}

#[cfg(unix)]
fn parse_unix_ps(stdout: &str) -> Vec<(String, String)> {
    let names = ["qdrant", "magpie-sidecar", "llama-server"];
    let mut out = Vec::new();
    for line in stdout.lines() {
        // Each line: `  <pid> <argv0> <args...>`. Trim leading whitespace,
        // split on the first whitespace.
        let line = line.trim_start();
        let Some((pid_str, rest)) = line.split_once(char::is_whitespace) else {
            continue;
        };
        let rest = rest.trim_start();
        if names.iter().any(|n| rest.contains(n)) {
            out.push((pid_str.to_string(), rest.to_string()));
        }
    }
    out
}

#[cfg(windows)]
fn parse_windows_tasklist(stdout: &str) -> Vec<(String, String)> {
    // Each CSV row: "image.exe","session","pid","mem"
    let names = ["qdrant.exe", "magpie-sidecar.exe", "llama-server.exe"];
    let mut out = Vec::new();
    for line in stdout.lines() {
        let parts: Vec<_> = line.trim_matches('"').split("\",\"").collect();
        if parts.len() < 3 {
            continue;
        }
        let image = parts[0];
        let pid = parts[1]; // skip session in cols
        if names.iter().any(|n| image.eq_ignore_ascii_case(n)) {
            out.push((pid.to_string(), image.to_string()));
        }
    }
    out
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

/// Resolve the directory containing externalBin sidecars at runtime.
///
/// Tauri 2 places `externalBin` entries from `tauri.conf.json` ALONGSIDE
/// the main executable on every platform — never in `Resources/`:
///
///   - macOS .app:        `Contents/MacOS/<name>`         (next to `Magpie`)
///   - Linux AppImage:    `usr/bin/<name>`                (next to `magpie`)
///   - Linux .deb:        `/usr/bin/<name>`               (next to `magpie`)
///   - Windows MSI/NSIS:  `<install-dir>/<name>.exe`      (next to `Magpie.exe`)
///
/// Earlier code resolved sidecars via `app.path().resource_dir()` which on
/// macOS returns `Contents/Resources/` — wrong by one directory. The bundle
/// shipped fine but the spawn always failed with `No such file or directory
/// (os error 2)` on user machines. This helper uses `current_exe().parent()`
/// which is correct on all three platforms.
fn bundled_bin_dir() -> Result<PathBuf, String> {
    std::env::current_exe()
        .map_err(|e| format!("could not resolve current_exe: {e}"))?
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "current_exe has no parent directory".to_string())
}

// Spawn qdrant on a pre-picked port; caller is responsible for storing the child.
//
// `http_port` and `grpc_port` are both passed via env so qdrant doesn't fall
// back to its 6334 gRPC default (which collides with any other qdrant-using
// app on the machine — OpenWhispr is the canonical case).
//
// `current_dir` is set to a WRITABLE directory under APP_DATA_DIR. Qdrant
// creates several files / dirs relative to cwd (`./snapshots/`, `./snapshots/tmp/`,
// `.qdrant-initialized` indicator, etc.). When Tauri spawns from a .app bundle,
// the inherited cwd is `Contents/MacOS/` which macOS marks read-only for code
// integrity → qdrant panics with `ReadOnlyFilesystem` and exits silently.
// Pointing cwd at app_data_dir makes those relative paths land somewhere
// writable, matching the explicit STORAGE_PATH env we already set.
//
// Both stdout and stderr are piped into `bootstrap.log` so a future spawn
// failure leaves a trail. Old code used `Stdio::null()` and that's exactly
// why "took too long" dialogs were impossible to debug.
fn spawn_qdrant(_app: &tauri::AppHandle, http_port: u16, grpc_port: u16) -> Result<Child, String> {
    let storage = app_data_dir().join("qdrant_storage");
    std::fs::create_dir_all(&storage).map_err(|e| e.to_string())?;
    // Dedicated runtime dir keeps qdrant's relative-path artifacts (snapshots/,
    // .qdrant-initialized, etc.) tidy and out of the storage tree.
    let runtime = app_data_dir().join("qdrant_runtime");
    std::fs::create_dir_all(&runtime).map_err(|e| e.to_string())?;

    let bin = bundled_bin_dir()?
        .join(if cfg!(windows) { "qdrant.exe" } else { "qdrant" });

    let mut cmd = Command::new(&bin);
    cmd.current_dir(&runtime)
        .env("QDRANT__STORAGE__STORAGE_PATH", &storage)
        .env("QDRANT__SERVICE__HTTP_PORT", http_port.to_string())
        .env("QDRANT__SERVICE__GRPC_PORT", grpc_port.to_string())
        .stdout(bootstrap_stdio())
        .stderr(bootstrap_stdio());
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
    _app: &tauri::AppHandle,
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
        let bin = bundled_bin_dir()?.join(
            if cfg!(windows) { "magpie-sidecar.exe" } else { "magpie-sidecar" },
        );
        let mut c = Command::new(&bin);
        c.arg("--port").arg(port.to_string());
        c.env("MAGPIE_DATA_DIR", app_data_dir());
        if let Some(qport) = qdrant_port {
            c.env("QDRANT_PROVIDER", "cloud")
                .env("QDRANT_CLUSTER_ENDPOINT", format!("http://127.0.0.1:{qport}"));
        }
        c
    };

    // Pipe stdout AND stderr into bootstrap.log. Sidecar's own per-session
    // LLM log lives in APP_DATA_DIR/logs/llm-*.log; this catches everything
    // that comes out before the logger initializes (PyInstaller bootstrap,
    // import errors, fastapi startup messages, etc.).
    cmd.stdout(bootstrap_stdio())
        .stderr(bootstrap_stdio())
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

    // macOS: promote to a regular (Dock-visible) app while Settings is
    // open. The spotlight bar itself runs as `ActivationPolicy::Accessory`
    // (no Dock icon, Spotlight-style); we flip to `Regular` here so Magpie
    // appears in the Dock, then revert to `Accessory` when the Settings
    // window closes (see the on_window_event handler below). Windows shows
    // the settings window in the taskbar natively — no equivalent flip
    // needed there.
    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Regular);

    if let Some(win) = app.get_webview_window("settings") {
        // Already open: re-inject the action so the SettingsWindow
        // component picks it up on its next effect tick. Eval is safe
        // since `action` is whitelisted at the command boundary.
        let _ = win.eval(&init);
        let _ = win.show();
        let _ = win.set_focus();
        return;
    }

    // Build the settings window from a BACKGROUND thread — never the main
    // thread. On Windows, every caller of this function (the `open_settings`
    // command, the tray-menu click, the macOS app menu) runs on the main
    // thread. Creating a webview window there deadlocks (wry#583): the native
    // window frame gets created, but WebView2 initialization needs the main
    // thread to pump messages — and the main thread is blocked inside this
    // very call. Symptom: a permanently white, unclosable "Magpie Settings"
    // window with no web content. macOS's WKWebView initializes differently
    // and never hit this, which is why settings worked on Mac and not on
    // Windows. From a background thread, `.build()` safely dispatches the
    // work to the (free) main event loop on both platforms.
    //
    // Loads the dedicated `settings.html` entry (settings-main.tsx renders
    // <SettingsWindow> directly) instead of the shared index.html +
    // `__MAGPIE_WINDOW_TYPE__` global, which removes the init-script/global
    // race that also white-screened the settings webview on WebView2.
    // Revert to Accessory (no Dock icon) once Settings closes: handled by the
    // app-level `on_window_event` CloseRequested handler in `run()`, keyed on
    // the "settings" window label. (Close is prevented + hidden there, so the
    // window persists and the branch above re-shows it on next open.)
    let app = app.clone();
    std::thread::spawn(move || {
        let built = WebviewWindowBuilder::new(
            &app,
            "settings",
            WebviewUrl::App("settings.html".into()),
        )
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
