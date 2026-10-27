# Đưa TPAgent lên cloud — dùng từ trình duyệt, máy yếu vẫn chạy

Ý tưởng: TPAgent chạy trên một máy chủ thuê giá rẻ (≈ 5–7 USD/tháng, ~130–180k đ), anh chỉ mở
trình duyệt trên laptop/điện thoại, dán **token** để đăng nhập rồi gõ việc. Mọi thứ nặng
(Chromium, ffmpeg, gọi model) chạy trên máy chủ. File anh tải lên / video xuất ra nằm trong
thư mục `/data` trên máy chủ và **không mất khi cập nhật** (volume).

> Trên cloud không có màn hình nên tool *điều khiển máy tính* (`computer`) bị tắt.
> Trình duyệt, video, subagent, code vẫn chạy đủ.

## 0. Chuẩn bị chung (làm 1 lần, 10 phút)

### 0.1 Lấy `ANTHROPIC_API_KEY`
1. Vào <https://console.anthropic.com>, đăng nhập bằng tài khoản Claude của anh.
2. Menu **API Keys** → **Create Key** → đặt tên `tpagent` → copy chuỗi `sk-ant-api03-...`
   (chỉ hiện 1 lần, lưu vào nơi an toàn).
3. Gói **Claude Max** được tặng credit API hằng tháng (Max 5x ≈ $100, Max 20x ≈ $200) — kiểm tra
   trong **Billing**. Hết credit tặng thì nạp thêm bằng thẻ (prepaid, nạp bao nhiêu dùng bấy nhiêu).

### 0.2 Chọn `TPAGENT_TOKEN` (mật khẩu vào web)
Ai có token này là dùng được agent (và tiền API của anh), nên phải **dài và ngẫu nhiên**:
```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```
Hoặc dùng trang <https://passwordsgenerator.net> chọn 32 ký tự. **Không** dùng số điện thoại, tên tiệm, ngày sinh.
Để trống thì container tự sinh token và in ra **log** khi khởi động (xem log của nền tảng để lấy).

### 0.3 Đưa mã nguồn lên GitHub (Railway/Render deploy từ GitHub)
1. Tạo tài khoản <https://github.com>, **New repository** → tên `tpagent` → **Private**.
2. Trên máy, trong thư mục `tpagent`:
   ```bash
   git init && git add . && git commit -m "tpagent"
   git branch -M main
   git remote add origin https://github.com/<tên-anh>/tpagent.git
   git push -u origin main
   ```
   (Chưa có git: tải tại <https://git-scm.com>, hoặc dùng GitHub Desktop kéo-thả thư mục.)
3. **Không** commit `config.yaml` có key hay file `.env` — thêm hai dòng `config.yaml` và `.env`
   vào file `.gitignore` trước khi `git add` (`.dockerignore` đã loại chúng khỏi image).

### Biến môi trường mà mọi nền tảng đều cần

| Biến | Giá trị | Ghi chú |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | bắt buộc |
| `TPAGENT_TOKEN` | chuỗi ngẫu nhiên dài | bắt buộc (hoặc để trống → tự sinh, xem log) |
| `PORT` | `8080` | Railway/Render/Fly tự đặt, không cần sửa |
| `TPAGENT_HOME` / `HOME` | `/data` | lịch sử phiên + config nằm trong volume (đã đặt sẵn trong Dockerfile) |
| `TPAGENT_WORKSPACE` | `/data/workspace` | nơi agent đọc/ghi file (đã đặt sẵn) |
| `TPAGENT_BROWSER_HEADLESS` | `1` | Chromium chạy ẩn (đã đặt sẵn) |
| `TPAGENT_ENABLED_TOOLS` | `browser,video,subagent` | tắt `computer`. Core hiện đọc danh sách tool từ `config.yaml`; bản `deploy/config.cloud.yaml` đã tắt sẵn, biến này để dự phòng |

Chỉ cần tự nhập **2 dòng đầu**; phần còn lại đã nằm trong `Dockerfile`/`deploy/*`.

---

## 1. Railway (rẻ và dễ nhất) — thử miễn phí, sau đó ≈ $5/tháng

Railway tính theo tài nguyên thực dùng; gói **Hobby $5/tháng** đã kèm $5 credit, agent dùng
lúc rảnh gần như không tốn thêm. Có volume nên file không mất.

1. Vào <https://railway.com> → **Login with GitHub**.
2. **New Project → Deploy from GitHub repo** → chọn repo `tpagent` → Railway tự thấy `Dockerfile`.
3. Vào service vừa tạo → tab **Settings**:
   - **Config-as-code → Railway Config File**: điền `deploy/railway.json` (để dùng healthcheck `/health`,
     restart policy đã viết sẵn). Nếu không thấy mục này: bỏ qua, Dockerfile tự chạy được.
   - **Networking → Generate Domain** → nhận địa chỉ dạng `https://tpagent-xxxx.up.railway.app`,
     cổng nhập `8080`.
4. Tab **Variables** → **New Variable**:
   - `ANTHROPIC_API_KEY` = key ở bước 0.1
   - `TPAGENT_TOKEN` = token ở bước 0.2
5. Gắn ổ lưu: chuột phải vào service (hoặc nút **+ Create → Volume**) → **Add Volume** →
   **Mount path**: `/data`. (Volume 0.5–1 GB miễn phí trong hạn mức, thêm ≈ $0.15/GB/tháng.)
6. Railway tự build (lần đầu 4–6 phút vì tải ảnh Chromium). Tab **Deployments → View Logs**
   thấy khung `TPAgent server` in **Token đăng nhập** và **URL** là xong.
7. Mở URL ở bước 3 trên trình duyệt → dán token → dùng.

**Cập nhật**: sửa code trên máy → `git add . && git commit -m "update" && git push` → Railway tự
build lại và deploy, dữ liệu trong `/data` giữ nguyên. Hoặc **Deployments → ⋮ → Redeploy**.

**Chi phí thực tế**: ~1 GB RAM, chạy 24/7 ≈ $5–8/tháng. Bật **Settings → App Sleeping** để
ngủ khi không dùng (tiết kiệm, nhưng lần mở đầu chậm ~10 giây) — trong `railway.json` đang để
`sleepApplication: false`, đổi thành `true` nếu muốn.

---

## 2. Render — có gói Free (ngủ khi rảnh), Starter $7/tháng

- **Free**: ngủ sau 15 phút không dùng (mở lại chờ ~1 phút), **512 MB RAM** (Chromium dễ chết),
  **không gắn được disk** → file tải lên mất sau mỗi lần deploy/ngủ. Chỉ nên dùng để **thử**.
- **Starter $7**: 512 MB RAM, không ngủ, gắn disk được. Chromium vẫn chật → chọn **Standard $25**
  (2 GB) nếu dùng tool trình duyệt nhiều. Vì vậy Render chỉ hợp khi anh chủ yếu dùng code + video nhẹ.

Cách nhanh (Blueprint):
1. Copy file cấu hình ra gốc repo rồi push: `cp deploy/render.yaml render.yaml && git add render.yaml && git commit -m render && git push`.
2. <https://dashboard.render.com> → **New → Blueprint** → chọn repo → **Apply**.
3. Render hỏi `ANTHROPIC_API_KEY` (dán key). `TPAGENT_TOKEN` được **tự sinh**: xem trong
   service → **Environment**.
4. Đợi build xong → URL dạng `https://tpagent.onrender.com` → dán token.

Cách tay (không dùng Blueprint): **New → Web Service** → chọn repo → Runtime **Docker** → Region
**Singapore** → Instance **Starter** → **Environment** thêm `ANTHROPIC_API_KEY`, `TPAGENT_TOKEN`
→ **Disks → Add Disk**: mount `/data`, 5 GB → **Health Check Path** `/health` → **Create**.

**Cập nhật**: `git push` là Render tự deploy lại (Auto-Deploy). Hoặc nút **Manual Deploy**.

---

## 3. Fly.io — linh hoạt, tự tắt máy khi rảnh (≈ $3–6/tháng)

Cần dùng dòng lệnh trên máy anh (chỉ gõ, copy-paste được).

1. Cài `flyctl`: Windows: `powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"`;
   Mac/Linux: `curl -L https://fly.io/install.sh | sh`. Rồi `fly auth signup` (hoặc `fly auth login`).
2. Trong thư mục `tpagent`:
   ```bash
   cp deploy/fly.toml fly.toml
   # mở fly.toml: đổi app = "tpagent" thành tên riêng (vd tpagent-thanhphat), dockerfile = "Dockerfile"
   fly launch --no-deploy --copy-config --name tpagent-thanhphat --region sin
   fly volumes create tpagent_data --region sin --size 3 --yes
   fly secrets set ANTHROPIC_API_KEY=sk-ant-... TPAGENT_TOKEN=<token-dài>
   fly deploy
   ```
3. `fly status` cho địa chỉ `https://tpagent-thanhphat.fly.dev` → mở, dán token. Xem log: `fly logs`.

Máy 1 GB RAM shared ≈ $5–6/tháng nếu chạy liên tục; cấu hình đã bật `auto_stop_machines` nên
khi anh không dùng máy tự tắt, chỉ trả tiền volume (~$0.15/GB) + thời gian chạy thực.
Cần 2 GB cho video dài: `fly scale memory 2048`.

**Cập nhật**: `git pull` (nếu lấy code mới) rồi `fly deploy`.

---

## 4. VPS bất kỳ (Vietnix, DigitalOcean, Hetzner… ≈ $5/tháng, 1–2 GB RAM)

Hợp nếu anh muốn máy chủ ở Việt Nam (Vietnix/Viettel IDC, ping thấp) hoặc đã có VPS.

1. Thuê VPS Ubuntu 22.04/24.04, **≥ 1 GB RAM** (2 GB thoải mái), SSH vào bằng root.
2. Cài Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Lấy code & cấu hình:
   ```bash
   git clone https://github.com/<tên-anh>/tpagent.git && cd tpagent
   cp deploy/.env.example .env
   nano .env        # điền ANTHROPIC_API_KEY, TPAGENT_TOKEN ; Ctrl+O, Enter, Ctrl+X để lưu
   docker compose up -d --build
   docker compose logs -f     # thấy "TPAgent server" + token là xong; Ctrl+C để thoát log
   ```
4. Mở cổng 8080 trên firewall của nhà cung cấp (hoặc `ufw allow 8080`), vào `http://<IP-VPS>:8080`.
5. **Nên có HTTPS** (để token không đi dạng chữ thường trên mạng): trỏ một tên miền về IP VPS rồi
   chạy Caddy làm reverse proxy — thêm vào `docker-compose.yml`:
   ```yaml
     caddy:
       image: caddy:2
       restart: unless-stopped
       ports: ["80:80", "443:443"]
       command: caddy reverse-proxy --from tpagent.ten-mien-cua-anh.vn --to tpagent:8080
       volumes: [caddy_data:/data]
   ```
   và `caddy_data:` vào mục `volumes:`. Caddy tự xin chứng chỉ Let's Encrypt. Khi đó bỏ dòng
   `ports` của service `tpagent` để chỉ vào được qua HTTPS.

**Cập nhật**: `cd tpagent && git pull && docker compose up -d --build`. Dữ liệu ở volume `tpagent_data` giữ nguyên.
**Sao lưu**: `docker run --rm -v tpagent_tpagent_data:/data -v $PWD:/backup ubuntu tar czf /backup/tpagent-data.tgz /data`.

---

## 5. Chi phí dự kiến mỗi tháng

| Khoản | Ước tính |
|---|---|
| Máy chủ (Railway Hobby / Fly 1GB / VPS 1–2GB) | $5–7 (≈ 130–180k đ) |
| Render Free | $0 nhưng ngủ, 512 MB, không lưu file |
| API Claude | gói Max tặng $100–200 credit/tháng → thường **0 đ** thêm. 1 phiên code 30 phút trên Sonnet ≈ $0.9; trên Haiku ≈ $0.04 (xem README mục 4) |
| Volume lưu file | 3–5 GB ≈ $0.5–1 |

Muốn rẻ hơn nữa: sửa `/data/.tpagent/config.yaml` trên máy chủ, đổi `standard: claude-haiku-5-5`
rồi restart container.

## 6. Sự cố thường gặp

| Hiện tượng | Nguyên nhân / cách sửa |
|---|---|
| Tool trình duyệt báo lỗi `Target closed` / `browser has been closed` / container tự restart | **Thiếu RAM** — Chromium cần ≥ 1 GB. Nâng gói (Railway: Settings → Resources; Fly: `fly scale memory 2048`; Render: Standard). Log khởi động có dòng cảnh báo nếu giới hạn < 900 MB. |
| Edit video rất chậm / timeout | ffmpeg dùng CPU; gói free/shared-CPU chậm 3–5 lần laptop. Cắt clip ngắn trước, hoặc dùng VPS 2 vCPU. Phụ đề tự động (`video_transcribe`) chạy Whisper trên CPU, model `small` ~1–2 phút cho clip 1 phút. |
| Mở web báo sai token | Xem log khởi động: dòng `Token đăng nhập (TPAGENT_TOKEN)`. Nếu đặt biến trên nền tảng thì phải **redeploy** sau khi sửa. |
| Agent trả lời "không có API key" | Chưa đặt `ANTHROPIC_API_KEY` hoặc gõ sai (phải bắt đầu `sk-ant-`). Log có dòng `!! CHƯA có ANTHROPIC_API_KEY`. |
| Lỗi `401 invalid x-api-key` / `credit balance too low` | Key bị thu hồi hoặc hết credit → vào console.anthropic.com → Billing. |
| File tải lên biến mất sau deploy | Chưa gắn volume vào `/data` (Railway Add Volume; Render Add Disk — gói Free không có). |
| Render Free: mở trang chờ ~1 phút | Service đang "thức dậy". Bình thường; nâng Starter để không ngủ. |
| Chữ tiếng Việt trong video bị ô vuông | Ảnh đã cài `fonts-noto`, `fonts-dejavu`. Nếu truyền `font=` tay thì dùng `Noto Sans` hoặc `DejaVu Sans`. |
| Build lâu / fail vì mạng | Lần đầu tải ảnh Playwright ~1.5 GB. Bấm **Redeploy** / `fly deploy` chạy lại là được. |
| Chạy thử không có key | Đặt biến `TPAGENT_PROVIDER=fake` để kiểm tra giao diện web, rồi bỏ đi khi dùng thật. |

## 7. Kiểm tra nhanh trên máy mình (nếu có Docker)

```bash
docker build -t tpagent .
docker run --rm -e TPAGENT_PROVIDER=fake -e TPAGENT_TOKEN=test -p 8080:8080 tpagent
# tab khác:
curl -s http://localhost:8080/health
```
Mở <http://localhost:8080>, token `test`.
