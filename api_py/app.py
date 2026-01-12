import asyncio, httpx, yaml, time, os, subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import docker_logs 
from . import system_service_version as system_service_version_api
from . import system_logs 
from . import ip_leases_mod



# Yol/konfig
OS_RELEASE = "/host-etc-os-release"
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



# FastAPI uygulaması
app = FastAPI(title="IFE Health")

# IP Leases Mod router
app.include_router(ip_leases_mod.router)

# System Logs router
app.include_router(system_logs.router) 

# Docker Logs router
app.include_router(docker_logs.router)

# System Service Version router
app.include_router(system_service_version_api.router)


# System Services router
from .host_health import router as host_health_router
app.include_router(host_health_router)

# Docker Services router
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


# Leases router
from .leases import router as leases_router
app.include_router(leases_router)


# Cache
_cached: Optional[Dict[str, Any]] = None
_cached_at: float = 0.0

def now() -> float:
    return time.monotonic()


def get_kernel_version() -> str:
    """
    Host kernel versiyonunu uname -r ile al.
    """
    try:
        out = subprocess.check_output(
            ["uname", "-r"], stderr=subprocess.STDOUT
        )
        return out.decode(errors="ignore").strip()
    except Exception as e:
        return f"unknown ({e.__class__.__name__})"

def get_distro_info() -> Dict[str, Optional[str]]:
    """
    /etc/os-release içinden:
      - PRETTY_NAME
      - VERSION_CODENAME
      - ID_LIKE
    """
    pretty_name = None
    version_codename = None
    id_like = None

    try:
        with open(OS_RELEASE, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue

                key, val = line.split("=", 1)

                val = val.strip().strip('"').strip("'")

                if key == "PRETTY_NAME":
                    pretty_name = val
                elif key == "VERSION_CODENAME":
                    version_codename = val
                elif key == "ID_LIKE":
                    id_like = val
    except Exception:
        pass

    return {
        "pretty_name": pretty_name,
        "version_codename": version_codename,
        "id_like": id_like
    }


@app.get("/api/system-info")
def api_system_info():
    distro = get_distro_info()
    return {
        "kernel": get_kernel_version(),
        "pretty_name": distro.get("pretty_name"),
        "version_codename": distro.get("version_codename"),
        "id_like": distro.get("id_like"),
    }


# Yardımcı kontroller
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


def get_pkg_version(pkg: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            f"dpkg -l {pkg}",
            shell=True, stderr=subprocess.STDOUT
        ).decode(errors="ignore").strip()

        for line in out.splitlines():
            if line.startswith("ii"):
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]  # version
    except Exception:
        return None

    return None

# IP adresi çekme
@app.get("/api/client-ip")
def api_client_ip(request: Request):
    # Reverse proxy arkasında ise X-Forwarded-For / X-Real-IP'e bak
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    return {"ip": ip or ""}



def fetch_version_systemctl(unit_name: str) -> Optional[str]:
    """
    systemctl -> FragmentPath -> dpkg -S -> dpkg -l zinciri ile otomatik versiyon çıkarır.
    """
    try:
        # Unit path
        out = subprocess.check_output(
            f"systemctl show {unit_name} --property=FragmentPath",
            shell=True, stderr=subprocess.STDOUT
        ).decode(errors="ignore").strip()

        if "=" not in out:
            return None

        frag_path = out.split("=", 1)[1].strip()

        # Bu hizmet hangi paketten geliyor?
        out = subprocess.check_output(
            f"dpkg -S {frag_path}",
            shell=True, stderr=subprocess.STDOUT
        ).decode(errors="ignore").strip()

        pkg = out.split(":", 1)[0].strip()

        # Paket versiyonu al
        out = subprocess.check_output(
            f"dpkg -l {pkg}",
            shell=True, stderr=subprocess.STDOUT
        ).decode(errors="ignore")

        for line in out.splitlines():
            if line.startswith("ii "):
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]

        return None

    except Exception:
        return None


# HTTP version çekme 

async def fetch_version_http(t: Dict[str, Any], timeout_ms: int) -> Optional[str]:
    vpath = t.get("version_path")
    if not vpath:
        return None

    host = str(t["host"])
    port = int(t["port"])
    tls  = bool(t.get("tls"))

    if not vpath.startswith("/"):
        vpath = "/" + vpath

    url = f"{'https' if tls else 'http'}://{host}:{port}{vpath}"

    try:
        async with httpx.AsyncClient(timeout=timeout_ms/1000) as cli:
            r = await cli.get(url)
    except:
        return None

    if not (200 <= r.status_code < 300):
        return None

    # JSON version destekliyse
    try:
        data = r.json()
        for key in ("version", "app_version", "build", "tag", "commit"):
            if key in data:
                return str(data[key])
    except:
        txt = (r.text or "").strip()
        return txt[:64] if txt else None

    return None


# TEK SERVİS CHECK
async def check_one(t: Dict[str, Any], timeout_ms: int) -> Dict[str, Any]:
    res: Dict[str, Any] = {"present": True}
    
    # --- 1. Port Kontrolü (TCP) ---

    # TCP KONTROLÜ
    err = await tcp_check(str(t["host"]), int(t["port"]), timeout_ms)
    res["port_ok"] = (err is None)
    if err:
        res.setdefault("errors", {})["port"] = err

    # --- 2. HTTP Kontrolü ---
    # HTTP KONTROLÜ 
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

    #  VERSION (DİNAMİK - pkg + dpkg)
    version = None
    pkg = t.get("pkg")
    if pkg:
        version = get_pkg_version(pkg)  

    res["version"] = version  

    # PRESENT HESAPLAMA
    pres_raw = t.get("present", {})
    pres = pres_raw if isinstance(pres_raw, dict) else {}
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
        return present_auto()

    def present_file():
        return os.path.exists(pres.get("path", ""))

    if ptype == "tcp": 
        res["present"] = bool(res.get("port_ok"))
    elif ptype == "http": 
        res["present"] = bool(res.get("http_ok")) if has_http else present_auto()
    elif ptype == "systemd": 
        res["present"] = present_systemd()
    elif ptype == "file": 
        res["present"] = present_file()
    else: 
        res["present"] = present_auto()

    return res



# TÜM SERVİSLER CHECK
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


# API ROUTES
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
