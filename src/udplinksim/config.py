"""CSV configuration model, parsing, validation, and atomic persistence."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Iterable, Sequence

REQUIRED_COLUMNS = (
    "listen_ip",
    "listen_port",
    "source_ip",
    "source_port",
    "target_ip",
    "target_port",
    "base_ms",
    "sigma_ms",
)
OPTIONAL_COLUMNS = ("loss_pct",)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class ConfigValidationError(ValueError):
    """Raised when one or more rules fail validation."""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Rule:
    listen_ip: str
    listen_port: int
    source_ip: str
    source_port: int
    target_ip: str
    target_port: int
    base_ms: float
    sigma_ms: float
    loss_pct: float = 0.0

    @property
    def listen_endpoint(self) -> tuple[str, int]:
        return (self.listen_ip, self.listen_port)

    @property
    def source_endpoint(self) -> tuple[str, int]:
        return (self.source_ip, self.source_port)

    @property
    def target_endpoint(self) -> tuple[str, int]:
        return (self.target_ip, self.target_port)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Rule":
        return parse_rule_mapping(data)


def _parse_ipv4(value: object, field_name: str, label: str) -> str:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        raise ValueError(f"{label}: {field_name} 不能为空")
    try:
        addr = IPv4Address(raw)
    except Exception as exc:
        raise ValueError(f"{label}: 无效的 IPv4 地址 {field_name}={raw!r}") from exc
    ip_str = str(addr)
    if ip_str == "0.0.0.0":
        raise ValueError(f"{label}: {field_name} 不能使用未指定地址 0.0.0.0")
    return ip_str


def _parse_port(value: object, field_name: str, min_port: int, label: str) -> int:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        raise ValueError(f"{label}: {field_name} 不能为空")
    try:
        # Reject floats like "123.4" or bools
        if isinstance(value, bool):
            raise ValueError("bool not allowed")
        port = int(raw)
        if str(port) != raw and int(float(raw)) != port:
            raise ValueError("non-integer")
    except Exception as exc:
        raise ValueError(f"{label}: 无效的端口 {field_name}={raw!r}") from exc
    if not (min_port <= port <= 65535):
        raise ValueError(
            f"{label}: {field_name} 超出范围 ({min_port}..65535): {port}"
        )
    return port


def _parse_float(
    value: object,
    field_name: str,
    min_val: float,
    max_val: float | None,
    label: str,
    default: float | None = None,
) -> float:
    raw = str(value).strip() if value is not None else ""
    if raw == "":
        if default is not None:
            return default
        raise ValueError(f"{label}: {field_name} 不能为空")
    try:
        if isinstance(value, bool):
            raise ValueError("bool not allowed")
        num = float(raw)
    except Exception as exc:
        raise ValueError(f"{label}: 无效数值 {field_name}={raw!r}") from exc
    if not math.isfinite(num):
        raise ValueError(f"{label}: {field_name} 必须为有限数值")
    if num < min_val:
        raise ValueError(f"{label}: {field_name} 不能小于 {min_val}: {num}")
    if max_val is not None and num > max_val:
        raise ValueError(f"{label}: {field_name} 不能大于 {max_val}: {num}")
    return num


def parse_rule_mapping(row: dict[str, object], label: str = "规则") -> Rule:
    """Parse and validate a single rule mapping (CSV row or dict)."""
    listen_ip = _parse_ipv4(row.get("listen_ip"), "listen_ip", label)
    listen_port = _parse_port(row.get("listen_port"), "listen_port", 1, label)
    source_ip = _parse_ipv4(row.get("source_ip"), "source_ip", label)
    source_port = _parse_port(row.get("source_port"), "source_port", 0, label)
    target_ip = _parse_ipv4(row.get("target_ip"), "target_ip", label)
    target_port = _parse_port(row.get("target_port"), "target_port", 1, label)
    base_ms = _parse_float(row.get("base_ms"), "base_ms", 0.0, None, label)
    sigma_ms = _parse_float(row.get("sigma_ms"), "sigma_ms", 0.0, None, label)
    loss_pct = _parse_float(
        row.get("loss_pct"), "loss_pct", 0.0, 100.0, label, default=0.0
    )

    listen_ep = (listen_ip, listen_port)
    source_ep = (source_ip, source_port)
    target_ep = (target_ip, target_port)

    if listen_ep == source_ep or listen_ep == target_ep or source_ep == target_ep:
        raise ValueError(
            f"{label}: listen/source/target 必须为互不相同的具体端点 "
            f"(listen={listen_ip}:{listen_port}, source={source_ip}:{source_port}, "
            f"target={target_ip}:{target_port})"
        )

    return Rule(
        listen_ip=listen_ip,
        listen_port=listen_port,
        source_ip=source_ip,
        source_port=source_port,
        target_ip=target_ip,
        target_port=target_port,
        base_ms=base_ms,
        sigma_ms=sigma_ms,
        loss_pct=loss_pct,
    )


def validate_rules(
    rules: Sequence[Rule], *, require_non_empty: bool = True
) -> list[Rule]:
    """Validate a sequence of Rule objects and check for ambiguous duplicates."""
    errors: list[str] = []
    normalized: list[Rule] = []
    seen_keys: dict[tuple[str, int, str, int], int] = {}

    for idx, rule in enumerate(rules, start=1):
        label = f"第 {idx} 条规则"
        try:
            norm = parse_rule_mapping(rule.to_dict(), label=label)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        key = (norm.listen_ip, norm.listen_port, norm.source_ip, norm.source_port)
        if key in seen_keys:
            prev_idx = seen_keys[key]
            errors.append(
                f"{label}: 与第 {prev_idx} 条规则存在重复/歧义匹配 "
                f"(listener={norm.listen_ip}:{norm.listen_port}, "
                f"source={norm.source_ip}:{norm.source_port})"
            )
            continue
        seen_keys[key] = idx
        normalized.append(norm)

    if require_non_empty and not normalized and not errors:
        errors.append("规则列表不能为空")

    if errors:
        raise ConfigValidationError(errors)
    return normalized


def load_rules_csv(path: str | os.PathLike[str], *, require_non_empty: bool = True) -> list[Rule]:
    """Load and validate rules from a CSV file (compatible with legacy 8-col and 9-col CSV)."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {file_path}")

    errors: list[str] = []
    parsed: list[Rule] = []
    seen_keys: dict[tuple[str, int, str, int], int] = {}

    with file_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ConfigValidationError(["CSV 文件为空或缺少表头"])
        clean_fields = [f.strip() if f is not None else "" for f in reader.fieldnames]
        reader.fieldnames = clean_fields

        missing = [col for col in REQUIRED_COLUMNS if col not in clean_fields]
        if missing:
            raise ConfigValidationError([f"CSV 缺少必需列: {', '.join(missing)}"])

        for line_no, raw_row in enumerate(reader, start=2):
            if raw_row is None:
                continue
            if None in raw_row:
                errors.append(f"第 {line_no} 行: 存在多余列 {raw_row[None]!r}")
                continue
            # Skip completely blank lines
            if all((v is None or str(v).strip() == "") for v in raw_row.values()):
                continue
            label = f"第 {line_no} 行"
            try:
                rule = parse_rule_mapping(raw_row, label=label)
            except ValueError as exc:
                errors.append(str(exc))
                continue

            key = (rule.listen_ip, rule.listen_port, rule.source_ip, rule.source_port)
            if key in seen_keys:
                errors.append(
                    f"{label}: 监听端 {rule.listen_ip}:{rule.listen_port} 上存在重复来源 "
                    f"{rule.source_ip}:{rule.source_port} (首次出现于第 {seen_keys[key]} 行)"
                )
                continue
            seen_keys[key] = line_no
            parsed.append(rule)

    if require_non_empty and not parsed and not errors:
        errors.append("CSV 中没有有效规则")

    if errors:
        raise ConfigValidationError(errors)
    return parsed


def _format_num(val: float) -> str:
    if val == int(val):
        return str(int(val)) if abs(val) < 1e12 else f"{val:g}"
    return f"{val:g}"


def save_rules_csv(
    path: str | os.PathLike[str],
    rules: Iterable[Rule],
    *,
    include_loss_column: bool = True,
) -> Path:
    """Validate and atomically write rules to a CSV file."""
    rule_list = list(rules)
    validated = validate_rules(rule_list, require_non_empty=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    columns = ALL_COLUMNS if include_loss_column else REQUIRED_COLUMNS

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            for r in validated:
                row = {
                    "listen_ip": r.listen_ip,
                    "listen_port": r.listen_port,
                    "source_ip": r.source_ip,
                    "source_port": r.source_port,
                    "target_ip": r.target_ip,
                    "target_port": r.target_port,
                    "base_ms": _format_num(r.base_ms),
                    "sigma_ms": _format_num(r.sigma_ms),
                }
                if include_loss_column:
                    row["loss_pct"] = _format_num(r.loss_pct)
                writer.writerow(row)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target
