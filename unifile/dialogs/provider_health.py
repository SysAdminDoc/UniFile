"""Provider health dashboard with local metrics and an off-GUI probe worker."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from unifile.config import get_active_stylesheet, get_active_theme
from unifile.dialogs.common import build_dialog_header


class LatencySparkline(QWidget):
    """Small pointer-free latency chart used in the provider table."""

    def __init__(self, values=None, theme=None, parent=None):
        super().__init__(parent)
        self._values = list(values or [])
        self._theme = theme or get_active_theme()
        self.setMinimumSize(130, 34)
        self.setMaximumHeight(40)
        self.setAccessibleName("Provider latency trend")

    def set_values(self, values):
        self._values = list(values or [])
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(5, 5, -5, -5)
        if not self._values:
            painter.setPen(QPen(QColor(self._theme['muted'])))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No samples")
            painter.end()
            return

        values = [max(0.0, float(value)) for value in self._values[-30:]]
        low = min(values)
        high = max(values)
        span = max(high - low, 1.0)
        path = QPainterPath()
        for index, value in enumerate(values):
            x = rect.left() if len(values) == 1 else rect.left() + (
                rect.width() * index / (len(values) - 1)
            )
            y = rect.bottom() - ((value - low) / span) * rect.height()
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(QColor(self._theme['accent']), 2))
        painter.drawPath(path)
        if len(values) == 1:
            painter.setBrush(QColor(self._theme['accent']))
            painter.drawEllipse(path.currentPosition(), 2.5, 2.5)
        painter.end()


class _ProviderProbeWorker(QThread):
    """Run provider reachability probes without blocking the settings dialog."""

    progress = pyqtSignal(str)

    def __init__(self, providers: dict, parent=None):
        super().__init__(parent)
        self._providers = providers

    def run(self):
        from unifile.ai_providers import AIProvider

        for provider_id, config in self._providers.items():
            if self.isInterruptionRequested():
                break
            if not config.get('enabled', False):
                continue
            name = config.get('name', provider_id)
            self.progress.emit(f"Checking {name}…")
            provider = AIProvider(config, provider_id=provider_id)
            available = provider.is_available()
            self.progress.emit(
                f"{name}: {'reachable' if available else 'unreachable'}"
            )


class ProviderHealthDialog(QDialog):
    """Show local latency, reliability, token usage, cost, and recent trend."""

    _HEADERS = (
        "Provider", "Status", "Avg latency", "Error rate", "Tokens in / out",
        "Estimated cost", "Recent latency",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Provider Health")
        self.setMinimumSize(980, 580)
        self.setStyleSheet(get_active_stylesheet())
        self._providers = {}
        self._worker = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        theme = get_active_theme()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(build_dialog_header(
            theme,
            "Observability",
            "AI Provider Health",
            "Local-only request history for configured providers. No metrics or credentials leave this device.",
        ))

        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        layout.addWidget(self.lbl_summary)

        actions = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload saved health samples without contacting providers.")
        self.btn_refresh.clicked.connect(self.refresh)
        actions.addWidget(self.btn_refresh)
        self.btn_probe = QPushButton("Probe Enabled Providers")
        self.btn_probe.setProperty("class", "primary")
        self.btn_probe.setToolTip("Run a short reachability check in the background.")
        self.btn_probe.clicked.connect(self._start_probe)
        actions.addWidget(self.btn_probe)
        self.btn_clear = QPushButton("Clear History")
        self.btn_clear.clicked.connect(self._clear_history)
        actions.addWidget(self.btn_clear)
        self.lbl_probe = QLabel()
        self.lbl_probe.setStyleSheet(f"color: {theme['muted']}; font-size: 11px;")
        actions.addWidget(self.lbl_probe, 1)
        layout.addLayout(actions)

        self.table = QTableWidget(0, len(self._HEADERS))
        self.table.setHorizontalHeaderLabels(self._HEADERS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 105)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 135)
        self.table.setColumnWidth(5, 125)
        self.table.setAccessibleName("AI provider health metrics")
        layout.addWidget(self.table, 1)

        footer = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        footer.rejected.connect(self.reject)
        layout.addWidget(footer)

    @staticmethod
    def _item(text: str, color: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if color:
            item.setForeground(QColor(color))
        return item

    def refresh(self):
        from unifile.ai_providers import load_providers, provider_health_snapshot

        self._providers = load_providers()
        snapshot = provider_health_snapshot(self._providers)
        ordered = sorted(
            snapshot.items(),
            key=lambda pair: (int(self._providers.get(pair[0], {}).get('priority', 99)), pair[0]),
        )
        self.table.setRowCount(len(ordered))
        theme = get_active_theme()
        total_requests = 0
        total_errors = 0
        total_tokens = 0
        for row, (provider_id, metrics) in enumerate(ordered):
            total_requests += metrics['request_count']
            total_errors += metrics['error_count']
            total_tokens += metrics['total_tokens']
            enabled = metrics['enabled']
            if not enabled:
                status, color = "Disabled", theme['muted']
            elif not metrics['request_count']:
                status, color = "Not tested", theme['muted']
            elif metrics['last_ok']:
                status, color = "Healthy", theme['green']
            else:
                status, color = "Error", '#ef4444'
            latency = (
                f"{metrics['avg_latency_ms']:,.0f} ms"
                if metrics['request_count'] else "—"
            )
            tokens = f"{metrics['input_tokens']:,} / {metrics['output_tokens']:,}"
            if metrics['total_tokens'] and metrics['estimated_cost']:
                cost = f"${metrics['estimated_cost']:,.4f}"
            elif metrics['total_tokens']:
                cost = "Rate not set"
            else:
                cost = "—"
            self.table.setItem(row, 0, self._item(metrics['name']))
            self.table.setItem(row, 1, self._item(status, color))
            self.table.setItem(row, 2, self._item(latency))
            self.table.setItem(row, 3, self._item(f"{metrics['error_rate']:.1f}%"))
            self.table.setItem(row, 4, self._item(tokens))
            self.table.setItem(row, 5, self._item(cost))
            latencies = [sample.get('latency_ms', 0) for sample in metrics['samples']]
            self.table.setCellWidget(row, 6, LatencySparkline(latencies, theme))
            self.table.setRowHeight(row, 42)

        enabled_count = sum(1 for metrics in snapshot.values() if metrics['enabled'])
        error_rate = (total_errors / total_requests * 100) if total_requests else 0.0
        self.lbl_summary.setText(
            f"{enabled_count} enabled provider(s) · {total_requests:,} recorded request(s) · "
            f"{total_tokens:,} token(s) · {error_rate:.1f}% overall error rate"
        )

    def _start_probe(self):
        if self._worker is not None and self._worker.isRunning():
            return
        from unifile.ai_providers import load_providers

        self._providers = load_providers()
        self.btn_refresh.setEnabled(False)
        self.btn_probe.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.lbl_probe.setText("Checking enabled providers…")
        self._worker = _ProviderProbeWorker(self._providers)
        self._worker.progress.connect(self.lbl_probe.setText)
        self._worker.finished.connect(self._probe_finished)
        self._worker.start()

    def _probe_finished(self):
        self.btn_refresh.setEnabled(True)
        self.btn_probe.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.lbl_probe.setText("Probe complete")
        self.refresh()

    def _clear_history(self):
        answer = QMessageBox.question(
            self,
            "Clear Provider History",
            "Delete all locally saved provider health samples?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from unifile.ai_providers import clear_provider_health

        if clear_provider_health():
            self.lbl_probe.setText("History cleared")
            self.refresh()
        else:
            self.lbl_probe.setText("Could not clear history")

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(6000)
        super().closeEvent(event)


__all__ = ['LatencySparkline', 'ProviderHealthDialog']
