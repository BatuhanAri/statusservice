# api_py/kea_http_leases.py
from fastapi import APIRouter, HTTPException
import time
import httpx  # yoksa: pip install httpx

router = APIRouter(prefix="/api/ip", tags=["kea-http-leases"])

KEA_HTTP_URL = "http://localhost:8000/"  # SENİN VERDİĞİN ENDPOINT

def _normalize_kea(resp_json):
    """
    Kea control-agent cevabını (lease4-get-all) mevcut UI contract'ına çevirir:
      {count, items, meta}
    """
    if not isinstance(resp_json, list) or not resp_json:
        raise HTTPException(502, "Kea response beklenen JSON list formatında değil")

    r0 = resp_json[0]
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
            "remaining_secs": remaining,
        })

    # IP sort (senin CSV ile aynı davranış)
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
            "source": "kea-http",
            "url": KEA_HTTP_URL,
            "result": r0.get("result"),
            "text": r0.get("text"),
            "mtime": now,
            "mtime_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        }
    }

@router.get("/leases", summary="Kea HTTP endpoint (POST) -> normalize leases")
def leases_from_kea_http():
    payload = {"command": "lease4-get-all", "service": ["dhcp4"]}

    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.post(KEA_HTTP_URL, json=payload)
            r.raise_for_status()
            resp_json = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kea HTTP call failed: {e}")

    return _normalize_kea(resp_json)
