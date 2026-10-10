import math
import os
import shutil
import socket
import time
from pathlib import Path

import config


CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")


class MetricsError(RuntimeError):
    pass


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _percentage(used: int | float, total: int | float) -> float:
    if total <= 0:
        raise MetricsError("Metric total must be greater than zero")
    return round(max(0.0, min(100.0, used / total * 100.0)), 2)


def _is_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        return any(
            marker in _read_text(PROC_ROOT / "1" / "cgroup")
            for marker in ("docker", "containerd", "kubepods", "podman", "lxc")
        )
    except OSError:
        return False


def _cpu_capacity() -> float:
    try:
        quota, period = _read_text(CGROUP_ROOT / "cpu.max").split()
        if quota != "max":
            return max(float(quota) / float(period), 0.01)
    except (OSError, ValueError, ZeroDivisionError):
        pass
    return float(os.cpu_count() or 1)


def _cgroup_cpu_usage() -> int:
    try:
        values = dict(
            line.split(maxsplit=1)
            for line in _read_text(CGROUP_ROOT / "cpu.stat").splitlines()
        )
        return int(values["usage_usec"])
    except (OSError, KeyError, ValueError) as error:
        raise MetricsError("Could not read container CPU usage") from error


def _host_cpu_usage() -> tuple[int, int]:
    try:
        values = [int(value) for value in _read_text(PROC_ROOT / "stat").splitlines()[0].split()[1:]]
    except (OSError, ValueError, IndexError) as error:
        raise MetricsError("Could not read host CPU usage") from error
    if len(values) < 4:
        raise MetricsError("Host CPU statistics are incomplete")
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def _cpu_percent(container: bool, sample_seconds: float) -> float:
    if container and (CGROUP_ROOT / "cpu.stat").exists():
        before = _cgroup_cpu_usage()
        started = time.monotonic()
        time.sleep(sample_seconds)
        elapsed = time.monotonic() - started
        used_seconds = (_cgroup_cpu_usage() - before) / 1_000_000
        return round(max(0.0, min(100.0, used_seconds / (elapsed * _cpu_capacity()) * 100)), 2)

    total_before, idle_before = _host_cpu_usage()
    time.sleep(sample_seconds)
    total_after, idle_after = _host_cpu_usage()
    total_delta = total_after - total_before
    idle_delta = idle_after - idle_before
    if total_delta <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100)), 2)


def _host_memory() -> tuple[int, int]:
    try:
        values = {}
        for line in _read_text(PROC_ROOT / "meminfo").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0))
    except (OSError, KeyError, ValueError, IndexError) as error:
        raise MetricsError("Could not read memory usage") from error
    return total - available, total


def _memory(container: bool) -> tuple[int, int]:
    if container:
        try:
            maximum = _read_text(CGROUP_ROOT / "memory.max")
            if maximum != "max":
                return int(_read_text(CGROUP_ROOT / "memory.current")), int(maximum)
        except (OSError, ValueError):
            pass
    return _host_memory()


def _uptime(container: bool) -> float:
    try:
        host_uptime = float(_read_text(PROC_ROOT / "uptime").split()[0])
        if not container:
            return round(host_uptime, 2)
        stat = _read_text(PROC_ROOT / "1" / "stat")
        # The process name may contain spaces, so fields are counted after its final ')'.
        fields = stat[stat.rfind(")") + 2 :].split()
        started_after_boot = int(fields[19]) / os.sysconf("SC_CLK_TCK")
        return round(max(0.0, host_uptime - started_after_boot), 2)
    except (AttributeError, OSError, ValueError, IndexError) as error:
        raise MetricsError("Could not read uptime") from error


def collect_metrics(
    *, sample_seconds: float = 0.1, storage_path: Path | None = None
) -> dict:
    if storage_path is None:
        storage_path = config.STORAGE_PATH
    if not isinstance(sample_seconds, (int, float)) or not math.isfinite(sample_seconds) or sample_seconds <= 0:
        raise MetricsError("CPU sample duration must be greater than zero")

    container = _is_container()

    try:
        cpu_percent = _cpu_percent(container, sample_seconds)
    except (MetricsError, OSError):
        cpu_percent = None

    memory = None
    try:
        memory_used, memory_total = _memory(container)
        memory = {
            "used_bytes": memory_used,
            "total_bytes": memory_total,
            "percent": _percentage(memory_used, memory_total),
        }
    except (MetricsError, OSError):
        pass

    storage = None
    try:
        disk = shutil.disk_usage(storage_path)
        storage = {
            "path": str(storage_path),
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "percent": _percentage(disk.used, disk.total),
        }
    except (MetricsError, OSError) as error:
        print(f"Storage metrics unavailable for {storage_path}: {error}", flush=True)

    try:
        uptime_seconds = _uptime(container)
    except (MetricsError, OSError):
        uptime_seconds = None

    try:
        hostname = socket.gethostname() or None
    except OSError:
        hostname = None

    return {
        "scope": "container" if container else "host",
        "hostname": hostname,
        "cpu_percent": cpu_percent,
        "memory": memory,
        "storage": storage,
        "uptime_seconds": uptime_seconds,
    }
