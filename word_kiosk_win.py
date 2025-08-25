
"""
Word Kiosk — improved resume behavior

State files:
 - %APPDATA%/WordKiosk/goal.json       <-- EXACTLY two fields: {"wordcount": <remaining>, "isTaskCompleted": <bool>}
 - %APPDATA%/WordKiosk/resume.json     <-- small helper file (goal_total + persisted_written) to restore progress after abrupt shutdown
 - %APPDATA%/WordKiosk/progress.json   <-- legacy; will be migrated if present
"""
import json
import os
import sys
import traceback
from pathlib import Path
import atexit
from datetime import datetime

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtWidgets import (
    QApplication, QInputDialog, QMainWindow, QMessageBox, QWidget,
    QLabel, QProgressBar, QVBoxLayout, QHBoxLayout, QPushButton
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript, QWebEngineProfile

# ---------------------------- Windows-only Autostart ----------------------------
APP_NAME = "WordKiosk"
TARGET_URL = "https://app.4thewords.com/dashboard"

APPDATA = os.environ.get("APPDATA", str(Path.home()))
APP_DIR = Path(APPDATA) / "WordKiosk"
APP_DIR.mkdir(parents=True, exist_ok=True)

GOAL_PATH = APP_DIR / "goal.json"      # EXACT two fields required by you
RESUME_PATH = APP_DIR / "resume.json"  # helper for robust resume
LEGACY_PROGRESS = APP_DIR / "progress.json"

PY_EXE = sys.executable
SCRIPT_PATH = Path(sys.argv[0]).resolve()


def set_autostart_windows(enabled: bool) -> None:
    """Create/Remove HKCU Run entry for autostart. No admin required."""
    try:
        import winreg  # type: ignore
    except Exception:
        return
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
    except Exception:
        return
    try:
        if enabled:
            cmd = f'"{PY_EXE}" "{SCRIPT_PATH}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    finally:
        try:
            key.Close()
        except Exception:
            pass


# -------------------------- Atomic helpers & state I/O -------------------------
def atomic_write_json(path: Path, data: dict):
    """Write JSON atomically (write -> fsync -> replace)."""
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        traceback.print_exc()


def load_state():
    """
    Return a dict containing:
      - goal_total: total words originally requested (int)
      - persisted_written: highest observed written count persisted to disk (int)
      - remaining: current remaining words (int)
      - isTaskCompleted: bool
    This function will migrate legacy 'progress.json' (with keys 'goal'/'written'/'completed')
    into the new pair of files if found.
    """
    # 1) Legacy migration
    if LEGACY_PROGRESS.exists():
        try:
            with open(LEGACY_PROGRESS, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "goal" in d:
                goal_total = int(d.get("goal", 0))
                persisted_written = int(d.get("written", 0))
                completed = bool(d.get("completed", persisted_written >= goal_total))
                remaining = max(0, goal_total - persisted_written)
                # Save into goal.json (two-field) and resume.json
                atomic_write_json(GOAL_PATH, {"wordcount": int(remaining), "isTaskCompleted": bool(completed)})
                atomic_write_json(RESUME_PATH, {"goal_total": int(goal_total), "persisted_written": int(persisted_written)})
                return {"goal_total": goal_total, "persisted_written": persisted_written, "remaining": remaining, "isTaskCompleted": completed}
        except Exception:
            traceback.print_exc()
            # fall through to other options

    # 2) resume.json exists — best case
    if RESUME_PATH.exists():
        try:
            with open(RESUME_PATH, "r", encoding="utf-8") as f:
                r = json.load(f)
            goal_total = int(r.get("goal_total", 0))
            persisted_written = int(r.get("persisted_written", 0))
            remaining = max(0, goal_total - persisted_written)
            completed = persisted_written >= goal_total
            # Ensure goal.json reflects this two-field shape (keep this canonical)
            atomic_write_json(GOAL_PATH, {"wordcount": int(remaining), "isTaskCompleted": bool(completed)})
            return {"goal_total": goal_total, "persisted_written": persisted_written, "remaining": remaining, "isTaskCompleted": completed}
        except Exception:
            traceback.print_exc()

    # 3) Only goal.json exists (we keep it two-field). We don't know goal_total/persisted_written.
    if GOAL_PATH.exists():
        try:
            with open(GOAL_PATH, "r", encoding="utf-8") as f:
                g = json.load(f)
            remaining = int(g.get("wordcount", 0))
            completed = bool(g.get("isTaskCompleted", True))
            # Best-effort fallback: assume goal_total == remaining and persisted_written == 0
            goal_total = int(remaining)
            persisted_written = 0
            return {"goal_total": goal_total, "persisted_written": persisted_written, "remaining": remaining, "isTaskCompleted": completed}
        except Exception:
            traceback.print_exc()

    # Default: no task
    return {"goal_total": 0, "persisted_written": 0, "remaining": 0, "isTaskCompleted": True}


def save_goal_state(remaining: int, completed: bool):
    """Save only the two-field goal.json (remaining + isTaskCompleted)."""
    atomic_write_json(GOAL_PATH, {"wordcount": int(max(0, remaining)), "isTaskCompleted": bool(completed)})


def save_resume_state(goal_total: int, persisted_written: int):
    """Save helper resume state that lets us restore progress after an abrupt shutdown."""
    atomic_write_json(RESUME_PATH, {"goal_total": int(max(0, goal_total)), "persisted_written": int(max(0, persisted_written))})


# ----------------------------- Web injection script ----------------------------
INJECT_JS = r"""
(() => {
  function countWords(s) {
    if (!s) return 0;
    const m = String(s).trim().match(/\b\w+\b/g);
    return m ? m.length : 0;
  }
  function collectEditableText(doc) {
    let parts = [];
    try { doc.querySelectorAll('textarea').forEach(el => parts.push(el.value || '')); } catch(e){}
    try { doc.querySelectorAll('[contenteditable=""], [contenteditable="true"]').forEach(el => parts.push(el.innerText || el.textContent || '')); } catch(e){}
    return parts.join(' ');
  }
  function computeCountAcrossFrames(win) {
    let total = '';
    try { total += ' ' + collectEditableText(win.document); } catch(e){}
    try {
      const ifr = win.document.querySelectorAll('iframe');
      for (const f of ifr) {
        try { if (f.contentWindow) total += ' ' + collectEditableText(f.contentWindow.document); } catch(e){}
      }
    } catch(e){}
    return countWords(total);
  }
  function setup() {
    if (window.__wordTrackerInstalled) return;
    window.__wordTrackerInstalled = true;
    const recalc = () => { try { window._writerWordCount = computeCountAcrossFrames(window); } catch(e){} };
    const events = ['input','keyup','change','click'];
    events.forEach(ev => window.addEventListener(ev, recalc, true));
    setInterval(recalc, 1000);
    recalc();
  }
  try { setup(); } catch(e){}
})();
"""


# --------------------------------- Main window ---------------------------------
class WordKiosk(QMainWindow):
    def __init__(self, goal_total: int, persisted_written: int, remaining: int):
        super().__init__()
        self.goal_total = int(max(0, goal_total))
        self.persisted_written = int(max(0, persisted_written))  # high-watermark persisted across runs
        self.remaining = int(max(0, remaining))                # remaining (mirrors goal.json)
        self._allow_close = (self.remaining == 0)

        self.setWindowTitle("4thewords Kiosk – Finish your remaining words")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # Header UI
        self.header = QWidget(); self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header); header_layout.setContentsMargins(16, 12, 16, 12); header_layout.setSpacing(16)
        self.lbl_remaining = QLabel(f"Remaining: {self.remaining}")
        self.lbl_live = QLabel(f"Live (this page): 0")
        for lbl in (self.lbl_remaining, self.lbl_live):
            f = lbl.font(); f.setPointSize(14); f.setBold(True); lbl.setFont(f)
        self.progress = QProgressBar(); self.progress.setRange(0, max(1, self.goal_total)); self.progress.setValue(self.goal_total - self.remaining); self.progress.setTextVisible(True); self.progress.setFixedHeight(28)
        self.btn_done = QPushButton("Finish & Quit"); self.btn_done.setEnabled(self._allow_close); self.btn_done.clicked.connect(self.finish_and_quit)
        header_layout.addWidget(self.lbl_remaining); header_layout.addWidget(self.lbl_live); header_layout.addWidget(self.progress, 1); header_layout.addWidget(self.btn_done)

        # Web view
        self.web = QWebEngineView(); self.web.setContextMenuPolicy(Qt.NoContextMenu)
        profile: QWebEngineProfile = self.web.page().profile()
        script = QWebEngineScript(); script.setName("WordTrackerInject"); script.setInjectionPoint(QWebEngineScript.DocumentReady); script.setWorldId(QWebEngineScript.MainWorld); script.setRunsOnSubFrames(True); script.setSourceCode(INJECT_JS)
        profile.scripts().insert(script)
        self.web.load(QUrl(TARGET_URL))

        # Layout
        central = QWidget(); v = QVBoxLayout(central); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0); v.addWidget(self.header); v.addWidget(self.web, 1); self.setCentralWidget(central)

        # Polling
        self.timer = QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.poll_word_count); self.timer.start()

        # Refocus watchdog to keep window visible while unfinished
        self.refocus = QTimer(self); self.refocus.setInterval(900); self.refocus.timeout.connect(self.force_foreground_if_needed); self.refocus.start()

        # Ensure autostart state matches unfinished/completed
        set_autostart_windows(enabled=(self.remaining > 0))
        save_goal_state(self.remaining, completed=(self.remaining == 0))
        save_resume_state(self.goal_total, self.persisted_written)
        
        # Make window full screen
        self.showFullScreen()

    def poll_word_count(self):
        js = "Number(window._writerWordCount || 0)"
        try:
            self.web.page().runJavaScript(js, self.update_from_js)
        except RuntimeError:
            pass

    def update_from_js(self, value):
        try:
            live = int(value) if value is not None else 0
        except Exception:
            live = 0

        # effective is max of persisted (from previous runs) and live (page)
        effective_written = max(self.persisted_written, live)

        # If the live count increased beyond what we've persisted, persist it right away.
        if effective_written > self.persisted_written:
            self.persisted_written = effective_written
            save_resume_state(self.goal_total, self.persisted_written)

        # Compute remaining using the total goal and effective written
        new_remaining = max(0, self.goal_total - effective_written)

        # Update UI & save goal.json if remaining changed
        if new_remaining != self.remaining:
            self.remaining = new_remaining
            save_goal_state(self.remaining, completed=(self.remaining == 0))

        self.lbl_live.setText(f"current: {live}")
        self.lbl_remaining.setText(f"Remaining: {self.remaining}")
        self.progress.setMaximum(max(1, self.goal_total))
        self.progress.setValue(self.goal_total - self.remaining)

        if self.remaining == 0 and not self._allow_close:
            self._allow_close = True
            set_autostart_windows(False)
            QMessageBox.information(self, "Great job!", "You reached your word goal. You can now finish and quit.", QMessageBox.Ok)
            self.btn_done.setEnabled(True)

    def force_foreground_if_needed(self):
        if self._allow_close:
            return
        try:
            # If minimized, restore to fullscreen and bring to front
            if self.windowState() & Qt.WindowMinimized:
                self.showFullScreen()
            self.raise_()
            self.activateWindow()
            self._win_bring_to_front()
        except Exception:
            pass

    def _win_bring_to_front(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            SW_RESTORE = 9
            SW_MAXIMIZE = 3
            # Restore/maximize and force to foreground
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if not self._allow_close and event.key() in (Qt.Key_Escape, Qt.Key_F11):
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QtCore.QEvent):
        # Prevent staying minimized while task is unfinished
        if not self._allow_close:
            try:
                if (self.windowState() & Qt.WindowMinimized) or self.isMinimized():
                    self.showFullScreen()
                    QTimer.singleShot(0, self.force_foreground_if_needed)
            except Exception:
                pass
        super().changeEvent(event)

    def focusOutEvent(self, event: QtGui.QFocusEvent):
        if not self._allow_close:
            QTimer.singleShot(0, self.force_foreground_if_needed)
        super().focusOutEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent):
        if self._allow_close:
            event.accept()
        else:
            QMessageBox.warning(self, "Keep going!", "You haven't reached your word goal yet. The window will stay open until you finish.", QMessageBox.Ok)
            event.ignore()

    def finish_and_quit(self):
        if self.remaining == 0:
            self._allow_close = True
            save_goal_state(0, True)
            save_resume_state(self.goal_total, self.persisted_written)
            set_autostart_windows(False)
            self.close()

   
# ------------------------------ App orchestration ------------------------------
def ask_new_goal(parent=None) -> int:
    while True:
        goal, ok = QInputDialog.getInt(parent, "Set your word goal", "How many words will you write?", value=500, min=1, max=1_000_000)
        if not ok:
            resp = QMessageBox.question(parent, "Exit?", "No goal set. Quit the app?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if resp == QMessageBox.Yes:
                return -1
            else:
                continue
        return int(goal)


def main():
    if sys.platform != "win32":
        print("This build is intended for Windows only.")

    app = QApplication(sys.argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    st = load_state()
    remaining = int(st.get("remaining", 0))
    completed = bool(st.get("isTaskCompleted", True))
    goal_total = int(st.get("goal_total", 0))
    persisted_written = int(st.get("persisted_written", 0))

    if (not completed) and remaining > 0 and goal_total > 0:
        # Resume unfinished task
        start_goal_total = goal_total
        start_persisted_written = persisted_written
        start_remaining = remaining
    else:
        # Fresh task: ask for new goal
        g = ask_new_goal()
        if g < 0:
            sys.exit(0)
        start_goal_total = g
        start_persisted_written = 0
        start_remaining = g
        save_resume_state(start_goal_total, start_persisted_written)
        save_goal_state(start_remaining, completed=False)
        set_autostart_windows(True)

    win = WordKiosk(start_goal_total, start_persisted_written, start_remaining)

    # Ensure we persist state on exit as safety
    def on_quit():
        try:
            save_resume_state(win.goal_total, win.persisted_written)
            save_goal_state(win.remaining, completed=(win.remaining == 0))
            set_autostart_windows(enabled=(win.remaining > 0))
        except Exception:
            traceback.print_exc()

    atexit.register(on_quit)
    app.aboutToQuit.connect(on_quit)

    win.show()
    code = app.exec_()

    # final ensure
    final = load_state()
    set_autostart_windows(enabled=(not final.get("isTaskCompleted", True)))
    sys.exit(code)


if __name__ == "__main__":
    main()




