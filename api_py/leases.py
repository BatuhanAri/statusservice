# api_py/leases.py
from fastapi import APIRouter, HTTPException
from pathlib import Path
import csv, time, os

router = APIRouter(prefix="/api/leases", tags=["leases"])
LEASES_CSV = Path("/var/lib/kea/kea-leases4.csv")

EXPECTED_COLS = [
    "address","hwaddr","client_id","valid_lifetime","expire",
    "subnet_id","fqdn_fwd","fqdn_rev","hostname","state","user_context"
]

def _to_int(x):
    try: return int(x)
    except: return None

def _read_csv():
    if not LEASES_CSV.exists():
        raise HTTPException(status_code=404, detail=f"{LEASES_CSV} bulunamadı")

    now = int(time.time())
    items = []

    with LEASES_CSV.open("r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        # header kontrolü
        has_header = isinstance(header, list) and header and header[0].strip().lower() == "address"
        idx = {}
        if has_header:
            hn = [h.strip().lower() for h in header]
            for name in EXPECTED_COLS:
                idx[name] = hn.index(name) if name in hn else None
        else:
            idx = {
                "address":0,"hwaddr":1,"client_id":2,"valid_lifetime":3,"expire":4,
                "subnet_id":5,"fqdn_fwd":6,"fqdn_rev":7,"hostname":8,"state":9,"user_context":10
            }
            # header yoksa ilk satır veri olarak işlenebilsin diye
            if header: reader = [[*header], *list(reader)]

        for row in reader:
            if not row or not row[0] or row[0].startswith("#"): 
                continue

            def col(name, default=""):
                i = idx.get(name)
                return (row[i].strip() if (i is not None and i < len(row)) else default)

            ip       = col("address")
            mac      = col("hwaddr").lower()
            clientid = col("client_id")
            vlt      = _to_int(col("valid_lifetime"))
            exp      = _to_int(col("expire"))
            subnet   = col("subnet_id")
            hostn    = col("hostname")
            state    = _to_int(col("state"))

            remaining = (exp - now) if (exp and exp > now) else 0
            expire_h  = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp)) if exp else ""

            items.append({
                "ip": ip, "mac": mac, "client_id": clientid, "hostname": hostn,
                "subnet_id": subnet, "state": (state if state is not None else -1),
                "valid_lft": vlt, "expire": exp, "expire_human": expire_h,
                "remaining_secs": remaining
            })

    # IP’e göre sırala
    def ipkey(x):
        try: return list(map(int, x["ip"].split(".")))
        except: return [999,999,999,999]
    items.sort(key=ipkey)

    # dosyanın mtime’ını meta’ya koy
    mtime = int(os.path.getmtime(LEASES_CSV))
    return {
        "count": len(items),
        "items": items,
        "meta": {
            "source": str(LEASES_CSV),
            "mtime": mtime,
            "mtime_human": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        }
    }

@router.get("", summary="Kea CSV -> JSON lease listesi")
def list_leases():
    return _read_csv()
