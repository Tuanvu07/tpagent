# TPAgent — "Claude giá rẻ" tự lắp ghép

Agent chạy trong terminal, làm được những việc của Claude Code / Cowork
(code, điều khiển trình duyệt, điều khiển máy tính, edit video, chia việc cho
subagent) nhưng chạy trên model API rẻ, tự chọn model theo độ khó của việc.

- **49 tool**: file/shell/web (11), trình duyệt (16), máy tính (9), video (13), subagent (2)
- **Nhiều nhà cung cấp**: Claude Haiku/Sonnet, DeepSeek, Qwen, Gemini, OpenRouter, Ollama (local, miễn phí)
- **Mặc định chạy toàn Claude ("chế độ Claude Max")**: Haiku 5.5 cho việc nhỏ/subagent, Sonnet 5.5 cho code hằng ngày (đúng model Claude Code dùng), Opus 5.5 cho việc khó. Router tự chọn; `/cost` xem tiền từng phiên. Muốn rẻ hơn thì đổi tier trong `config.yaml`.
- **Nén ngữ cảnh**: giữ prompt < 100K token để luôn ở giá rẻ nhất của Haiku 5.5
- **Hỏi trước khi làm việc nguy hiểm** (xóa file, click chuột, chạy JS), hoặc `--yes` để tự chạy

- **Giao diện web** (`python -m tpagent.server`): dùng trên trình duyệt hoặc điện thoại, upload/tải file, duyệt hành động bằng nút bấm, nhiều phiên song song — chạy được trên cloud rẻ (~$5/tháng), máy anh yếu cũng không sao.
- **Giống Claude Code**: streaming, suy nghĩ mở rộng (extended thinking) cho việc khó, danh sách việc (task list), trí nhớ (`MEMORY.md`), kho skill (`skills/*/SKILL.md`), hỏi lại người dùng khi cần, tiếp tục phiên cũ.

Kế hoạch & kết quả nghiên cứu: xem `PLAN.md`. Quyết định thiết kế: `DECISIONS.md`.

## 0. Cách nhanh nhất: chạy trên cloud, dùng qua trình duyệt

Xem **`docs/deploy.md`** — đẩy thư mục này lên GitHub, bấm deploy trên Railway (hoặc Render/Fly/VPS),
điền 2 biến `ANTHROPIC_API_KEY` và `TPAGENT_TOKEN` (mật khẩu đăng nhập web), mở link là dùng. Hướng dẫn giao diện web: `docs/web.md`.

Chạy web ở máy nhà: `pip install -e ".[web]"` rồi `python -m tpagent.server` → mở http://localhost:8080.

## 1. Cài đặt (5 phút)

```bash
# Python 3.11+ ; tải thư mục này về máy rồi:
cd tpagent
pip install -e ".[browser,computer]"
python -m playwright install chromium        # cho tool trình duyệt
# ffmpeg cần có trong PATH (Windows: winget install ffmpeg ; Mac: brew install ffmpeg)
```

## 2. Cấu hình API key

Copy `config.example.yaml` thành `config.yaml` (hoặc `~/.tpagent/config.yaml`) rồi điền key,
hoặc chỉ cần đặt biến môi trường:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # chỉ cần key này. Lấy tại console.anthropic.com — gói Max được tặng credit API hằng tháng
# Tùy chọn, chỉ khi muốn rẻ hơn Claude:
# export DEEPSEEK_API_KEY=... ; export DASHSCOPE_API_KEY=... ; export GEMINI_API_KEY=...
```

Không có key nào? Vẫn chạy thử được: `TPAGENT_PROVIDER=fake tpagent "đọc README.md"`.
Muốn miễn phí hoàn toàn: cài [Ollama](https://ollama.com), `ollama pull qwen3` rồi đặt tier `cheap: ollama:qwen3`.

## 3. Dùng

```bash
tpagent                                  # chế độ chat (REPL)
tpagent "sửa lỗi trong app.py rồi chạy test"
tpagent --tier strong "thiết kế lại cấu trúc dự án này"
tpagent "vào shopee.vn tìm giá iPhone 17, báo lại 3 kết quả rẻ nhất"
tpagent "cắt khoảng lặng trong raw.mp4, thay phông xanh bằng bg.jpg, thêm nhạc music.mp3, xuất 9:16"
tpagent --yes "viết 3 bài quảng cáo cho tiệm, mỗi bài một subagent chạy song song"
tpagent "mở Notepad và gõ xin chào"      # điều khiển máy tính, cần màn hình thật
```
Tất cả tool (trình duyệt, máy tính, video, subagent) đã bật sẵn — không cần `--enable`.

Lệnh trong REPL: `/model haiku|cheap|strong|<tên model>`, `/cost`, `/tools`, `/yes`, `/clear`, `/help`, `/exit`.

Hướng dẫn chi tiết: `docs/browser_computer.md`, `docs/video.md`.

## 4. Chi phí thực tế

Giá API Claude (USD / 1M token, input/output): Haiku 5.5 $0.10/$0.50 · Sonnet 5.5 $2/$10 · Opus 5.5 $4/$20.

| Việc | Model | Ước tính |
|---|---|---|
| 1 phiên code 30 phút (~300K in / 30K out) | Sonnet 5.5 (mặc định) | ≈ $0.9 (~23.000đ) |
| Cùng phiên đó | Haiku 5.5 | ≈ $0.04 (~1.000đ) |
| Cùng phiên đó | Opus 5.5 | ≈ $1.8 |
| 20 bước điều khiển trình duyệt có ảnh | Sonnet 5.5 | ≈ $0.5 |
| Gói Claude Max 5x / 20x | tặng $100 / $200 credit API mỗi tháng | ≈ 100–200 phiên Sonnet miễn phí |

Agent nén ngữ cảnh và dùng prompt caching (cache read rẻ hơn ~90%) nên phiên dài không tăng giá tuyến tính.

## 5. Giới hạn (nói thật)

- Sonnet 5.5 là model Claude Code dùng hằng ngày nên chất lượng code tương đương; router tự lên Opus (`strong`) khi thấy việc khó, hoặc ép bằng `--tier strong`.
- Điều khiển máy tính qua ảnh chụp màn hình dễ click sai hơn tool trình duyệt (click theo số). Ưu tiên `browser` khi việc nằm trên web.
- Tool máy tính chỉ chạy trên máy có màn hình (Windows/Mac/Linux X11), không chạy trong server.
- Không gõ mật khẩu / OTP / số thẻ bằng agent — tool đã ghi rõ và sẽ hỏi trước.

## 6. Kiểm thử

```bash
pip install -e ".[dev]"
python -m pytest tests -q        # 68 test, không cần mạng hay API key
```

## 7. Cấu trúc

```
tpagent/cli.py          REPL + one-shot
tpagent/core/agent.py   vòng lặp agent, make_default_agent()
tpagent/core/router.py  chọn model + tính tiền
tpagent/core/context.py nén ngữ cảnh
tpagent/core/permissions.py
tpagent/llm/            anthropic_provider, openai_provider (DeepSeek/Qwen/Gemini/Ollama/OpenRouter), fake
tpagent/tools/          files, shell, web, browser, computer, video, subagent
tests/                  68 test
docs/                   hướng dẫn trình duyệt/máy tính, video
```
