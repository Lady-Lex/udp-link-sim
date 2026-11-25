"""Qt models and QML controller bridging PySide6 UI with EngineProcessManager."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from .. import APP_NAME, __version__
from ..config import (
    ConfigValidationError,
    Rule,
    load_rules_csv,
    parse_rule_mapping,
    save_rules_csv,
    validate_rules,
)
from ..manager import EngineProcessManager


@dataclass
class RuleRowState:
    listen_ip: str = "127.0.0.1"
    listen_port: str = "20001"
    source_ip: str = "127.0.0.1"
    source_port: str = "21001"
    target_ip: str = "127.0.0.1"
    target_port: str = "22001"
    base_ms: str = "20"
    sigma_ms: str = "0"
    loss_pct: str = "0"
    # Live stats from engine
    rx: int = 0
    tx: int = 0
    tx_rate: float = 0.0
    queued_packets: int = 0
    queued_bytes: int = 0
    loss_drops: int = 0
    overflow_drops: int = 0
    send_errors: int = 0
    discarded_on_stop: int = 0
    error_text: str = ""

    @classmethod
    def from_rule(cls, r: Rule) -> "RuleRowState":
        def _fmt(v: float) -> str:
            return str(int(v)) if v == int(v) else f"{v:g}"

        return cls(
            listen_ip=r.listen_ip,
            listen_port=str(r.listen_port),
            source_ip=r.source_ip,
            source_port=str(r.source_port),
            target_ip=r.target_ip,
            target_port=str(r.target_port),
            base_ms=_fmt(r.base_ms),
            sigma_ms=_fmt(r.sigma_ms),
            loss_pct=_fmt(r.loss_pct),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "listen_ip": self.listen_ip,
            "listen_port": self.listen_port,
            "source_ip": self.source_ip,
            "source_port": self.source_port,
            "target_ip": self.target_ip,
            "target_port": self.target_port,
            "base_ms": self.base_ms,
            "sigma_ms": self.sigma_ms,
            "loss_pct": self.loss_pct,
        }


class RuleListModel(QAbstractListModel):
    """List model for QML live rule table."""

    RowIndexRole = Qt.UserRole + 1
    ListenIpRole = Qt.UserRole + 2
    ListenPortRole = Qt.UserRole + 3
    SourceIpRole = Qt.UserRole + 4
    SourcePortRole = Qt.UserRole + 5
    TargetIpRole = Qt.UserRole + 6
    TargetPortRole = Qt.UserRole + 7
    BaseMsRole = Qt.UserRole + 8
    SigmaMsRole = Qt.UserRole + 9
    LossPctRole = Qt.UserRole + 10
    RxRole = Qt.UserRole + 11
    TxRole = Qt.UserRole + 12
    TxRateRole = Qt.UserRole + 13
    QueuedPacketsRole = Qt.UserRole + 14
    QueuedBytesRole = Qt.UserRole + 15
    LossDropsRole = Qt.UserRole + 16
    OverflowDropsRole = Qt.UserRole + 17
    SendErrorsRole = Qt.UserRole + 18
    ErrorTextRole = Qt.UserRole + 19

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[RuleRowState] = []

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.RowIndexRole: b"rowIndex",
            self.ListenIpRole: b"listenIp",
            self.ListenPortRole: b"listenPort",
            self.SourceIpRole: b"sourceIp",
            self.SourcePortRole: b"sourcePort",
            self.TargetIpRole: b"targetIp",
            self.TargetPortRole: b"targetPort",
            self.BaseMsRole: b"baseMs",
            self.SigmaMsRole: b"sigmaMs",
            self.LossPctRole: b"lossPct",
            self.RxRole: b"rx",
            self.TxRole: b"tx",
            self.TxRateRole: b"txRate",
            self.QueuedPacketsRole: b"queuedPackets",
            self.QueuedBytesRole: b"queuedBytes",
            self.LossDropsRole: b"lossDrops",
            self.OverflowDropsRole: b"overflowDrops",
            self.SendErrorsRole: b"sendErrors",
            self.ErrorTextRole: b"errorText",
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        mapping = {
            self.RowIndexRole: index.row() + 1,
            self.ListenIpRole: r.listen_ip,
            self.ListenPortRole: r.listen_port,
            self.SourceIpRole: r.source_ip,
            self.SourcePortRole: r.source_port,
            self.TargetIpRole: r.target_ip,
            self.TargetPortRole: r.target_port,
            self.BaseMsRole: r.base_ms,
            self.SigmaMsRole: r.sigma_ms,
            self.LossPctRole: r.loss_pct,
            self.RxRole: r.rx,
            self.TxRole: r.tx,
            self.TxRateRole: round(r.tx_rate, 1),
            self.QueuedPacketsRole: r.queued_packets,
            self.QueuedBytesRole: r.queued_bytes,
            self.LossDropsRole: r.loss_drops,
            self.OverflowDropsRole: r.overflow_drops,
            self.SendErrorsRole: r.send_errors,
            self.ErrorTextRole: r.error_text,
        }
        return mapping.get(role)

    def rows(self) -> list[RuleRowState]:
        return self._rows

    def set_rows(self, rows: list[RuleRowState]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        self.countChanged.emit()

    def append_row(self, row: RuleRowState) -> int:
        idx = len(self._rows)
        self.beginInsertRows(QModelIndex(), idx, idx)
        self._rows.append(row)
        self.endInsertRows()
        self.countChanged.emit()
        return idx

    def insert_row(self, idx: int, row: RuleRowState) -> int:
        idx = max(0, min(idx, len(self._rows)))
        self.beginInsertRows(QModelIndex(), idx, idx)
        self._rows.insert(idx, row)
        self.endInsertRows()
        self.countChanged.emit()
        return idx

    def remove_row(self, idx: int) -> None:
        if not (0 <= idx < len(self._rows)):
            return
        self.beginRemoveRows(QModelIndex(), idx, idx)
        self._rows.pop(idx)
        self.endRemoveRows()
        self.countChanged.emit()

    def notify_row_changed(self, idx: int) -> None:
        if 0 <= idx < len(self._rows):
            mi = self.index(idx, 0)
            self.dataChanged.emit(mi, mi)

    def notify_all_changed(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, 0))


class ListenerListModel(QAbstractListModel):
    """List model for per-listener diagnostics in bottom pane."""

    ListenRole = Qt.UserRole + 1
    UnmatchedRole = Qt.UserRole + 2
    LastUnmatchedPeerRole = Qt.UserRole + 3
    Wsa10054Role = Qt.UserRole + 4
    RecvErrorsRole = Qt.UserRole + 5

    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._items)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ListenRole: b"listen",
            self.UnmatchedRole: b"unmatched",
            self.LastUnmatchedPeerRole: b"lastUnmatchedPeer",
            self.Wsa10054Role: b"wsa10054",
            self.RecvErrorsRole: b"recvErrors",
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        if role == self.ListenRole:
            return it.get("listen", "")
        if role == self.UnmatchedRole:
            return int(it.get("unmatched_packets", 0))
        if role == self.LastUnmatchedPeerRole:
            return it.get("last_unmatched_peer", "") or "-"
        if role == self.Wsa10054Role:
            return int(it.get("wsa10054", 0))
        if role == self.RecvErrorsRole:
            return int(it.get("recv_errors", 0))
        return None

    def update_items(self, items: list[dict[str, Any]]) -> None:
        if len(items) == len(self._items):
            self._items = list(items)
            if self._items:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(self._items) - 1, 0)
                )
        else:
            self.beginResetModel()
            self._items = list(items)
            self.endResetModel()
            self.countChanged.emit()


class AppController(QObject):
    """Main QML controller managing rules, CSV I/O, theme, engine lifecycle, and 250ms stats."""

    configPathChanged = Signal()
    unsavedChangesChanged = Signal()
    pendingApplyChanged = Signal()
    darkModeChanged = Signal()
    selectedIndexChanged = Signal()
    engineStateChanged = Signal()
    validationChanged = Signal()
    totalsChanged = Signal()
    logsChanged = Signal()

    # Internal thread-safe bridge signals from EngineProcessManager background threads
    _statsReceived = Signal(dict)
    _stateReceived = Signal(str, str)
    _logReceived = Signal(str)

    def __init__(self, initial_config: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rules_model = RuleListModel(self)
        self._listeners_model = ListenerListModel(self)

        self._config_path = ""
        self._unsaved_changes = False
        self._pending_apply = False
        self._dark_mode = False
        self._selected_index = -1

        self._engine_running = False
        self._engine_state = "stopped"
        self._engine_status_text = "引擎已停止"
        self._engine_pid = 0
        self._timer_mode = "-"
        self._uptime_s = 0.0
        self._last_discarded_pending = 0
        self._validation_error = ""
        self._applied_rules: list[Rule] = []
        self._logs: list[str] = []

        self._totals: dict[str, Any] = {
            "rx": 0,
            "tx": 0,
            "tx_rate": 0.0,
            "queued_packets": 0,
            "queued_bytes": 0,
            "loss_drops": 0,
            "overflow_drops": 0,
            "send_errors": 0,
            "discarded_on_stop": 0,
            "unmatched_packets": 0,
            "wsa10054": 0,
        }

        self._statsReceived.connect(self._handle_stats)
        self._stateReceived.connect(self._handle_state)
        self._logReceived.connect(self._append_log)

        self._manager = EngineProcessManager(
            on_stats=lambda s: self._statsReceived.emit(s),
            on_state=lambda st, msg: self._stateReceived.emit(st, msg),
            on_log=lambda msg: self._logReceived.emit(msg),
            stats_ms=250,
            spin_us=500,
        )

        self._append_log(f"{APP_NAME} v{__version__} 已就绪")
        if initial_config:
            self.importCsv(initial_config)

    # --- Properties ---
    @Property(str, constant=True)
    def appTitle(self) -> str:
        return f"{APP_NAME} v{__version__}"

    @Property(QObject, constant=True)
    def rulesModel(self) -> RuleListModel:
        return self._rules_model

    @Property(QObject, constant=True)
    def listenersModel(self) -> ListenerListModel:
        return self._listeners_model

    @Property(str, notify=configPathChanged)
    def configPath(self) -> str:
        return self._config_path

    @Property(bool, notify=unsavedChangesChanged)
    def hasUnsavedChanges(self) -> bool:
        return self._unsaved_changes

    @Property(bool, notify=pendingApplyChanged)
    def hasPendingApply(self) -> bool:
        return self._pending_apply

    @Property(bool, notify=darkModeChanged)
    def darkMode(self) -> bool:
        return self._dark_mode

    @darkMode.setter
    def darkMode(self, value: bool) -> None:
        val = bool(value)
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()

    @Property(int, notify=selectedIndexChanged)
    def selectedIndex(self) -> int:
        return self._selected_index

    @selectedIndex.setter
    def selectedIndex(self, value: int) -> None:
        count = self._rules_model.rowCount()
        clamped = value if 0 <= value < count else (-1 if count == 0 else count - 1)
        if self._selected_index != clamped:
            self._selected_index = clamped
            self.selectedIndexChanged.emit()

    @Property(bool, notify=engineStateChanged)
    def engineRunning(self) -> bool:
        return self._engine_running

    @Property(str, notify=engineStateChanged)
    def engineState(self) -> str:
        return self._engine_state

    @Property(str, notify=engineStateChanged)
    def engineStatusText(self) -> str:
        return self._engine_status_text

    @Property(int, notify=engineStateChanged)
    def enginePid(self) -> int:
        return self._engine_pid

    @Property(str, notify=engineStateChanged)
    def timerMode(self) -> str:
        return self._timer_mode

    @Property(float, notify=totalsChanged)
    def uptimeSeconds(self) -> float:
        return self._uptime_s

    @Property(int, notify=engineStateChanged)
    def lastDiscardedPending(self) -> int:
        return self._last_discarded_pending

    @Property(str, notify=validationChanged)
    def validationError(self) -> str:
        return self._validation_error

    @Property(bool, notify=validationChanged)
    def isValid(self) -> bool:
        return self._validation_error == "" and self._rules_model.rowCount() > 0

    @Property("QVariantMap", notify=totalsChanged)
    def totals(self) -> dict[str, Any]:
        return dict(self._totals)

    @Property(str, notify=logsChanged)
    def logText(self) -> str:
        return "\n".join(self._logs)

    # --- Helpers ---
    def _normalize_path(self, path_or_url: str) -> str:
        s = path_or_url.strip()
        if s.startswith("file:"):
            return QUrl(s).toLocalFile()
        return s

    def _set_unsaved(self, val: bool) -> None:
        if self._unsaved_changes != val:
            self._unsaved_changes = val
            self.unsavedChangesChanged.emit()

    def _set_pending_apply(self, val: bool) -> None:
        if self._pending_apply != val:
            self._pending_apply = val
            self.pendingApplyChanged.emit()

    def _revalidate(self) -> list[Rule] | None:
        rows = self._rules_model.rows()
        parsed_rules: list[Rule] = []
        seen_keys: dict[tuple[str, int, str, int], int] = {}
        first_error = ""

        for idx, row in enumerate(rows):
            row.error_text = ""
            try:
                rule = parse_rule_mapping(row.to_mapping(), label=f"第 {idx + 1} 条规则")
            except ValueError as exc:
                row.error_text = str(exc)
                if not first_error:
                    first_error = row.error_text
                continue

            key = (rule.listen_ip, rule.listen_port, rule.source_ip, rule.source_port)
            if key in seen_keys:
                prev = seen_keys[key] + 1
                row.error_text = f"与第 {prev} 条规则存在重复/歧义匹配"
                if not first_error:
                    first_error = f"第 {idx + 1} 条规则: {row.error_text}"
                continue
            seen_keys[key] = idx
            parsed_rules.append(rule)

        self._rules_model.notify_all_changed()

        if not rows:
            first_error = "请至少添加一条转发规则"

        if self._validation_error != first_error:
            self._validation_error = first_error
            self.validationChanged.emit()
        else:
            # Ensure isValid updates when count toggles 0 <-> >0
            self.validationChanged.emit()

        if first_error:
            return None
        if self._engine_running:
            self._set_pending_apply(parsed_rules != self._applied_rules)
        return parsed_rules

    @Slot(str)
    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._logs.append(f"[{ts}] {msg}")
        if len(self._logs) > 300:
            self._logs = self._logs[-300:]
        self.logsChanged.emit()

    @Slot(dict)
    def _handle_stats(self, snap: dict[str, Any]) -> None:
        self._uptime_s = float(snap.get("uptime_s", 0.0))
        if snap.get("timer_mode"):
            self._timer_mode = str(snap["timer_mode"])
        totals = snap.get("totals")
        if isinstance(totals, dict):
            self._totals = dict(totals)
        rules_stats = snap.get("rules")
        if isinstance(rules_stats, list):
            rows = self._rules_model.rows()
            # Map stats by rule index when rule counts match active engine
            if len(rules_stats) == len(rows):
                for st in rules_stats:
                    i = int(st.get("index", -1))
                    if 0 <= i < len(rows):
                        r = rows[i]
                        r.rx = int(st.get("rx", 0))
                        r.tx = int(st.get("tx", 0))
                        r.tx_rate = float(st.get("tx_rate", 0.0))
                        r.queued_packets = int(st.get("queued_packets", 0))
                        r.queued_bytes = int(st.get("queued_bytes", 0))
                        r.loss_drops = int(st.get("loss_drops", 0))
                        r.overflow_drops = int(st.get("overflow_drops", 0))
                        r.send_errors = int(st.get("send_errors", 0))
                self._rules_model.notify_all_changed()
        listeners = snap.get("listeners")
        if isinstance(listeners, list):
            self._listeners_model.update_items(listeners)
        self.totalsChanged.emit()

    @Slot(str, str)
    def _handle_state(self, state: str, message: str) -> None:
        self._engine_state = state
        self._engine_running = state == "running"
        self._engine_status_text = message
        self._engine_pid = self._manager.pid
        self._last_discarded_pending = self._manager.last_discarded_pending
        if self._engine_running:
            info = self._manager.ready_info
            if info.get("timer_mode"):
                self._timer_mode = str(info["timer_mode"])
        else:
            self._set_pending_apply(False)
        self.engineStateChanged.emit()

    # --- QML Slots ---
    @Slot()
    def toggleTheme(self) -> None:
        self.darkMode = not self._dark_mode

    @Slot(int, result="QVariantMap")
    def getRule(self, index: int) -> dict[str, Any]:
        rows = self._rules_model.rows()
        if not (0 <= index < len(rows)):
            return {}
        r = rows[index]
        return {
            "listenIp": r.listen_ip,
            "listenPort": r.listen_port,
            "sourceIp": r.source_ip,
            "sourcePort": r.source_port,
            "targetIp": r.target_ip,
            "targetPort": r.target_port,
            "baseMs": r.base_ms,
            "sigmaMs": r.sigma_ms,
            "lossPct": r.loss_pct,
            "errorText": r.error_text,
        }

    @Slot(
        int, str, str, str, str, str, str, str, str, str, result=bool
    )
    def updateRule(
        self,
        index: int,
        listen_ip: str,
        listen_port: str,
        source_ip: str,
        source_port: str,
        target_ip: str,
        target_port: str,
        base_ms: str,
        sigma_ms: str,
        loss_pct: str,
    ) -> bool:
        rows = self._rules_model.rows()
        if not (0 <= index < len(rows)):
            return False
        r = rows[index]
        r.listen_ip = listen_ip.strip()
        r.listen_port = listen_port.strip()
        r.source_ip = source_ip.strip()
        r.source_port = source_port.strip()
        r.target_ip = target_ip.strip()
        r.target_port = target_port.strip()
        r.base_ms = base_ms.strip()
        r.sigma_ms = sigma_ms.strip()
        r.loss_pct = loss_pct.strip() if loss_pct.strip() != "" else "0"
        self._set_unsaved(True)
        if self._engine_running:
            self._set_pending_apply(True)
        valid = self._revalidate() is not None
        return valid

    @Slot()
    def addRule(self) -> None:
        # Pick non-colliding loopback defaults for convenient editing
        used_sources = {
            (r.listen_ip, r.listen_port, r.source_ip, r.source_port)
            for r in self._rules_model.rows()
        }
        listen_port = 20001
        source_port = 21001
        target_port = 22001
        while (
            "127.0.0.1",
            str(listen_port),
            "127.0.0.1",
            str(source_port),
        ) in used_sources:
            source_port += 1
            target_port += 1

        new_row = RuleRowState(
            listen_ip="127.0.0.1",
            listen_port=str(listen_port),
            source_ip="127.0.0.1",
            source_port=str(source_port),
            target_ip="127.0.0.1",
            target_port=str(target_port),
            base_ms="20",
            sigma_ms="0",
            loss_pct="0",
        )
        idx = self._rules_model.append_row(new_row)
        self.selectedIndex = idx
        self._set_unsaved(True)
        if self._engine_running:
            self._set_pending_apply(True)
        self._revalidate()
        self._append_log(f"已新增第 {idx + 1} 条规则")

    @Slot(int)
    def duplicateRule(self, index: int) -> None:
        rows = self._rules_model.rows()
        if not (0 <= index < len(rows)):
            return
        src = rows[index]
        # Suggest incremented source_port so duplicate is immediately usable (unless 0)
        try:
            sp = int(src.source_port)
            next_sp = str(sp + 1 if 0 < sp < 65535 else sp)
        except ValueError:
            next_sp = src.source_port

        dup = RuleRowState(
            listen_ip=src.listen_ip,
            listen_port=src.listen_port,
            source_ip=src.source_ip,
            source_port=next_sp,
            target_ip=src.target_ip,
            target_port=src.target_port,
            base_ms=src.base_ms,
            sigma_ms=src.sigma_ms,
            loss_pct=src.loss_pct,
        )
        new_idx = self._rules_model.insert_row(index + 1, dup)
        self.selectedIndex = new_idx
        self._set_unsaved(True)
        if self._engine_running:
            self._set_pending_apply(True)
        self._revalidate()
        self._append_log(f"已复制规则到第 {new_idx + 1} 行")

    @Slot(int)
    def deleteRule(self, index: int) -> None:
        rows = self._rules_model.rows()
        if not (0 <= index < len(rows)):
            return
        self._rules_model.remove_row(index)
        new_count = self._rules_model.rowCount()
        if new_count == 0:
            self._selected_index = -1
        else:
            self._selected_index = min(index, new_count - 1)
        self.selectedIndexChanged.emit()
        self._set_unsaved(True)
        if self._engine_running:
            self._set_pending_apply(True)
        self._revalidate()
        self._append_log(f"已删除第 {index + 1} 条规则")

    @Slot(str, result=bool)
    def importCsv(self, path_or_url: str) -> bool:
        path = self._normalize_path(path_or_url)
        if not path:
            return False
        try:
            rules = load_rules_csv(path, require_non_empty=True)
        except (FileNotFoundError, ConfigValidationError, OSError) as exc:
            self._append_log(f"导入失败 ({path}): {exc}")
            self._validation_error = str(exc)
            self.validationChanged.emit()
            return False

        self._rules_model.set_rows([RuleRowState.from_rule(r) for r in rules])
        self._config_path = str(Path(path).resolve())
        self.configPathChanged.emit()
        self._set_unsaved(False)
        self._selected_index = 0 if rules else -1
        self.selectedIndexChanged.emit()
        self._revalidate()
        if self._engine_running:
            self._set_pending_apply(True)
        self._append_log(f"已导入 {len(rules)} 条规则: {self._config_path}")
        return True

    @Slot(result=bool)
    def saveCsv(self) -> bool:
        if not self._config_path:
            self._append_log("请先通过「另存为」选择保存路径")
            return False
        return self.saveCsvAs(self._config_path)

    @Slot(str, result=bool)
    def saveCsvAs(self, path_or_url: str) -> bool:
        path = self._normalize_path(path_or_url)
        if not path:
            return False
        validated = self._revalidate()
        if validated is None:
            self._append_log(f"保存失败: 规则校验未通过 ({self._validation_error})")
            return False
        try:
            saved = save_rules_csv(path, validated, include_loss_column=True)
        except (ConfigValidationError, OSError) as exc:
            self._append_log(f"保存失败 ({path}): {exc}")
            return False
        self._config_path = str(saved.resolve())
        self.configPathChanged.emit()
        self._set_unsaved(False)
        self._append_log(f"已保存 {len(validated)} 条规则至: {self._config_path}")
        return True

    @Slot(result=bool)
    def applyAndRestart(self) -> bool:
        validated = self._revalidate()
        if validated is None:
            self._append_log(f"无法应用: {self._validation_error}")
            return False
        try:
            was_running = self._manager.is_running
            discarded, info = self._manager.restart_rules(validated)
            self._applied_rules = list(validated)
            self._last_discarded_pending = discarded
            self._timer_mode = str(info.get("timer_mode", "-"))
            self._set_pending_apply(False)
            # Clear displayed per-rule counters for fresh engine run
            for r in self._rules_model.rows():
                r.rx = r.tx = r.queued_packets = r.queued_bytes = 0
                r.loss_drops = r.overflow_drops = r.send_errors = 0
                r.tx_rate = 0.0
            self._rules_model.notify_all_changed()
            self._listeners_model.update_items([])
            action = "已重启引擎并应用配置" if was_running else "已启动引擎"
            self._append_log(
                f"{action} (PID={info.get('pid')}, 丢弃旧在途包={discarded})"
            )
            self.engineStateChanged.emit()
            return True
        except Exception as exc:
            self._append_log(f"引擎启动/应用失败: {exc}")
            self._handle_state("error", str(exc))
            return False

    @Slot()
    def stopEngine(self) -> None:
        if not self._manager.is_running:
            return
        discarded = self._manager.stop()
        self._last_discarded_pending = discarded
        self._applied_rules = []
        self._set_pending_apply(False)
        self._append_log(f"引擎已停止，丢弃在途包={discarded}")
        self.engineStateChanged.emit()

    @Slot()
    def resetStats(self) -> None:
        self._manager.reset_stats()
        for r in self._rules_model.rows():
            r.rx = r.tx = r.loss_drops = r.overflow_drops = r.send_errors = 0
            r.tx_rate = 0.0
        self._rules_model.notify_all_changed()
        self._append_log("已清零统计计数")

    @Slot()
    def clearLogs(self) -> None:
        self._logs.clear()
        self.logsChanged.emit()

    def shutdown(self) -> None:
        self._manager.close()
