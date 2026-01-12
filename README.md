# Status Service (IFE Health)

Bu repo, host üzerindeki servislerin ve konteynerlerin durumunu izlemek için **FastAPI** tabanlı bir sağlık kontrol servisi ve basit bir web arayüzü sağlar. API; sistem servisleri, Docker servisleri, loglar ve DHCP lease bilgilerini tek bir noktadan sunar.

## Özellikler

- TCP/HTTP sağlık kontrolleri (konfigüre edilebilir hedef listesi).
- Sistem servisleri durumu (`systemctl is-active`).
- Docker konteyner listesi ve loglarına erişim.
- Systemd journal logları (bind9/kea/nginx/system-service).
- Kea DHCP lease bilgileri (CSV veya HTTP control-agent üzerinden).
- Sistem bilgileri (kernel ve distro).
- Basit statik dashboard (`www/`).

## Dizin Yapısı

- `api_py/`: FastAPI uygulaması ve router'lar.
- `www/`: Statik HTML dashboard ve yardımcı sayfalar.
- `Dockerfile`: Uygulama imajı.
- `docker-compose.yml`: Host entegrasyonlu çalışma örneği.

## Kurulum

### Docker (önerilen)

```bash
docker compose up --build
```

`docker-compose.yml` şu host kaynaklarını mount eder:

- `/var/run/docker.sock` (Docker API erişimi)
- `/var/log/journal` ve `/run/log/journal` (systemd logları)
- `/var/lib/kea/kea-leases4.csv` (Kea DHCP lease CSV)
- `/etc/systemd/system`, `/lib/systemd/system` (service metadata)
- `/var/lib/dpkg`, `/etc/dpkg` (paket versiyonu okuma)
- `/var/lib/docker/containers` (docker json logları)

> Not: `docker-compose.yml` içinde `image: ${IMAGE_NAME}` kullanılır. Değerini `.env` veya ortam değişkeni ile geçebilirsiniz.

### Local (uvicorn)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r api_py/requirements.txt
uvicorn api_py.app:app --host 0.0.0.0 --port 8001
```

## Konfigürasyon

`api_py/config.yaml` dosyası TCP/HTTP kontrol hedeflerini tanımlar.

Örnek:

```yaml
bind: "0.0.0.0:8001"
timeout_ms: 2000
cache_secs: 5

targets:
  - name: nginx
    host: 127.0.0.1
    port: 80
    http_path: "/"
    expect_status: [200,301,302]
    present:
      type: systemd
    pkg: nginx
```

Alanlar:

- `timeout_ms`: TCP/HTTP istek zaman aşımı.
- `cache_secs`: `/api/health` için cache süresi.
- `targets`: Kontrol edilecek servis listesi.
  - `http_path`: HTTP kontrolü için path.
  - `expect_status`: Başarılı kabul edilen HTTP kodları.
  - `present.type`: `tcp`, `http`, `systemd`, `file`.
  - `pkg`: `dpkg -l` ile versiyon okuma için paket adı.

## API Endpointleri (Özet)

- `GET /health`: Liveness.
- `GET /api/health`: Konfigüre hedefler için cache'li sağlık sonucu.
- `POST /api/run`: Anlık sağlık kontrolü.
- `GET /api/system-info`: Kernel ve distro bilgisi.
- `GET /api/system-services`: Systemd servis durumu (bind9/kea/nginx/system-service).
- `GET /api/system-logs?lines=80`: Systemd journal logları.
- `GET /api/docker-services`: Docker konteyner listesi.
- `GET /api/docker-logs/{container_name}?tail=0`: Docker json loglarını okur.
- `GET /api/system-service/version`: system-service versiyonu (unit description üzerinden).
- `GET /api/leases`: Kea lease CSV okuma.
- `GET /api/ip/leases`: Kea HTTP control-agent üzerinden lease okuma.

## Web Arayüzü

- `GET /`: Ana dashboard (`www/index.html`).
- `GET /ip-service.html`: IP/Lease görüntüleme sayfası.
- `GET /logs-service.html`: Log izleme sayfası.

## Notlar

- Docker logları için konteyner log-driver'ının `json-file` olması gerekir.
- Systemd logları için container içine journal dizinlerinin mount edilmesi gerekir.
- Nginx reverse proxy örneği `ife-health.conf` dosyasında bulunur.
