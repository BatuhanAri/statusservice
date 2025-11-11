# api_py/app.py
import asyncio, httpx, yaml, time, os, subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# -----------------------------
# Yol/konfig
# -----------------------------
BASE = Path(__file__).parent
ROOT = BASE.parent
CFG  = BASE / "config.yaml"
WWW  = ROOT / "www"

def load_cfg() -> Dict[str, Any]:
    cfg = yaml.safe_load(CFG.read_text()) if CFG.exists() else {}
    cfg = cfg or {}
    cfg.setdefault("timeout_ms", 2000)
    cfg.setdefault("cache_secs", 5)
    cfg.setdefault("targets", [])
    return cfg

cfg = load_cfg()

# -----------------------------
# FastAPI uygulaması
# -----------------------------
app = FastAPI(title="IFE Health")

# Statik dosyaları /static altında ver (güvenli tercih)
app.mount("/static", StaticFiles(directory=str(WWW)), name="static")

# Köke index.html döndür
@app.get("/")
def index():
    idx = WWW / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"hint": "put www/index.html"})

# IP-Service sayfasını kökten da ver (kolay erişim)
@app.get("/ip-service.html")
def ip_service_page():
    f = WWW / "ip-service.html"
    if f.exists():
        return FileResponse(str(f))
    # fallback: static path önerisi
    raise HTTPException(status_code=404, detail="ip-service.html bulunamadı (www/ip-service.html oluşturun)")

# -----------------------------
# Leases router (Kea CSV -> JSON)
# -----------------------------
from .leases import router as leases_router
app.include_router(leases_router)   # leases_router kendi içinde prefix="/api/leases"

# -----------------------------
# Health / Problama (mevcut hedef kontrolleri)
# -----------------------------
_cached: Optional[Dict[str, Any]] = None
_cached_at: float = 0.0
def now() -> float: return time.monotonic()

async def tcp_check(host: str, port: int, timeout_ms: int) -> Optional[str]:
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout_ms/1000)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return None
    except Exception as e:
        return str(e)

async def http_check(host: str, port: int, path: str, timeout_ms: int, tls: bool, expect: Optional[List[int]]):
    url = f"{'https' if tls else 'http'}://{host}:{port}{path if path.startswith('/') else '/'+path}"
    try:
        async with httpx.AsyncClient(timeout=timeout_ms/1000) as cli:
            r = await cli.get(url)
        st = r.status_code
        ok = st in (expect or [200, 301, 302, 401, 403])
        return {"http_ok": ok, "status": st}
    except Exception as e:
        return {"http_ok": False, "error": str(e)}

async def check_one(t: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
    res: Dict[str, Any] = {"present": True}

    # TCP
    err = await tcp_check(str(t["host"]), int(t["port"]), timeout_ms)
    res["port_ok"] = (err is None)
    if err:
        res.setdefault("errors", {})["port"] = err

    # HTTP (opsiyonel)
    has_http = bool(t.get("http_path") or t.get("expect_status") or t.get("tls"))
    if has_http:
        h = await http_check(
            str(t["host"]), int(t["port"]), str(t.get("http_path") or "/"),
            timeout_ms, bool(t.get("tls")), t.get("expect_status")
        )
        res.update(h)
        if "error" in h:
            res.setdefault("errors", {})["http"] = h["error"]

    # Rozetler için metadata (UI)
    res["host"] = str(t.get("host"))
    res["port"] = int(t.get("port")) if t.get("port") is not None else None
    if t.get("http_path") is not None:
        res["http_path"] = str(t.get("http_path"))

    # ---- PRESENT HESAPLAMA ----
    pres = t.get("present", {}) or {}
    ptype = pres.get("type", "auto")

    def present_auto() -> bool:
        if has_http:
            return bool(res.get("http_ok") is True)
        return bool(res.get("port_ok") is True)

    def present_tcp() -> bool:
        return bool(res.get("port_ok") is True)

    def present_http() -> bool:
        if not has_http:
            return present_auto()
        return bool(res.get("http_ok") is True)

    def present_cmd() -> bool:
        cmd = pres.get("cmd")
        if not cmd:
            return present_auto()
        try:
            rc = subprocess.call(cmd, shell=True)
            return rc == 0
        except Exception:
            return False

    def present_systemd() -> bool:
        unit = pres.get("unit")
        if not unit:
            return present_auto()
        try:
            rc = subprocess.call(f"systemctl is-active --quiet {unit}", shell=True)
            return rc == 0
        except Exception:
            return False

    def present_file() -> bool:
        path = pres.get("path")
        if not path:
            return present_auto()
        return os.path.exists(path)

    if ptype == "tcp":
        res["present"] = present_tcp()
    elif ptype == "http":
        res["present"] = present_http()
    elif ptype == "cmd":
        res["present"] = present_cmd()
    elif ptype == "systemd":
        res["present"] = present_systemd()
    elif ptype == "file":
        res["present"] = present_file()
    else:
        res["present"] = present_auto()

    return res

async def perform() -> Dict[str, Any]:
    ts: List[Dict[str, Any]] = cfg["targets"]
    rs = await asyncio.gather(*[check_one(t, int(cfg["timeout_ms"])) for t in ts])
    return { str(t["name"]): r for t, r in zip(ts, rs) }

def cached() -> Dict[str, Any]:
    global _cached, _cached_at
    if _cached and (now() - _cached_at) < int(cfg["cache_secs"]):
        return _cached
    # senkron endpoint'ten çağrıldığında güvenli
    data = asyncio.run(perform())
    _cached, _cached_at = data, now()
    return data

@app.get("/health")
def liveness():
    return {"status": "up"}

@app.get("/api/health")
def api_health():
    return JSONResponse(content=cached())

@app.post("/api/run")
async def api_run():
    data = await perform()
    global _cached, _cached_at
    _cached, _cached_at = data, now()
    return JSONResponse(content=data)
