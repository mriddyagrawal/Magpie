; Magpie — NSIS installer hooks
; ---------------------------------------------------------------------------
; Windows locks a running .exe, so if Magpie (or a leftover/orphaned child
; process from a prior crash) is still running when the installer tries to
; overwrite its files, NSIS aborts with:
;     "Error opening file for writing: ...\Magpie\qdrant.exe"
; and the install gets stuck (Abort/Retry/Ignore).
;
; These hooks stop every Magpie process BEFORE the installer copies files
; (fresh install / update) and BEFORE the uninstaller removes them, so the
; file locks are always released first. Runs silently — no user action.
;
; Process names match the installed executables:
;   Magpie.exe          the Tauri shell (productName = "Magpie")
;   qdrant.exe          the bundled vector DB sidecar
;   magpie-sidecar.exe  the bundled Python search backend
;   llama-server.exe    the local-LLM server (downloaded at runtime)
;
; /F = force, /T = also kill the process tree (children). We Pop the exit
; code off the stack after each call so a "process not found" result (which
; is the normal, healthy case on a first install) is harmless and doesn't
; leave the NSIS stack dirty.

!macro _magpie_kill_processes
  DetailPrint "Stopping any running Magpie processes..."
  nsExec::Exec 'taskkill /F /T /IM Magpie.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /IM qdrant.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /IM magpie-sidecar.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /IM llama-server.exe'
  Pop $0
  ; Give Windows a moment to release the file handles before we touch files.
  Sleep 500
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro _magpie_kill_processes
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro _magpie_kill_processes
!macroend
