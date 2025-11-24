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

# -----------------------------
# System Services router
# -----------------------------
from .host_health import router as host_health_router
app.include_router(host_health_router)

# -----------------------------
# Docker Services router
# -----------------------------
from .docker_services import router as docker_services_router
app.include_router(docker_services_router)

# Statik dosyalar
app.mount("/static", StaticFiles(directory=str(WWW)), name="static")

# Index
@app.get("/")
def index():
    idx = WWW / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"hint": "put www/index.html"})


# IP-Service sayfası
@app.get("/ip-service.html")
def ip_service_page():
    f = WWW / "ip-service.html"
    if f.exists():
        return FileResponse(str(f))
    raise HTTPException(status_code=404, detail="ip-service.html bulunamadı")


# -----------------------------
# Leases router
# -----------------------------
from .leases import router as leases_router
app.include_router(leases_router)


# -----------------------------
# Cache
# -----------------------------
_cached: Optional[Dict[str, Any]] = None
_cached_at: float = 0.0

def now() -> float:
    return time.monotonic()


# -----------------------------
# Yardımcı kontroller
# -----------------------------
async def tcp_check(host: str, port: int, timeout_ms: int) -> Optional[str]:
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout_ms/1000
        )
        w.close()
        try: await w.wait_closed()
        except: pass
        return None
    except Exception as e:
        return str(e)


async def http_check(host: str, port: int, path: str, timeout_ms: int,
                     tls: bool, expect: Optional[List[int]]):
    url = f"{'https' if tls else 'http'}://{host}:{port}{path if path.startswith('/') else '/'+path}"
    try:
        async with httpx.AsyncClient(timeout=timeout_ms/1000) as cli:
            r = await cli.get(url)

        st = r.status_code
        ok = st in (expect or [200,301,302,401,403])
        return {"http_ok": ok, "status": st}

    except Exception as e:
        return {"http_ok": False, "error": str(e)}


# -----------------------------
# TEK SERVİS CHECK
# -----------------------------
async def check_one(t: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
    res: Dict[str, Any] = {"present": True}
    
    # --- 1. Port Kontrolü (TCP) ---
    err = await tcp_check(str(t["host"]), int(t["port"]), timeout_ms)
    res["port_ok"] = (err is None)
    if err:
        res.setdefault("errors", {})["port"] = err

    # --- 2. HTTP Kontrolü ---
    has_http = bool(t.get("http_path") or t.get("expect_status") or t.get("tls"))
    if has_http:
        h = await http_check(
            str(t["host"]), int(t["port"]),
            str(t.get("http_path") or "/"),
            timeout_ms, bool(t.get("tls")), t.get("expect_status")
        )
        res.update(h)
        if "error" in h:
            res.setdefault("errors", {})["http"] = h["error"]

        # --- 3. VERSION (sadece config'ten al) ---
    res["version"] = t.get("version")


    

    # --- 4. PRESENT (Varlık) Kontrolü ---
    pres = t.get("present", {}) or {}
    ptype = pres.get("type")

    def present_auto():
        if has_http: return bool(res.get("http_ok"))
        return bool(res.get("port_ok"))

    def present_systemd():
        unit = pres.get("unit") or f"{t['name']}.service"
        try:
            # is-active 0 dönerse çalışıyordur
            rc = subprocess.call(
                f"systemctl is-active --quiet {unit}", 
                shell=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            return rc == 0
        except:
            return False

    def present_file():
        return os.path.exists(pres.get("path", ""))

    if ptype == "tcp": res["present"] = bool(res.get("port_ok"))
    elif ptype == "http": res["present"] = bool(res.get("http_ok")) if has_http else present_auto()
    elif ptype == "systemd": res["present"] = present_systemd()
    elif ptype == "file": res["present"] = present_file()
    else: res["present"] = present_auto()

    return res


# -----------------------------
# TÜM SERVİSLER CHECK
# -----------------------------
async def perform() -> Dict[str, Any]:
    ts = cfg["targets"]
    rs = await asyncio.gather(*[check_one(t, int(cfg["timeout_ms"])) for t in ts])
    return {t["name"]: r for t, r in zip(ts, rs)}


def cached() -> Dict[str, Any]:
    global _cached, _cached_at
    if _cached and (now() - _cached_at) < int(cfg["cache_secs"]):
        return _cached
    data = asyncio.run(perform())
    _cached, _cached_at = data, now()
    return data


# -----------------------------
# API ROUTES
# -----------------------------
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
