import os
import platform
import socket
import time
from pathlib import Path
from typing import Any

import psutil


def _unavailable() -> str:
    return "Not available on this platform"


def cpu_temperature() -> dict[str, Any]:
    try:
        temperatures = psutil.sensors_temperatures()
        for key in ("cpu_thermal", "coretemp", "soc_thermal"):
            entries = temperatures.get(key, [])
            if entries:
                return {"available": True, "celsius": round(entries[0].current, 1)}
    except (AttributeError, OSError):
        pass
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return {"available": True, "celsius": round(float(thermal.read_text().strip()) / 1000, 1)}
    except (OSError, ValueError):
        return {"available": False, "message": _unavailable()}


def cpu_usage() -> dict[str, Any]:
    return {"percent": psutil.cpu_percent(interval=0.2), "cores": psutil.cpu_count(logical=True)}


def cpu_load() -> dict[str, Any]:
    try:
        one, five, fifteen = os.getloadavg()
        return {"1m": round(one, 2), "5m": round(five, 2), "15m": round(fifteen, 2)}
    except OSError:
        return {"message": _unavailable()}


def ram_usage() -> dict[str, Any]:
    value = psutil.virtual_memory()
    return {"total": value.total, "available": value.available, "used": value.used, "percent": value.percent}


def disk_usage() -> dict[str, Any]:
    value = psutil.disk_usage("/")
    return {"total": value.total, "free": value.free, "used": value.used, "percent": value.percent}


def uptime() -> dict[str, Any]:
    try:
        seconds = int(time.time() - psutil.boot_time())
    except (OSError, PermissionError):
        try:
            seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            return {"seconds": None, "human": _unavailable()}
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return {"seconds": seconds, "human": f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"}


def hostname() -> dict[str, str]:
    return {"hostname": socket.gethostname()}


def os_information() -> dict[str, str]:
    return {"system": platform.system(), "release": platform.release(), "version": platform.version(), "machine": platform.machine()}


def raspberry_pi_model() -> dict[str, Any]:
    path = Path("/proc/device-tree/model")
    try:
        model = path.read_text().rstrip("\x00")
        return {"available": True, "model": model, "is_raspberry_pi": "Raspberry Pi" in model}
    except OSError:
        return {"available": False, "model": _unavailable(), "is_raspberry_pi": False}


def network_information() -> dict[str, Any]:
    interfaces: dict[str, list[str]] = {}
    for name, addresses in psutil.net_if_addrs().items():
        values = [address.address for address in addresses if address.family in (socket.AF_INET, socket.AF_INET6)]
        if values:
            interfaces[name] = values
    primary = "Unavailable"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        primary = sock.getsockname()[0]
    except OSError:
        pass
    finally:
        sock.close()
    return {"primary_ip": primary, "interfaces": interfaces}


def top_processes(sort_by: str = "memory", limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            rows.append({
                "pid": process.info["pid"], "name": process.info["name"],
                "cpu_percent": round(process.info["cpu_percent"] or 0, 1),
                "memory_percent": round(process.info["memory_percent"] or 0, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
    return sorted(rows, key=lambda row: row[key], reverse=True)[: max(1, min(limit, 20))]


def system_health() -> dict[str, Any]:
    return {
        "cpu": cpu_usage(), "load": cpu_load(), "temperature": cpu_temperature(),
        "memory": ram_usage(), "disk": disk_usage(), "uptime": uptime(),
        "hostname": hostname()["hostname"], "network": network_information(),
        "os": os_information(), "raspberry_pi": raspberry_pi_model(),
    }
