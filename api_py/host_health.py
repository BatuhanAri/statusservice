#!/usr/bin/env python3
"""
Host üzerindeki core servislerin (bind9, kea, nginx, docker) durumunu
systemctl üzerinden kontrol eder.

- CLI:
    python -m api_py.host_health

- API (FastAPI router):
    /api/system-services
"""

import subprocess
import json
from typing import List, Dict

from fastapi import APIRouter

router = APIRouter(
    prefix="/api/system-services",
    tags=["system-services"],
)

# Statik kalacak core servis listesi
SERVICES = [
    {
        "id": "bind9",
        "unit": "named.service",
        "name": "BIND9 DNS",
    },
    {
        "id": "kea",
        "unit": "kea-dhcp4-server.service",
        "name": "Kea DHCPv4",
    },
    {
        "id": "nginx",
        "unit": "nginx.service",
        "name": "Nginx Reverse Proxy",
    },
    {
        "id": "docker",
        "unit": "docker.service",
        "name": "Docker Engine",
    },
]


def check_systemd(unit: str) -> str:
    """
    systemctl is-active <unit>

    - active  -> "up"
    - diğer   -> "down"
    - hata    -> "unknown"
    """
    try:
        res = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            check=False,
        )
        active = (res.returncode == 0) and (res.stdout.strip() == "active")
        return "up" if active else "down"
    except Exception:
        return "unknown"


def list_services() -> List[Dict]:
    """
    Tüm statik servisleri dolaşır, state alanını doldurur.
    """
    result: List[Dict] = []

    for s in SERVICES:
        state = check_systemd(s["unit"])
        result.append(
            {
                "id": s["id"],
                "name": s["name"],
                "unit": s["unit"],
                "state": state,
                "kind": "systemd",
            }
        )

    return result


@router.get("")
def get_system_services():
    """
    API endpoint: GET /api/system-services
    """
    try:
        
        return list_services()

    except Exception as exc:
        print(f"Hata: {exc}")
        return {"error": str(exc)}


def main() -> None:
    """
    CLI entrypoint: JSON çıktıyı stdout'a basar.
    """
    data = list_services()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
