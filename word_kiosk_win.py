# # #!/usr/bin/env python3
# # # -*- coding: utf-8 -*-
# # """
# # Windows-only PyQt5 "Word Goal Kiosk" for 4thewords — with persistence & boot-resume

# # What it does
# # - On launch, if there is an unfinished goal from a previous session, it resumes it
# #   *and forces the app to autostart on Windows boot until the goal is completed*.
# # - If there is no unfinished goal, it asks for a new one.
# # - Loads https://app.4thewords.com/dashboard in a QWebEngineView and injects JS to
# #   count words typed in textareas/contenteditable fields (incl. subframes where possible).
# # - Shows progress (Written / Goal / Remaining) with a progress bar.
# # - Prevents closing/minimizing until the goal is met (kiosk-ish: fullscreen, always-on-top,
# #   frameless; cannot defeat hardware power button or all OS shortcuts).
# # - Persists state (goal, written, completed) at %APPDATA%/WordKiosk/progress.json.
# # - Ensures Windows autostart (HKCU Run) *only while a goal is unfinished*; removes it on completion.

# # Notes
# # - If after reboot the website/editor content is empty, the app still remembers your
# #   last recorded "written" count and uses the *max(previous_written, live_count)* so you
# #   cannot reduce progress by deleting text.
# # - This app doesn’t automate sign-in to 4thewords.

# # Dependencies
# #   pip install PyQt5 PyQtWebEngine

# # Run
# #   python word_kiosk_win.py
# # """

# # import json
# # import os
# # import sys
# # import traceback
# # from pathlib import Path

# # from PyQt5 import QtCore, QtWidgets, QtGui
# # from PyQt5.QtCore import Qt, QTimer
# # from PyQt5.QtWidgets import (
# #     QApplication,
# #     QInputDialog,
# #     QMainWindow,
# #     QMessageBox,
# #     QWidget,
# #     QLabel,
# #     QProgressBar,
# #     QVBoxLayout,
# #     QHBoxLayout,
# #     QPushButton,
# # )
# # from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript, QWebEngineProfile

# # # ---------------------------- Windows-only Autostart ----------------------------
# # APP_NAME = "WordKiosk"
# # TARGET_URL = "https://app.4thewords.com/dashboard"

# # # App data directory
# # APPDATA = os.environ.get("APPDATA", str(Path.home()))
# # APP_DIR = Path(APPDATA) / "WordKiosk"
# # APP_DIR.mkdir(parents=True, exist_ok=True)
# # STATE_PATH = APP_DIR / "progress.json"

# # # Path to this interpreter + script (for autostart)
# # PY_EXE = sys.executable
# # SCRIPT_PATH = Path(sys.argv[0]).resolve()


# # def set_autostart_windows(enabled: bool) -> None:
# #     """Create/Remove HKCU Run entry for autostart. No admin required.
# #     Only active while a goal is unfinished.
# #     """
# #     try:
# #         import winreg  # type: ignore
# #     except Exception:
# #         # Not on Windows or module unavailable
# #         return

# #     try:
# #         key = winreg.OpenKey(
# #             winreg.HKEY_CURRENT_USER,
# #             r"Software\Microsoft\Windows\CurrentVersion\Run",
# #             0,
# #             winreg.KEY_SET_VALUE,
# #         )
# #     except Exception:
# #         return

# #     try:
# #         if enabled:
# #             # Quote paths with spaces; pass script path explicitly
# #             cmd = f'"{PY_EXE}" "{SCRIPT_PATH}"'
# #             winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
# #         else:
# #             try:
# #                 winreg.DeleteValue(key, APP_NAME)
# #             except FileNotFoundError:
# #                 pass
# #     finally:
# #         try:
# #             key.Close()
# #         except Exception:
# #             pass


# # # ------------------------------ State management -------------------------------

# # def load_state() -> dict:
# #     if STATE_PATH.exists():
# #         try:
# #             with open(STATE_PATH, "r", encoding="utf-8") as f:
# #                 data = json.load(f)
# #                 if isinstance(data, dict):
# #                     return data
# #         except Exception:
# #             traceback.print_exc()
# #     return {"goal": 0, "written": 0, "completed": True}


# # def save_state(goal: int, written: int, completed: bool) -> None:
# #     data = {"goal": int(goal), "written": int(max(0, written)), "completed": bool(completed)}
# #     try:
# #         with open(STATE_PATH, "w", encoding="utf-8") as f:
# #             json.dump(data, f)
# #     except Exception:
# #         traceback.print_exc()


# # # ----------------------------- Web injection script ----------------------------
# # INJECT_JS = r"""
# # (() => {
# #   function countWords(s) {
# #     if (!s) return 0;
# #     const m = String(s).trim().match(/\b\w+\b/g);
# #     return m ? m.length : 0;
# #   }
# #   function collectEditableText(rootDoc) {
# #     let parts = [];
# #     try {
# #       const textareas = rootDoc.querySelectorAll('textarea');
# #       textareas.forEach(el => parts.push(el.value || ''));
# #     } catch (e) {}
# #     try {
# #       const editables = rootDoc.querySelectorAll('[contenteditable=""], [contenteditable="true"]');
# #       editables.forEach(el => parts.push(el.innerText || el.textContent || ''));
# #     } catch (e) {}
# #     return parts.join(' ');
# #   }
# #   function computeCountAcrossFrames(win) {
# #     let totalText = '';
# #     try { totalText += ' ' + collectEditableText(win.document); } catch (e) {}
# #     try {
# #       const iframes = win.document.querySelectorAll('iframe');
# #       for (const f of iframes) {
# #         try { if (f.contentWindow) totalText += ' ' + collectEditableText(f.contentWindow.document); }
# #         catch (e) { /* cross-origin */ }
# #       }
# #     } catch (e) {}
# #     return countWords(totalText);
# #   }
# #   function setup() {
# #     if (window.__wordTrackerInstalled) return;
# #     window.__wordTrackerInstalled = true;
# #     const recalc = () => { try { window._writerWordCount = computeCountAcrossFrames(window); } catch (e) {} };
# #     window.addEventListener('input', recalc, true);
# #     window.addEventListener('keyup', recalc, true);
# #     window.addEventListener('change', recalc, true);
# #     window.addEventListener('click', recalc, true);
# #     setInterval(recalc, 1000);
# #     recalc();
# #   }
# #   try { setup(); } catch (e) {}
# # })();
# # """


# # # --------------------------------- Main window ---------------------------------
# # class WordKiosk(QMainWindow):
# #     def __init__(self, goal_words: int, prior_written: int = 0, resume_mode: bool = False):
# #         super().__init__()
# #         self.goal = max(0, int(goal_words))
# #         self.prior_written = max(0, int(prior_written))  # persisted progress from previous sessions
# #         self.count_live = 0  # live page-derived count
# #         self.allow_close = self.goal == 0  # allow close if no goal
# #         self.resume_mode = resume_mode

# #         self.setWindowTitle("4thewords Kiosk – Word Goal")
# #         self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
# #         self.setWindowFlag(Qt.FramelessWindowHint, True)  # remove OS buttons
# #         self.setAttribute(Qt.WA_DeleteOnClose, True)

# #         # Header UI
# #         self.header = QWidget(); self.header.setObjectName("header")
# #         header_layout = QHBoxLayout(self.header); header_layout.setContentsMargins(16, 12, 16, 12); header_layout.setSpacing(16)
# #         self.lbl_goal = QLabel(f"Goal: {self.goal}")
# #         self.lbl_progress = QLabel("Written: 0")
# #         self.lbl_remaining = QLabel(f"Remaining: {self.goal}")
# #         for lbl in (self.lbl_goal, self.lbl_progress, self.lbl_remaining):
# #             f = lbl.font(); f.setPointSize(14); f.setBold(True); lbl.setFont(f)
# #         self.progress = QProgressBar(); self.progress.setRange(0, max(1, self.goal)); self.progress.setValue(0); self.progress.setTextVisible(True); self.progress.setFixedHeight(28)
# #         self.btn_quit = QPushButton("Finish & Quit"); self.btn_quit.setEnabled(False); self.btn_quit.clicked.connect(self.handle_finish_quit)
# #         header_layout.addWidget(self.lbl_goal); header_layout.addWidget(self.lbl_progress); header_layout.addWidget(self.lbl_remaining); header_layout.addWidget(self.progress, 1); header_layout.addWidget(self.btn_quit)

# #         # Web view
# #         self.web = QWebEngineView(); self.web.setContextMenuPolicy(Qt.NoContextMenu)
# #         profile: QWebEngineProfile = self.web.page().profile()
# #         script = QWebEngineScript(); script.setName("WordTrackerInject"); script.setInjectionPoint(QWebEngineScript.DocumentReady); script.setWorldId(QWebEngineScript.MainWorld); script.setRunsOnSubFrames(True); script.setSourceCode(INJECT_JS)
# #         profile.scripts().insert(script)
# #         self.web.load(QtCore.QUrl(TARGET_URL))

# #         # Layout
# #         central = QWidget(); v = QVBoxLayout(central); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0); v.addWidget(self.header); v.addWidget(self.web, 1); self.setCentralWidget(central)

# #         # Polling
# #         self.timer = QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.poll_word_count); self.timer.start()

# #         # Style & Fullscreen
# #         self.apply_styles(); QtCore.QTimer.singleShot(0, self.showFullScreen)

# #         # If we are in resume mode (unfinished goal), enforce autostart
# #         set_autostart_windows(enabled=True)

# #     # Effective written is the max of persisted and live (can't go backwards)
# #     def effective_written(self) -> int:
# #         return max(self.prior_written, self.count_live)

# #     def apply_styles(self):
# #         self.setStyleSheet(
# #             """
# #             QWidget#header { background: #0f172a; color: #e2e8f0; border-bottom: 1px solid #1e293b; }
# #             QLabel { color: #e2e8f0; }
# #             QProgressBar { background: #1e293b; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; }
# #             QProgressBar::chunk { background-color: #22c55e; }
# #             QPushButton { background: #22c55e; color: #0f172a; border: none; padding: 8px 14px; border-radius: 8px; font-weight: 600; }
# #             QPushButton:disabled { background: #334155; color: #94a3b8; }
# #             """
# #         )

# #     def poll_word_count(self):
# #         js = "Number(window._writerWordCount || 0)"
# #         try:
# #             self.web.page().runJavaScript(js, self.update_from_js)
# #         except RuntimeError:
# #             pass

# #     def update_from_js(self, value):
# #         try:
# #             self.count_live = int(value) if value is not None else 0
# #         except Exception:
# #             self.count_live = 0

# #         written = self.effective_written()
# #         remaining = max(0, self.goal - written)

# #         self.lbl_progress.setText(f"Written: {written}")
# #         self.lbl_remaining.setText(f"Remaining: {remaining}")
# #         self.progress.setMaximum(max(1, self.goal))
# #         self.progress.setValue(min(written, self.goal))

# #         # Persist progress regularly
# #         save_state(self.goal, written, completed=(written >= self.goal))

# #         if not self.allow_close and written >= self.goal:
# #             self.allow_close = True
# #             self.btn_quit.setEnabled(True)
# #             # Remove autostart now that the goal is complete
# #             set_autostart_windows(enabled=False)
# #             QMessageBox.information(self, "Great job!", "You reached your word goal. You can now finish and quit.", QMessageBox.Ok)

# #     def handle_finish_quit(self):
# #         if self.effective_written() >= self.goal:
# #             self.close()

# #     # Prevent closing until goal met
# #     def closeEvent(self, event: QtGui.QCloseEvent):
# #         if self.allow_close:
# #             event.accept()
# #         else:
# #             QMessageBox.warning(self, "Keep going!", "You haven't reached your word goal yet. The window will stay open until you finish.", QMessageBox.Ok)
# #             event.ignore()

# #     # Light key filtering (doesn't block OS-level combos)
# #     def keyPressEvent(self, event: QtGui.QKeyEvent):
# #         if not self.allow_close:
# #             if event.key() in (Qt.Key_Escape,):
# #                 return
# #         super().keyPressEvent(event)


# # # ------------------------------- App orchestration ------------------------------
# # def ask_goal(parent=None) -> int:
# #     while True:
# #         goal, ok = QInputDialog.getInt(parent, "Set your word goal", "How many words will you write today?", value=500, min=1, max=1_000_000)
# #         if not ok:
# #             resp = QMessageBox.question(parent, "Exit?", "No goal set. Quit the app?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
# #             if resp == QMessageBox.Yes:
# #                 return -1
# #             else:
# #                 continue
# #         return int(goal)


# # def main():
# #     if sys.platform != "win32":
# #         print("This build is intended for Windows only.")

# #     app = QApplication(sys.argv)
# #     QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
# #     QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# #     state = load_state()
# #     resume_mode = not state.get("completed", True) and state.get("goal", 0) > 0

# #     if resume_mode:
# #         # Resume unfinished goal; enable autostart until completion
# #         goal = int(state.get("goal", 0))
# #         prior_written = int(state.get("written", 0))
# #         win = WordKiosk(goal, prior_written=prior_written, resume_mode=True)
# #     else:
# #         # Fresh session: ask for a new goal
# #         goal = ask_goal()
# #         if goal < 0:
# #             sys.exit(0)
# #         # Start tracking from 0 and mark as not completed + enable autostart
# #         save_state(goal, 0, completed=False)
# #         set_autostart_windows(enabled=True)
# #         win = WordKiosk(goal, prior_written=0, resume_mode=True)

# #     win.show()
# #     code = app.exec_()

# #     # On exit, make sure state reflects completion status; if complete, disable autostart
# #     final = load_state()
# #     if final.get("completed"):
# #         set_autostart_windows(enabled=False)
# #     sys.exit(code)


# # if __name__ == "__main__":
# #     main()



# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# Windows-only PyQt5 "Word Goal Kiosk" for 4thewords — boot-resume w/ minimal kiosk

# State file (exact shape as requested)
#   %APPDATA%/WordKiosk/goal.json
#   {
#     "wordcount": <int REMAINING words>,
#     "isTaskCompleted": <bool>
#   }

# Behavior
# - If "isTaskCompleted" is false and "wordcount" > 0, app forces itself on top
#   (fullscreen, frameless, always-on-top) and re-focuses itself if you alt-tab away.
# - App is added to Windows autostart ONLY while unfinished; removed on completion.
# - Remaining words only go DOWN when you type more. Deletions never raise remaining.
# - On a new goal, you set the target; internally we store REMAINING in goal.json.
# - Loads https://app.4thewords.com/dashboard and counts words typed in editable areas.

# Notes
# - True OS-level lockdown (blocking Win key, Ctrl+Alt+Del, power button, etc.) isn’t
#   possible without Windows kiosk mode / policies. This is a "polite kiosk" that
#   stays on top and grabs focus frequently.
# """

# import json
# import os
# import sys
# import traceback
# from pathlib import Path

# from PyQt5 import QtCore, QtWidgets, QtGui
# from PyQt5.QtCore import Qt, QTimer, QUrl
# from PyQt5.QtWidgets import (
#     QApplication, QInputDialog, QMainWindow, QMessageBox, QWidget,
#     QLabel, QProgressBar, QVBoxLayout, QHBoxLayout, QPushButton
# )
# from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript, QWebEngineProfile

# # ----------------------------- Constants & Paths -----------------------------
# APP_NAME = "WordKiosk"
# TARGET_URL = "https://app.4thewords.com/dashboard"

# APPDATA = os.environ.get("APPDATA", str(Path.home()))
# APP_DIR = Path(APPDATA) / "WordKiosk"
# APP_DIR.mkdir(parents=True, exist_ok=True)
# STATE_PATH = APP_DIR / "goal.json"  # EXACT filename per request

# PY_EXE = sys.executable
# SCRIPT_PATH = Path(sys.argv[0]).resolve()

# # ----------------------------- Autostart (Windows) ---------------------------
# def set_autostart_windows(enabled: bool) -> None:
#     try:
#         import winreg  # type: ignore
#     except Exception:
#         return  # not Windows or no winreg

#     try:
#         key = winreg.OpenKey(
#             winreg.HKEY_CURRENT_USER,
#             r"Software\Microsoft\Windows\CurrentVersion\Run",
#             0,
#             winreg.KEY_SET_VALUE,
#         )
#     except Exception:
#         return

#     try:
#         if enabled:
#             cmd = f'"{PY_EXE}" "{SCRIPT_PATH}"'
#             winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
#         else:
#             try:
#                 winreg.DeleteValue(key, APP_NAME)
#             except FileNotFoundError:
#                 pass
#     finally:
#         try:
#             key.Close()
#         except Exception:
#             pass

# # ----------------------------- State Management ------------------------------
# def load_state():
#     # Returns dict with exactly these keys; defaults are "no task"
#     if STATE_PATH.exists():
#         try:
#             with open(STATE_PATH, "r", encoding="utf-8") as f:
#                 data = json.load(f)
#                 wc = int(max(0, int(data.get("wordcount", 0))))
#                 done = bool(data.get("isTaskCompleted", True))
#                 return {"wordcount": wc, "isTaskCompleted": done}
#         except Exception:
#             traceback.print_exc()
#     return {"wordcount": 0, "isTaskCompleted": True}

# def save_state(remaining: int, completed: bool):
#     data = {
#         "wordcount": int(max(0, remaining)),
#         "isTaskCompleted": bool(completed),
#     }
#     try:
#         with open(STATE_PATH, "w", encoding="utf-8") as f:
#             json.dump(data, f)
#     except Exception:
#         traceback.print_exc()

# # ----------------------------- Word Counter JS -------------------------------
# INJECT_JS = r"""
# (() => {
#   function countWords(s) {
#     if (!s) return 0;
#     const m = String(s).trim().match(/\b\w+\b/g);
#     return m ? m.length : 0;
#   }
#   function collectEditableText(doc) {
#     let parts = [];
#     try {
#       doc.querySelectorAll('textarea').forEach(el => parts.push(el.value || ''));
#     } catch(e){}
#     try {
#       doc.querySelectorAll('[contenteditable=""], [contenteditable="true"]').forEach(el => {
#         parts.push(el.innerText || el.textContent || '');
#       });
#     } catch(e){}
#     return parts.join(' ');
#   }
#   function computeCountAcrossFrames(win) {
#     let total = '';
#     try { total += ' ' + collectEditableText(win.document); } catch(e){}
#     try {
#       const ifr = win.document.querySelectorAll('iframe');
#       for (const f of ifr) {
#         try { if (f.contentWindow) total += ' ' + collectEditableText(f.contentWindow.document); } catch(e){}
#       }
#     } catch(e){}
#     return countWords(total);
#   }
#   function setup() {
#     if (window.__wordTrackerInstalled) return;
#     window.__wordTrackerInstalled = true;
#     const recalc = () => { try { window._writerWordCount = computeCountAcrossFrames(window); } catch(e){} };
#     const events = ['input','keyup','change','click'];
#     events.forEach(ev => window.addEventListener(ev, recalc, true));
#     setInterval(recalc, 1000);
#     recalc();
#   }
#   try { setup(); } catch(e){}
# })();
# """

# # ------------------------------- Main Window ---------------------------------
# class WordKiosk(QMainWindow):
#     def __init__(self, remaining_words: int):
#         super().__init__()
#         # Remaining words to finish THIS task (persisted in goal.json)
#         self.remaining = max(0, int(remaining_words))

#         # live word count seen in page; we use the "increase-only" delta since launch
#         self._last_live = 0
#         self._max_live = 0      # highest live count observed this run
#         self._session_gain = 0  # monotonic: increases only when live rises

#         self._allow_close = self.remaining == 0

#         self.setWindowTitle("4thewords Kiosk – Finish your remaining words")
#         self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
#         self.setWindowFlag(Qt.FramelessWindowHint, True)
#         self.setAttribute(Qt.WA_DeleteOnClose, True)

#         # Header
#         self.header = QWidget(); self.header.setObjectName("header")
#         hl = QHBoxLayout(self.header); hl.setContentsMargins(16, 12, 16, 12); hl.setSpacing(16)
#         self.lbl_goal = QLabel(f"Remaining: {self.remaining}")
#         self.lbl_live = QLabel("Live typed (this session): 0")
#         for lbl in (self.lbl_goal, self.lbl_live):
#             f = lbl.font(); f.setPointSize(14); f.setBold(True); lbl.setFont(f)
#         self.progress = QProgressBar(); self.progress.setRange(0, max(1, self.remaining)); self.progress.setValue(0); self.progress.setTextVisible(True); self.progress.setFixedHeight(28)
#         self.btn_done = QPushButton("Finish & Quit"); self.btn_done.setEnabled(self.remaining == 0); self.btn_done.clicked.connect(self.finish_and_quit)
#         hl.addWidget(self.lbl_goal); hl.addWidget(self.lbl_live); hl.addWidget(self.progress, 1); hl.addWidget(self.btn_done)

#         # Web view
#         self.web = QWebEngineView(); self.web.setContextMenuPolicy(Qt.NoContextMenu)
#         profile: QWebEngineProfile = self.web.page().profile()
#         script = QWebEngineScript()
#         script.setName("WordTrackerInject")
#         script.setInjectionPoint(QWebEngineScript.DocumentReady)
#         script.setWorldId(QWebEngineScript.MainWorld)
#         script.setRunsOnSubFrames(True)
#         script.setSourceCode(INJECT_JS)
#         profile.scripts().insert(script)
#         self.web.load(QUrl(TARGET_URL))

#         # Layout
#         central = QWidget()
#         v = QVBoxLayout(central); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
#         v.addWidget(self.header); v.addWidget(self.web, 1)
#         self.setCentralWidget(central)

#         self.apply_styles()
#         QtCore.QTimer.singleShot(0, self.showFullScreen)

#         # Polling
#         self.timer = QTimer(self); self.timer.setInterval(500); self.timer.timeout.connect(self.poll_word_count); self.timer.start()

#         # Refocus watchdog (lightweight "kiosk" feel)
#         self.refocus = QTimer(self); self.refocus.setInterval(800); self.refocus.timeout.connect(self.force_foreground_if_needed); self.refocus.start()

#         # Enforce autostart while unfinished
#         set_autostart_windows(enabled=(self.remaining > 0))
#         save_state(self.remaining, completed=(self.remaining == 0))

#     def apply_styles(self):
#         self.setStyleSheet("""
#             QWidget#header { background: #0f172a; color: #e2e8f0; border-bottom: 1px solid #1e293b; }
#             QLabel { color: #e2e8f0; }
#             QProgressBar { background: #1e293b; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; }
#             QProgressBar::chunk { background-color: #22c55e; }
#             QPushButton { background: #22c55e; color: #0f172a; border: none; padding: 8px 14px; border-radius: 8px; font-weight: 600; }
#             QPushButton:disabled { background: #334155; color: #94a3b8; }
#         """)

#     # Count words from page and update remaining (only on increases)
#     def poll_word_count(self):
#         try:
#             self.web.page().runJavaScript("Number(window._writerWordCount || 0)", self._update_counts)
#         except RuntimeError:
#             pass

#     def _update_counts(self, live_val):
#         try:
#             live = int(live_val) if live_val is not None else 0
#         except Exception:
#             live = 0

#         # Track only upward motion within this session
#         if live > self._max_live:
#             inc = live - self._max_live
#             self._session_gain += inc
#             self._max_live = live
#         # (if live drops, ignore; never reduce session_gain)

#         # Compute new remaining by subtracting session gain from the boot/start remaining
#         new_remaining = max(0, self.remaining_start() - self._session_gain)

#         # Persist if changed
#         if new_remaining != self.remaining:
#             self.remaining = new_remaining
#             save_state(self.remaining, completed=(self.remaining == 0))

#         # UI
#         self.lbl_live.setText(f"Live typed (this session): {self._session_gain}")
#         self.lbl_goal.setText(f"Remaining: {self.remaining}")
#         self.progress.setMaximum(max(1, self.remaining + self._session_gain))  # base bar on total to type this boot
#         self.progress.setValue(self._session_gain)
#         done_now = (self.remaining == 0)
#         self.btn_done.setEnabled(done_now)
#         if done_now and not self._allow_close:
#             self._allow_close = True
#             set_autostart_windows(False)
#             QMessageBox.information(self, "Great job!",
#                                     "You completed the remaining words. You may now Finish & Quit.",
#                                     QMessageBox.Ok)

#         self._last_live = live

#     def remaining_start(self):
#         """Remaining value from disk at process start (we keep it constant during run)."""
#         # We capture it once lazily and cache
#         if not hasattr(self, "_remaining_boot_snapshot"):
#             st = load_state()
#             self._remaining_boot_snapshot = int(st.get("wordcount", self.remaining))
#         return self._remaining_boot_snapshot

#     def force_foreground_if_needed(self):
#         if self._allow_close:
#             return
#         try:
#             # Bring window to front repeatedly while unfinished
#             self.raise_()
#             self.activateWindow()
#         except Exception:
#             pass

#     def keyPressEvent(self, e: QtGui.QKeyEvent):
#         if not self._allow_close:
#             if e.key() in (Qt.Key_Escape, Qt.Key_F11):
#                 return  # ignore common escape routes until finished
#         super().keyPressEvent(e)

#     def closeEvent(self, event: QtGui.QCloseEvent):
#         if self._allow_close:
#             event.accept()
#         else:
#             QMessageBox.warning(self, "Keep going!",
#                                 "You still have words remaining. Finish them to quit.",
#                                 QMessageBox.Ok)
#             event.ignore()

#     def finish_and_quit(self):
#         if self.remaining == 0:
#             self._allow_close = True
#             save_state(0, True)
#             set_autostart_windows(False)
#             self.close()

# # ----------------------------- Orchestration ----------------------------------
# def ask_new_goal_remaining(parent=None) -> int:
#     # Ask for a NEW target in words; store as remaining
#     while True:
#         goal, ok = QInputDialog.getInt(
#             parent,
#             "Set your word goal",
#             "How many words will you write?",
#             value=500, min=1, max=1_000_000
#         )
#         if not ok:
#             resp = QMessageBox.question(parent, "Exit?", "No goal set. Quit the app?",
#                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
#             if resp == QMessageBox.Yes:
#                 return -1
#             continue
#         return int(goal)

# def main():
#     if sys.platform != "win32":
#         print("This build is intended for Windows only.")

#     app = QApplication(sys.argv)
#     QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
#     QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

#     st = load_state()
#     remaining = int(st["wordcount"])
#     completed = bool(st["isTaskCompleted"])

#     if (not completed) and remaining > 0:
#         # Resume unfinished task (autostart stays ON)
#         start_remaining = remaining
#     else:
#         # Fresh task
#         g = ask_new_goal_remaining()
#         if g < 0:
#             sys.exit(0)
#         start_remaining = g
#         save_state(start_remaining, completed=False)
#         set_autostart_windows(True)

#     win = WordKiosk(start_remaining)
#     win.show()
#     code = app.exec_()

#     # On exit, if finished, ensure autostart is removed; else keep it
#     final = load_state()
#     set_autostart_windows(enabled=not final.get("isTaskCompleted", True))
#     sys.exit(code)

# if __name__ == "__main__":
#     main()




#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

        self.lbl_live.setText(f"Live (this page): {live}")
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
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if not self._allow_close and event.key() in (Qt.Key_Escape, Qt.Key_F11):
            return
        super().keyPressEvent(event)

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
