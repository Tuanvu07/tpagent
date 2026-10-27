# Hướng dẫn: tool Trình duyệt & Điều khiển máy tính

Hai bộ tool này là **tùy chọn**, chỉ nạp khi bật:

```bash
tpagent --enable browser "mở shopee.vn, tìm 'máy đếm tiền' và cho tôi 3 giá rẻ nhất"
tpagent --enable computer "mở Notepad và gõ chữ Xin chào"
tpagent --enable browser,computer "..."
```

## 1. Trình duyệt (`browser_*`) — Playwright, cách của browser-use

Thay vì đọc HTML thô, model nhận **danh sách phần tử đánh số** + ảnh chụp:

```
[12] <button> Đăng nhập
[13] <input type=text placeholder="Tìm kiếm">
```

Model chỉ cần gọi `browser_click(12)` hoặc `browser_type(13, "vàng 9999", press_enter=true)`.
Sau mỗi hành động tool tự chờ trang tải và trả về trạng thái mới (chỉ chữ, không ảnh — để tiết kiệm token).
Khi cần nhìn, gọi `browser_state` hoặc `browser_screenshot` (ảnh thu nhỏ còn 1024px ngang).

### Cài đặt

```bash
pip install playwright
python -m playwright install chromium
```

### Biến môi trường

| Biến | Ý nghĩa |
|---|---|
| `TPAGENT_BROWSER_HEADLESS=1` / `0` | Ép chạy ẩn / hiện cửa sổ. Mặc định: hiện nếu máy có màn hình, ẩn nếu không. |
| `TPAGENT_CDP_URL=http://localhost:9222` | Gắn vào Chrome **đang mở của anh** (giữ đăng nhập Facebook, Shopee, ngân hàng…) thay vì mở Chromium mới. |

### Dùng Chrome thật của anh qua CDP

1. Đóng hết Chrome, rồi mở lại với cổng gỡ lỗi:
   - **Windows:** `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\tpagent-chrome"`
   - **macOS:** `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222`
   - **Linux:** `google-chrome --remote-debugging-port=9222`
2. Đăng nhập các trang cần dùng trong cửa sổ Chrome đó (một lần).
3. Chạy: `TPAGENT_CDP_URL=http://localhost:9222 tpagent --enable browser "..."`

Khi gắn qua CDP, `browser_close` **không** tắt Chrome của anh.

### Tool nguy hiểm (hỏi trước, trừ khi chạy `--yes`)

- `browser_eval(js)` — chạy JavaScript tùy ý trong trang.
- `browser_submit(index)` — gửi form (đăng nhập, đặt hàng…).

Các tool còn lại (`navigate`, `click`, `type`, `select`, `scroll`, `back`, `get_text`, `screenshot`, `tabs`, `new_tab`, `switch_tab`, `wait`, `close`) chạy không cần hỏi.
Lưu ý: `browser_type` + `press_enter=true` cũng có thể gửi form; model được nhắc **không bao giờ tự nhập mật khẩu/OTP/số thẻ**.

## 2. Điều khiển máy tính (`computer_*`) — vòng lặp kiểu computer-use

Vòng lặp: `computer_screenshot` → model nhìn ảnh → `computer_click(x, y)` → chụp lại → …

- Ảnh chụp được **thu nhỏ còn tối đa 1280px ngang**; tool báo kèm tỷ lệ và kích thước màn hình thật.
  Model luôn dùng tọa độ **trên ảnh**, tool tự nhân ngược về pixel thật.
- Tool: `computer_screenshot`, `computer_click(x,y,button=left|right|double)`, `computer_move`, `computer_type`,
  `computer_key("ctrl+c")`, `computer_scroll`, `computer_drag`, `computer_open_app("notepad")`, `computer_wait`.
- `computer_type` với chữ có dấu tiếng Việt sẽ dán qua clipboard (cần `pyperclip`).
- `computer_open_app`: Windows dùng `start`, macOS dùng `open -a`, Linux chạy trực tiếp hoặc `xdg-open`.

### Cài đặt

```bash
pip install pyautogui mss pillow pyperclip
```

Linux cần phiên đồ họa (X11; Wayland có thể cần `xdotool`/XWayland). Không có màn hình (ví dụ server, Docker)
thì tool vẫn nạp được nhưng trả lỗi rõ ràng: `computer tools unavailable: No display found`.

### An toàn

- Tất cả tool trừ `screenshot` và `wait` đều là **nguy hiểm** → agent hỏi trước mỗi lần (bỏ hỏi bằng `--yes`).
- `pyautogui.FAILSAFE` bật: **đưa chuột vào góc màn hình** để dừng khẩn cấp.
- Model được dặn không gõ mật khẩu, mã OTP, số thẻ — anh tự nhập khi được yêu cầu.
- Khi việc làm được trong trình duyệt, ưu tiên `browser_*` (click theo số chính xác hơn click theo ảnh với model rẻ).

## 3. Kiểm thử

```bash
python -m pytest tests/test_browser.py tests/test_computer.py -q
```

Test trình duyệt tự bỏ qua nếu Chromium chưa cài; test máy tính không cần màn hình.
