# Hướng dẫn edit video quảng cáo bằng TPAgent

Bộ tool `video` dùng **ffmpeg** để xử lý video nói trước ống kính (talking-head) cho tiệm
Cầm Đồ Thành Phát: cắt khoảng lặng, thay phông xanh, chèn nhạc, phụ đề, xuất đúng khung
TikTok/Reels 9:16. Anh chỉ cần gõ yêu cầu bằng tiếng Việt, agent sẽ tự gọi đúng tool theo thứ tự.

## Cài đặt

```bash
# ffmpeg bắt buộc (Ubuntu/Debian):  sudo apt install ffmpeg
# Windows: winget install ffmpeg   |  macOS: brew install ffmpeg
# Phụ đề tự động (tùy chọn, chạy CPU được):
pip install faster-whisper
```

Bật module trong `config.yaml`: `enabled_tools: [video]` hoặc chạy `tpagent --tools video`.

## Nguyên tắc an toàn

- **Không bao giờ ghi đè file gốc.** Mỗi bước tạo file mới cạnh file gốc, ví dụ
  `raw.mp4 → raw_nosilence.mp4 → raw_nosilence_keyed.mp4 ...`
- Mỗi tool trả về đường dẫn file kết quả và thời lượng mới để anh kiểm tra.
- Không tool nào xóa file, nên không cần xác nhận quyền.

## Các tool có sẵn

| Tool | Việc làm | Tham số chính |
|---|---|---|
| `video_info` | Xem thời lượng, độ phân giải, fps, codec, âm thanh | `path` |
| `video_trim` | Cắt từ giây A đến giây B | `start`, `end` |
| `video_cut_silence` | Tự cắt khoảng lặng, giữ phần nói | `noise_db=-30`, `min_silence=0.5`, `padding=0.15` |
| `video_chromakey` | Thay phông xanh bằng ảnh / video / màu (`#1e3a5f`) | `background`, `color=0x00FF00`, `similarity=0.3` |
| `video_add_music` | Chèn nhạc nền, tự lặp, fade out, **tự hạ nhạc khi đang nói** | `music_path`, `music_volume=0.15`, `duck=true` |
| `video_resize` | Xuất `9:16` (1080x1920), `16:9`, `1:1` | `preset`, `mode=crop|pad` |
| `video_add_text` | Chèn tiêu đề có nền tối ở trên/giữa/dưới, theo khoảng thời gian | `text`, `position`, `fontsize`, `start`, `end` |
| `video_transcribe` | Nghe giọng nói → file `.srt` (tiếng Việt) bằng faster-whisper | `model=small`, `language=vi` |
| `video_captions` | Đóng phụ đề từ file `.srt` vào video | `srt_path`, `fontsize`, `outline`, `margin` |
| `video_concat` | Ghép nhiều clip (tự scale về cùng kích cỡ) | `paths`, `out` |
| `video_speed` | Tăng/giảm tốc (1.25x, 2x, 0.5x...) | `factor` |
| `video_thumbnail` | Lấy 1 khung hình làm ảnh bìa | `time` |
| `video_extract_audio` | Tách tiếng ra MP3 | — |

## Ví dụ câu lệnh gõ cho agent

Quy trình trọn gói (hay dùng nhất):

```
cắt khoảng lặng trong raw.mp4, thay phông xanh bằng bg.jpg, thêm nhạc music.mp3, xuất 9:16
```

```
quay xong clip quang_cao_dao_han.mp4 rồi, làm phụ đề tiếng Việt tự động, đóng phụ đề vào,
chèn chữ "Đáo hạn thẻ phí 1.5%" ở trên trong 4 giây đầu, xuất Reels 9:16 tên final.mp4
```

Từng bước lẻ:

```
xem thông tin file raw.mp4
cắt raw.mp4 từ giây 3 đến giây 45
cắt im lặng trong raw.mp4, ngưỡng -35dB, khoảng lặng từ 0.4 giây
thay phông xanh trong raw.mp4 bằng màu xanh đậm #1e3a5f
thay phông xanh bằng video background_shop.mp4, phông hơi bị bóng nên tăng similarity lên 0.4
thêm nhạc nen.mp3 vào final.mp4, volume 0.1, hạ nhạc khi nói
đổi raw.mp4 sang 9:16, cắt hai bên (crop)
đổi raw.mp4 sang 1:1 nhưng thêm viền đen thay vì cắt (pad)
chèn chữ "Cầm Đồ Thành Phát - Hóc Môn" ở dưới, chữ vàng, từ giây 0 đến giây 5
tạo phụ đề srt cho final.mp4 bằng model small
đóng phụ đề final.srt vào final.mp4, chữ to 20, viền 3
ghép intro.mp4, body.mp4, outro.mp4 thành ad_full.mp4
tăng tốc raw.mp4 lên 1.2 lần
lấy ảnh bìa ở giây 2.5 của final.mp4
tách tiếng từ raw.mp4 ra mp3
```

## Mẹo cho video phông xanh

- Đèn đều, đứng cách phông ≥ 1m để không bị bóng. Nếu viền còn xanh: tăng `similarity`
  (0.35–0.45) và `blend` (0.15). Nếu mất chi tiết tóc/áo: giảm `similarity` (0.2–0.25).
- Phông không phải xanh lá (ví dụ xanh dương): đổi `color` thành `0x0000FF`.
- Làm **cắt khoảng lặng trước**, rồi mới chromakey/chèn nhạc để đỡ phải xử lý lại.
- Thứ tự gợi ý: `cut_silence → chromakey → add_text → captions → add_music → resize 9:16`.
  Resize cuối cùng để chữ/phụ đề được canh đúng khung dọc.
- Phụ đề tiếng Việt: model `small` đủ tốt và nhanh; `medium` chính xác hơn nhưng chậm ~3 lần.
  Mở file `.srt` sửa lại vài chữ sai (tên tiệm, số tiền) rồi mới `video_captions`.

## Khi gặp lỗi

- `ffmpeg failed ... No such filter: subtitles` → bản ffmpeg thiếu libass, cài bản đầy đủ.
- `faster-whisper is not installed` → chạy `pip install faster-whisper`.
- `no speech segments detected` → giọng nhỏ, hạ ngưỡng xuống `noise_db=-40`.
- Video quá dài: mỗi tool có timeout 10 phút; cắt clip ngắn trước rồi ghép lại.
