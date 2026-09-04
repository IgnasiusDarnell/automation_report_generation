# Setup `report.darnell.my.id` untuk Web Admin GUI

Status saat ini:
- `remindre-web` (Flask) jalan di `homelab-backend:8080` ✓
- `homelab-nginx` sudah jadi reverse-proxy untuk Host `report.darnell.my.id` & `bot.darnell.my.id` ✓
- `homelab-cloudflared` sudah terkoneksi ke Cloudflare (tunnel token mode) ✓
- DNS publik `cc.darnell.my.id` = A record Cloudflare anycast (bukan via tunnel)

Yang belum: **route `report.darnell.my.id` dari internet ke nginx Anda**.

Ada 2 cara — pilih salah satu:

---

## Cara A: Lewat Dashboard Cloudflare (paling gampang, tanpa API)

1. Buka https://one.dash.cloudflare.com/
2. Login → pilih account Anda.
3. Sidebar kiri: **Networks** → **Tunnels**.
4. Klik tunnel yang dipakai `homelab-cloudflared` (cari di log container:
   `docker logs homelab-cloudflared | grep "Tunnel connection" — name tunnel biasanya seperti "homelab-tunnel-xxxx"`).
5. Klik tab **Public Hostname**.
6. Klik **Add a public hostname**.
7. Isi:
   - **Subdomain**: `report`
   - **Domain**: `darnell.my.id`
   - **Service type**: `HTTP`
   - **URL**: `homelab-nginx:80`
8. Klik **Save**.
9. (Opsional) Centang **No TLS Verify** jika nanti HTTPS muncul error.
10. Tunggu ~30 detik. Test:

    ```bash
    curl -I https://report.darnell.my.id
    ```

    Harus return `HTTP/2 200` atau `302` (redirect ke login).

---

## Cara B: Lewat Cloudflare API (reproducible, ada audit log)

Anda butuh:
- **Cloudflare API Token** dengan permission `Zone:DNS:Edit` + `Account:Cloudflare Tunnel:Edit`
  (Generate di https://dash.cloudflare.com/profile/api-tokens → "Create Custom Token").
- **Account ID** (ada di sidebar kanan dashboard atau di `curl -H "Authorization: Bearer $TOKEN" https://api.cloudflare.com/client/v4/accounts`).
- **Zone ID** untuk `darnell.my.id` (`curl -H "Authorization: Bearer $TOKEN" "https://api.cloudflare.com/client/v4/zones?name=darnell.my.id"`).
- **Tunnel ID** (di URL dashboard saat buka tunnel, atau `curl -H "Authorization: Bearer $TOKEN" "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel?name=homelab-cloudflared"`).

### Step 1 — Buat CNAME record di zone `darnell.my.id`

```bash
curl -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "type": "CNAME",
    "name": "report",
    "content": "<TUNNEL_ID>.cfargotunnel.com",
    "proxied": true
  }'
```

### Step 2 — Tambah Public Hostname ke tunnel

```bash
curl -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
  -H "Authorization: Bearer $CF_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "config": {
      "ingress": [
        { "hostname": "report.darnell.my.id", "service": "http://homelab-nginx:80" },
        { "service": "http_status:404" }
      ]
    }
  }'
```

Verifikasi:
```bash
curl -I https://report.darnell.my.id
```

---

## Kalau pakai Cloudflare Access (opsional, untuk OTP di depan login)

Di dashboard: **Access → Applications → Add Application → Self-hosted**.
- Name: `KOMPU Report Admin`
- Domain: `report.darnell.my.id`
- Policy: `Allow` + `Emails` (pakai email Anda) + `Require One-time PIN`.

Setelah disimpan, akses `https://report.darnell.my.id` akan minta OTP email dulu, baru login form web muncul.

---

## Verifikasi akhir

```bash
# Dari server Anda
docker exec homelab-nginx nginx -t         # harus OK
docker logs remindre-web --tail 5        # harus ada log akses via nginx

# Dari internet (via Cloudflare)
curl -I https://report.darnell.my.id
# Expected: HTTP/2 200 (login page) atau 302 (redirect ke /login)

# Login
# Username: automation_darma
# Password: darma_password_automation123
```