# Hướng dẫn: dùng TPAgent qua trình duyệt (giao diện web)

Giao diện web cho phép anh dùng TPAgent giống Claude Cowork: mở trình duyệt (máy tính
hoặc điện thoại), gõ việc cần làm, xem agent chạy từng bước, duyệt lệnh nguy hiểm,
tải file lên / tải kết quả về. Server có thể chạy trên máy anh hoặc trên một máy
chủ cloud (Docker) để máy yếu không phải gánh.

## 1. Cài và chạy

```bash
pip install -e ".[web]"              # fastapi, uvicorn, websockets, python-multipart
export ANTHROPIC_API_KEY=sk-ant-...  # hoặc TPAGENT_PROVIDER=fake để chạy thử không cần key
python -m tpagent.server             # mặc định cổng 8080, lắng nghe 0.0.0.0
```

Tùy chọn:

```bash
python -m tpagent.server --port 9000 --workspace /data/tpagent --token mat-khau-cua-anh
```

| Biến môi trường / tham số | Ý nghĩa | Mặc định |
|---|---|---|
| `PORT` / `--port` | Cổng web | 8080 |
| `TPAGENT_TOKEN` / `--token` | Mã đăng nhập dùng chung (1 mã duy nhất) | tự sinh, in ra màn hình khi khởi động |
| `TPAGENT_WORKSPACE` / `--workspace` | Thư mục chứa file của các phiên | `./workspace` |
| `TPAGENT_PROVIDER` | `fake` để chạy thử, không tốn tiền | (theo config.yaml) |

Khi server chạy, nó in ra:

```
TPAgent web: http://0.0.0.0:8080  (mở trình duyệt, dán token để đăng nhập)
Workspace: /home/tuan/tpagent/workspace
Token (tự sinh, đặt TPAGENT_TOKEN để cố định): kJ3...
```

## 2. Đăng nhập

Mở `http://<địa-chỉ-máy-chủ>:8080`. Dán **token** vào ô và bấm *Đăng nhập*. Token được
lưu trong trình duyệt (localStorage) nên lần sau không cần nhập lại; bấm *Đăng xuất*
để xóa. Nếu để server tự sinh token, mỗi lần khởi động lại sẽ ra token mới — đặt
`TPAGENT_TOKEN` để cố định.

Nếu mở ra Internet, hãy đặt server sau một reverse proxy có HTTPS (Caddy, nginx,
Cloudflare Tunnel…) để token không bị lộ. Không chia sẻ token cho người khác: ai có
token là điều khiển được agent (và máy chủ) của anh.

## 3. Phiên làm việc (sessions)

- Bấm **+ Phiên mới** ở cột trái. Mỗi phiên là một cuộc hội thoại riêng, agent nhớ
  ngữ cảnh các câu trước trong cùng phiên.
- Mỗi phiên có **thư mục riêng** `workspace/<mã-phiên>/`. Mọi file anh tải lên và mọi
  file agent tạo ra đều nằm trong đó; agent không đọc/ghi được ra ngoài thư mục này
  (trừ tool `bash`, nên lệnh nguy hiểm mới phải hỏi).
- Lịch sử hội thoại lưu ở `~/.tpagent/sessions/<mã-phiên>.json`; khởi động lại server
  vẫn mở lại được phiên cũ và tiếp tục chat.
- Biểu tượng 🗑 xóa phiên **và toàn bộ file** của phiên đó.
- Chi phí ($) của phiên hiện ở góc trên bên phải, cập nhật sau mỗi lần gọi model.

## 4. Gõ việc, chọn model, duyệt lệnh

- **Tự động / Nhanh-rẻ / Chuẩn / Mạnh**: chọn tier model cho câu lệnh kế tiếp
  (`cheap` / `standard` / `strong` trong `config.yaml`). *Tự động* để router đoán.
- **Tự duyệt**: bật thì agent không hỏi khi chạy lệnh nguy hiểm (xóa file, click
  chuột, chạy JS…). Chỉ bật khi anh tin tưởng việc đang giao.
- Khi agent cần làm việc nguy hiểm, một **thẻ vàng** hiện ra với nội dung lệnh:
  *Cho phép* (1 lần) · *Luôn cho phép* (tool này, trong phiên này) · *Từ chối*.
  Không trả lời trong **10 phút** thì server tự **từ chối**.
- Khi agent cần hỏi anh (ví dụ chọn 1 trong vài phương án), một **thẻ xanh** hiện ra:
  bấm nút lựa chọn hoặc gõ câu trả lời tự do.
- Nút **■ Dừng** hủy việc đang chạy. Lịch sử vẫn được lưu và chat tiếp được.
- Các bước agent gọi tool hiện dạng thẻ thu gọn (tên tool + tham số); bấm để xem kết quả.
- Mất mạng giữa chừng? Agent vẫn chạy tiếp trên server; mở lại trang là thấy trạng
  thái và các câu hỏi đang chờ.

## 5. File: tải lên, xem, tải về

Bấm 📁 để mở bảng file của phiên:

- **Kéo thả** file vào vùng chấm chấm (hoặc bấm *chọn file*), chọn được nhiều file.
  Kéo thả vào bất kỳ chỗ nào trên trang cũng được.
- Danh sách file có nút ⬇ để tải về. Bấm tên file để **xem trước**: ảnh (png/jpg/
  gif/webp) hiện ngay, video (mp4/webm) có trình phát.
- Sau mỗi bước tool chạy, danh sách tự làm mới nên anh thấy ngay file agent vừa tạo.

Ví dụ luồng làm video quảng cáo: Phiên mới → tải `raw.mp4`, `bg.jpg`, `music.mp3` →
gõ "cắt khoảng lặng trong raw.mp4, thay phông xanh bằng bg.jpg, thêm nhạc music.mp3,
xuất 9:16 tên final.mp4" → chờ → bấm `final.mp4` để xem rồi ⬇ tải về.

## 6. An toàn

- Một token duy nhất bảo vệ toàn bộ API và WebSocket. Mọi yêu cầu không có token
  đúng bị từ chối (401). Trang đăng nhập và file tĩnh thì mở công khai (không có dữ liệu).
- Đường dẫn tải về bị kiểm tra chống `../` — không đọc được file ngoài thư mục phiên.
  Tên file tải lên bị cắt bỏ phần thư mục.
- Agent chỉ thấy thư mục của phiên hiện tại. Server chạy **một việc tại một thời điểm**
  (các phiên khác xếp hàng) để thư mục làm việc không bị lẫn.
- Tool `bash` chạy với quyền của tiến trình server: hãy chạy server bằng user thường
  (hoặc trong Docker), không chạy bằng root trên máy có dữ liệu quan trọng.
- Không gõ mật khẩu / OTP / số thẻ vào chat cho agent.

## 7. API (cho người muốn tích hợp)

Tất cả cần header `Authorization: Bearer <token>` (hoặc `?token=` cho WebSocket/link tải).

| Method | Đường dẫn | Việc |
|---|---|---|
| GET | `/api/me` | kiểm tra token, xem tier mặc định |
| GET | `/api/sessions` | danh sách phiên (id, tiêu đề, chi phí, mtime, đang chạy?) |
| POST | `/api/sessions` | tạo phiên mới → `{"id"}` |
| GET | `/api/sessions/{id}` | lịch sử tin nhắn + chi phí |
| DELETE | `/api/sessions/{id}` | xóa phiên và thư mục file |
| GET | `/api/files/{id}` | danh sách file của phiên |
| POST | `/api/files/{id}` | tải lên (multipart, trường `files`, nhiều file; `subdir` tùy chọn) |
| GET | `/api/files/{id}/download?path=…` | tải file (`&inline=1` để xem trong trình duyệt) |
| WS | `/ws/{id}?token=…` | chạy việc và nhận sự kiện |

WebSocket — trình duyệt gửi:

```json
{"type":"task","text":"...","tier":null,"auto_approve":false}
{"type":"approval_response","id":"...","approved":true,"always":false}
{"type":"answer","id":"...","text":"..."}
{"type":"cancel"}
```

Server gửi: `status`, `start`, `cost`, `text_delta`, `text`, `tool_call`, `tool_result`,
`done`, cùng `approval_request`, `question`, `queued`, `cancelled`, `error`.
