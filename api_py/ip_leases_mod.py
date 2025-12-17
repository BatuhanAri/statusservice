# api_py/ip_leases_mod.py
from fastapi import APIRouter, HTTPException, Query
from pathlib import Path
import json, os, socket, time

# CSV endpoint'in zaten var: /api/leases
# Biz yeni mod endpoint'i açıyoruz:
router = APIRouter(prefix="/api/ip", tags=["ip-leases"])

KEA4_CTRL_SOCKET = Path("/run/kea/kea4-ctrl-socket")

def _kea_ctrl(command: dict, sock_path: Path, timeout_s: float = 2.0):
    if not sock_path.exists():
        raise HTTPException(status_code=503, detail=f"Kea control socket yok: {sock_path}")

    data = json.dumps([command]).encode("utf-8")  # Kea control-agent JSON list bekler
    out = b""

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout_s)
    try:
        s.connect(str(sock_path))
        s.sendall(data)
        # cevap JSON; tek seferde gelmeyebilir
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
    except socket.timeout:
        raise HTTPException(status_code=504, detail="Kea control socket timeout")
    except OSError as e:
        raise HTTPException(status_code=502, detail=f"Kea control socket hata: {e}")
    finally:
        try: s.close()
        except: pass

    try:
        return json.loads(out.decode("utf-8", errors="replace"))
    except Exception:
        raise HTTPException(status_code=502, detail="Kea cevabı JSON parse edilemedi")

def _normalize_kea_leases(resp):
    # resp örneği senin çıktın gibi: [ { "arguments": { "leases": [...] }, "result":0, "text":"..." } ]
    if not isinstance(resp, list) or not resp:
        raise HTTPException(status_code=502, detail="Kea cevabı beklenen formatta değil")

    r0 = resp[0]
    args = (r0.get("arguments") or {})
    leases = args.get("leases") or []
    now = int(time.time())

    items = []
    for l in leases:
        ip = l.get("ip-address") or ""
        mac = (l.get("hw-address") or "").lower()
        client_id = l.get("client-id") or ""
        hostname = l.get("hostname") or ""
        subnet_id = l.get("subnet-id")
        state = l.get("state", -1)
        cltt = l.get("cltt")
        valid_lft = l.get("valid-lft")

        expire = None
        if isinstance(cltt, int) and isinstance(valid_lft, int):
            expire = cltt + valid_lft

        remaining = (expire - now) if (isinstance(expire, int) and expire > now) else 0
        expire_human = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expire)) if expire else ""

        items.append({
            "ip": ip,
            "mac": mac,
            "client_id": client_id,
            "hostname": hostname,
            "subnet_id": subnet_id,
            "state": state,
            "valid_lft": valid_lft,
            "expire": expire,
            "expire_human": expire_human,
            "remaining_secs": remaining
        })

    # IP sort (senin CSV'deki gibi)
    def ipkey(x):
        try:
            return list(map(int, str(x["ip"]).split(".")))
        except:
            return [999, 999, 999, 999]
    items.sort(key=ipkey)

    return {
        "count": len(items),
        "items": items,
        "meta": {
            "source": "kea-control-socket",
            "socket": str(KEA4_CTRL_SOCKET),
            "result": r0.get("result"),
            "text": r0.get("text"),
            "mtime": int(time.time()),
            "mtime_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
    }

@router.get("/leases", summary="IP leases (CSV veya Kea)")
def ip_leases(source: str = Query("csv", pattern="^(csv|kea)$")):
    if source == "csv":
        # mevcut /api/leases response’unu aynen döndürmek istersen:
        # from .leases import _read_csv
        # return _read_csv()
        #
        # Ama import path’in sende nasıl, repo yapına göre düzenle:
        from api_py.leases import _read_csv
        return _read_csv()

    # source == "kea"
    cmd = {"command": "lease4-get-all", "service": ["dhcp4"]}
    resp = _kea_ctrl(cmd, KEA4_CTRL_SOCKET)
    return _normalize_kea_leases(resp)
