
"""
PyQt5 Word-Goal Web Kiosk for 4thewords

Features
- On launch: ask user for a word goal (integer).
- Loads https://app.4thewords.com/dashboard in a QWebEngineView.
- Injects JavaScript that watches all <textarea> and [contenteditable="true"]
  fields and maintains a live word count in window._writerWordCount.
- Polls the page for the current count and displays:
    * words typed so far
    * goal
    * remaining
  with a large progress bar.
- Kiosk-ish behavior until goal is met:
    * Fullscreen + always-on-top
    * Close/minimize disabled until goal reached (we intercept closeEvent)

Notes & Limitations
- True OS-level "cannot use anything else" kiosk mode (e.g., blocking Alt+Tab)
  is not fully enforceable from a cross-platform PyQt app. This app makes it
  harder to escape (fullscreen, always-on-top, blocked close) but cannot defeat
  all OS shortcuts.
- 4thewords may require login. The app does not handle authentication; it
  simply loads the site.
- Word counting is based only on user-editable fields on the current page. If
  the site uses an iframe/Shadow DOM for the editor, the injected script still
  attempts to capture text in subframes. You may need to adjust selectors if
  4thewords changes its editor.
"""

import sys
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
)
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript, QWebEngineProfile

TARGET_URL = "https://app.4thewords.com/dashboard"

INJECT_JS = r"""
(() => {
  // Utility: count words in a string
  function countWords(s) {
    if (!s) return 0;
    // Count sequences of letters/numbers/underscore as words.
    const m = String(s).trim().match(/\b\w+\b/g);
    return m ? m.length : 0;
  }

  // Combine text from textareas and contenteditable elements (and their frames)
  function collectEditableText(rootDoc) {
    let parts = [];

    try {
      const textareas = rootDoc.querySelectorAll('textarea');
      textareas.forEach(el => parts.push(el.value || ''));
    } catch (e) {}

    try {
      const editables = rootDoc.querySelectorAll('[contenteditable=""], [contenteditable="true"]');
      editables.forEach(el => parts.push(el.innerText || el.textContent || ''));
    } catch (e) {}

    return parts.join(' ');
  }

  function computeCountAcrossFrames(win) {
    let totalText = '';
    try {
      totalText += ' ' + collectEditableText(win.document);
    } catch (e) {}

    // Recurse into iframes
    try {
      const iframes = win.document.querySelectorAll('iframe');
      for (const f of iframes) {
        try {
          if (f.contentWindow) {
            totalText += ' ' + collectEditableText(f.contentWindow.document);
          }
        } catch (e) {
          // cross-origin; skip
        }
      }
    } catch (e) {}

    return countWords(totalText);
  }

  function setup() {
    if (window.__wordTrackerInstalled) return; // idempotent
    window.__wordTrackerInstalled = true;
    window._writerWordCount = computeCountAcrossFrames(window);

    const recalc = () => {
      try {
        window._writerWordCount = computeCountAcrossFrames(window);
      } catch (e) {
        // ignore
      }
    };

    // capture typing in as many places as possible
    window.addEventListener('input', recalc, true);
    window.addEventListener('keyup', recalc, true);
    window.addEventListener('change', recalc, true);
    window.addEventListener('click', recalc, true);

    // periodic safety update
    setInterval(recalc, 1000);

    // initial calc
    recalc();
  }

  try { setup(); } catch (e) { /* no-op */ }
})();
"""

class WordKiosk(QMainWindow):
    def __init__(self, goal_words: int):
        super().__init__()
        self.goal = max(0, int(goal_words))
        self.count = 0
        self.allow_close = self.goal == 0  # if goal 0, allow immediate close

        self.setWindowTitle("4thewords Kiosk – Word Goal")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)  # remove OS buttons
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # UI header
        self.header = QWidget()
        self.header.setObjectName("header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(16)

        self.lbl_goal = QLabel(f"Goal: {self.goal}")
        self.lbl_progress = QLabel("Written: 0")
        self.lbl_remaining = QLabel(f"Remaining: {self.goal}")

        for lbl in (self.lbl_goal, self.lbl_progress, self.lbl_remaining):
            f = lbl.font()
            f.setPointSize(14)
            f.setBold(True)
            lbl.setFont(f)

        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, self.goal))
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(28)

        # (Hidden) Quit button shown only after goal
        self.btn_quit = QPushButton("Finish & Quit")
        self.btn_quit.setEnabled(False)
        self.btn_quit.clicked.connect(self.handle_finish_quit)

        header_layout.addWidget(self.lbl_goal)
        header_layout.addWidget(self.lbl_progress)
        header_layout.addWidget(self.lbl_remaining)
        header_layout.addWidget(self.progress, 1)
        header_layout.addWidget(self.btn_quit)

        # Web view
        self.web = QWebEngineView()
        self.web.setContextMenuPolicy(Qt.NoContextMenu)

        # Apply a global profile script so it persists across navigations
        profile: QWebEngineProfile = self.web.page().profile()
        script = QWebEngineScript()
        script.setName("WordTrackerInject")
        script.setInjectionPoint(QWebEngineScript.DocumentReady)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(INJECT_JS)
        profile.scripts().insert(script)

        self.web.load(QtCore.QUrl(TARGET_URL))

        # Layout
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.header)
        v.addWidget(self.web, 1)
        self.setCentralWidget(central)

        # Poll JS variable periodically
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.poll_word_count)
        self.timer.start()

        # Style
        self.apply_styles()

        # Fullscreen after widgets are ready
        QtCore.QTimer.singleShot(0, self.showFullScreen)

    def apply_styles(self):
        self.setStyleSheet(
            """
            QWidget#header {
                background: #0f172a; /* slate-900 */
                color: #e2e8f0;      /* slate-200 */
                border-bottom: 1px solid #1e293b;
            }
            QLabel { color: #e2e8f0; }
            QProgressBar {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #e2e8f0;
            }
            QProgressBar::chunk { background-color: #22c55e; }
            QPushButton {
                background: #22c55e; color: #0f172a; border: none;
                padding: 8px 14px; border-radius: 8px; font-weight: 600;
            }
            QPushButton:disabled { background: #334155; color: #94a3b8; }
            """
        )

    def poll_word_count(self):
        # Ask the page for the current value of window._writerWordCount
        js = "Number(window._writerWordCount || 0)"
        try:
            self.web.page().runJavaScript(js, self.update_from_js)
        except RuntimeError:
            # page might be changing; ignore transient errors
            pass

    def update_from_js(self, value):
        try:
            count = int(value) if value is not None else 0
        except Exception:
            count = 0
        self.count = max(0, count)

        remaining = max(0, self.goal - self.count)
        self.lbl_progress.setText(f"Written: {self.count}")
        self.lbl_remaining.setText(f"Remaining: {remaining}")
        self.progress.setMaximum(max(1, self.goal))
        self.progress.setValue(min(self.count, self.goal))

        if not self.allow_close and self.count >= self.goal:
            self.allow_close = True
            self.btn_quit.setEnabled(True)
            QMessageBox.information(
                self,
                "Great job!",
                "You reached your word goal. You can now finish and quit.",
                QMessageBox.Ok,
            )

    def handle_finish_quit(self):
        if self.count >= self.goal:
            self.close()

    # Prevent closing until goal met
    def closeEvent(self, event: QtGui.QCloseEvent):
        if self.allow_close:
            event.accept()
        else:
            # Nudge the user back to writing
            QMessageBox.warning(
                self,
                "Keep going!",
                "You haven't reached your word goal yet. The window will stay open until you finish.",
                QMessageBox.Ok,
            )
            event.ignore()

    # Optional: also prevent Alt+F4 via key press (won't block all OS combos)
    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if not self.allow_close:
            if event.key() in (Qt.Key_Escape,):
                # Ignore Escape while locked
                return
        super().keyPressEvent(event)


def ask_goal(parent=None) -> int:
    while True:
        goal, ok = QInputDialog.getInt(
            parent,
            "Set your word goal",
            "How many words will you write today?",
            value=500,
            min=0,
            max=1_000_000,
        )
        if not ok:
            # If user cancels, confirm exit
            resp = QMessageBox.question(
                parent,
                "Exit?",
                "No goal set. Quit the app?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if resp == QMessageBox.Yes:
                return -1
            else:
                continue
        return int(goal)


def main():
    app = QApplication(sys.argv)
    # High-DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    goal = ask_goal()
    if goal < 0:
        sys.exit(0)

    win = WordKiosk(goal)
    win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
