# KẾ HOẠCH: TPAgent — "Claude giá rẻ" tự lắp ghép

> Mục tiêu: một agent chạy trên máy anh Tuấn, làm được 90% việc Claude Code / Cowork làm
> (code, điều khiển trình duyệt, điều khiển máy tính, edit video, chia việc cho subagent)
> nhưng chạy trên model API rẻ gấp 10–100 lần, chọn model theo độ khó của từng việc.
>
> Lưu ý thật: đây là **bộ khung agent** (harness) — phần "thông minh" vẫn là model API.
> Không thể "tạo ra model Claude" — nhưng bộ khung + model rẻ là thứ tạo ra 80–90% giá trị.

## 1. Kết quả nghiên cứu (27/10/2026)

### 1.1 Giá model API (USD / 1 triệu token, input / output)

| Model | Input | Output | Ghi chú |
|---|---|---|---|
| **Claude Haiku 5.5** | $0.10 | $0.50 | Rẻ hơn Haiku 4.5 90%; >100K token prompt thì $0.50/$2.50. Có vision, tool-use, computer-use. Gói Max 5x được tặng $100 API credit/tháng, Max 20x $200 (không dùng được cho Claude Code) |
| Claude Sonnet 5.5 | cao hơn | cao hơn | Dùng khi việc khó (kiến trúc, debug khó) |
| DeepSeek V4 Flash | $0.14–0.22 | $0.28–0.66 | Giá giờ cao điểm/thấp điểm; mạnh về code |
| Qwen3.7 Flash | $0.03 | $0.13 | Rẻ nhất thị trường |
| Qwen3.8 Flash | $0.15 | $0.47 | |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 | |
| Gemini 3 Flash | $0.50 | $3.00 | 1M context |
| Ollama (local) | $0 | $0 | Qwen/Llama chạy trên máy, chậm nhưng miễn phí |

**Kết luận:** Haiku 5.5 là "xương sống" tốt nhất (rẻ, có vision để nhìn màn hình/trình duyệt, tool-use chuẩn, và anh đang có Max → có credit API miễn phí hằng tháng). Qwen Flash / DeepSeek làm lớp rẻ hơn nữa cho việc đơn giản. Sonnet chỉ gọi khi thật sự cần.

### 1.2 Các mảnh ghép mã nguồn mở đã có sẵn

| Mảnh | Dùng gì | Vì sao |
|---|---|---|
| Vòng lặp agent + tool-use | **Tự viết** (~400 dòng Python), tham khảo OpenCode, open-claude-code, Claude Agent SDK | Kiểm soát hoàn toàn, không khóa vào 1 nhà cung cấp |
| Gọi nhiều model | SDK `anthropic` + SDK `openai` (DeepSeek, Qwen, Gemini, Ollama, OpenRouter đều tương thích OpenAI) | 2 SDK phủ 100% thị trường |
| Trình duyệt | **Playwright** + cách của browser-use: liệt kê phần tử đánh số + ảnh chụp | Model rẻ click theo số chính xác hơn đọc HTML thô |
| Điều khiển máy tính | **pyautogui + mss** (screenshot → model vision → click/type), giống vòng lặp computer-use của Anthropic/E2B Surf | Chạy được Windows/Mac/Linux |
| Edit video | **ffmpeg** (cắt khoảng lặng, ghép, chroma key xanh, chèn nhạc, resize 9:16, phụ đề) + Whisper (tùy chọn) | Đúng nhu cầu video quảng cáo tiệm |
| Subagent | Tự viết: agent cha spawn agent con với bộ tool thu hẹp, chạy song song bằng asyncio | Giống Agent tool của Claude Code |
| Router tiết kiệm tiền | Tự viết: phân loại việc → chọn tier (cheap / standard / strong), theo dõi chi phí từng phiên | Đây là phần "giá rẻ" |
| Nén ngữ cảnh | Tự viết: tóm tắt lịch sử khi vượt ngưỡng token (giữ prompt < 100K để hưởng giá rẻ của Haiku) | Tránh rơi vào giá cao |

## 2. Kiến trúc

```
tpagent/
├── tpagent/
│   ├── cli.py            # REPL + one-shot: tpagent "làm X"
│   ├── config.py         # đọc config.yaml + env
│   ├── core/
│   │   ├── agent.py      # vòng lặp: gọi model → chạy tool → lặp
│   │   ├── router.py     # chọn model theo độ khó, tính tiền
│   │   ├── context.py    # nén ngữ cảnh khi quá dài
│   │   └── permissions.py# hỏi trước khi làm việc nguy hiểm
│   ├── llm/
│   │   ├── base.py       # giao diện chung: chat(messages, tools) -> (text, tool_calls, usage)
│   │   ├── anthropic_provider.py
│   │   └── openai_provider.py   # DeepSeek/Qwen/Gemini/Ollama/OpenRouter
│   └── tools/
│       ├── base.py       # Tool(name, description, schema, run)
│       ├── files.py      # read/write/edit/glob/grep
│       ├── shell.py      # bash với timeout
│       ├── web.py        # fetch + search
│       ├── browser.py    # Playwright
│       ├── computer.py   # pyautogui + mss
│       ├── video.py      # ffmpeg
│       └── subagent.py   # spawn agent con
├── tests/
├── config.example.yaml
├── README.md             # hướng dẫn tiếng Việt
└── pyproject.toml
```

Luồng 1 lượt:
1. User gõ việc → `router` đoán tier (cheap/standard/strong) → chọn model.
2. `agent` gửi system prompt + lịch sử + danh sách tool → model trả text hoặc tool_calls.
3. Tool nguy hiểm (xóa file, bash lạ, click chuột) → `permissions` hỏi (hoặc auto nếu `--yes`).
4. Chạy tool, nối kết quả, lặp tới khi model trả lời xong hoặc hết `max_turns`.
5. `context` nén khi > 80K token. `router` cộng tiền từng call, in `/cost`.

## 3. Lịch làm việc đêm nay (agent chạy song song)

| # | Agent | Việc | Đầu ra |
|---|---|---|---|
| A | core | llm/, core/, tools/files+shell+web, cli.py, config, pyproject, tests | `tpagent "..."` chạy được |
| B | browser+computer | tools/browser.py, tools/computer.py + tests (headless) | 2 bộ tool cắm vào core |
| C | video+subagent | tools/video.py, tools/subagent.py + tests với ffmpeg | 2 bộ tool cắm vào core |
| D | kiểm thử tổng | chạy toàn bộ test, smoke test CLI với provider giả, viết README tiếng Việt | gói zip giao anh |

## 4. Chi phí dự kiến khi dùng

- 1 phiên code 30 phút trên Haiku 5.5: ~300K token in + 30K out ≈ **$0.045** (~1.100đ).
- 1 phiên điều khiển trình duyệt 20 bước có ảnh: ~200K in ≈ **$0.03**.
- Với $100 credit/tháng của gói Max 5x: **~2.000 phiên/tháng miễn phí**.
- So sánh: cùng việc trên Sonnet/Opus đắt gấp 30–150 lần.

## 5. Những gì KHÔNG làm được bằng model rẻ (nói thật)

- Việc kiến trúc phức tạp, debug nhiều file liên quan: Haiku kém Sonnet/Opus rõ rệt → router sẽ tự lên Sonnet khi cần (vẫn rẻ hơn Opus).
- Điều khiển máy tính qua ảnh: model rẻ click sai nhiều hơn; nên ưu tiên tool trình duyệt (click theo số) khi được.
- Không có "trí nhớ dài hạn" và kho skill phong phú như Claude app — có thể bổ sung sau.

## Nguồn
- Haiku 5.5 pricing: https://www.vktr.com/ai-platforms/anthropic-cuts-smallmodel-pricing-90-with-claude-haiku-55/ , https://apidog.com/blog/claude-haiku-5-5-pricing/
- Giá DeepSeek/Qwen/Gemini: https://dev.to/liekeai/llm-api-pricing-comparison-2026-1nga , https://www.morphllm.com/llm-api , https://anotherwrapper.com/tools/llm-pricing/deepseek-r1/qwen3.7-flash
- browser-use: https://github.com/browser-use/browser-use , https://browser-use.com/posts/ai-browser-agent-benchmark
- Computer-use loop: https://e2b.dev/docs/use-cases/computer-use.md , https://pinggy.io/blog/control_computer_with_ai_agents/
- Claude Code alternatives: https://levelup.gitconnected.com/opencode-the-best-claude-code-alternative-87b17e384d58 , https://pypi.org/project/ccvibe/
