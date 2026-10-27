---
name: video-ad-vn
description: Quy trình dựng video quảng cáo talking-head 9:16 (Reels/TikTok) từ clip quay phông xanh - cắt khoảng lặng, chroma key, nhạc nền, caption.
---
# Dựng video quảng cáo talking-head 9:16

Dùng khi người dùng đưa một clip quay người nói trước phông xanh (hoặc phông thường) và muốn ra video quảng cáo ngắn đăng Facebook Reels / TikTok / YouTube Shorts.

## Chuẩn bị
1. `video_info(path)` để biết độ dài, độ phân giải, có audio hay không. Nếu không có audio: báo người dùng, đừng cắt khoảng lặng.
2. Hỏi (ask_user) nếu chưa rõ: ảnh/video nền muốn dùng, file nhạc, có cần caption không, chữ hiển thị đầu video (tên tiệm, số điện thoại).
3. Mọi file trung gian đặt trong thư mục `out/` cạnh clip gốc; đặt tên theo bước (`01_cut.mp4`, `02_key.mp4`...).

## Quy trình (theo đúng thứ tự)
1. **Cắt khoảng lặng** - `video_cut_silence(path, out="out/01_cut.mp4", noise_db=-30, min_silence=0.5)`.
   Nếu cắt quá tay (mất đầu câu) tăng `min_silence` lên 0.7-0.8 hoặc `noise_db` xuống -35.
2. **Chroma key** - `video_chromakey(path="out/01_cut.mp4", background=<ảnh/video nền>, out="out/02_key.mp4", color="0x00FF00")`.
   Viền xanh còn sót: thử `similarity` 0.35-0.45. Phông không phải xanh lá: đổi `color` cho đúng mã màu.
3. **Khung 9:16** - `video_resize(path, preset="9:16", out="out/03_916.mp4", mode="crop")` (dùng `mode="pad"` nếu không muốn mất mép).
4. **Nhạc nền** - `video_add_music(path, music_path, out="out/04_music.mp4", music_volume=0.12)`. Nhạc phải nhỏ hơn giọng nói; 0.10-0.15 là vừa.
5. **Caption** - `video_transcribe(path, language="vi")` để ra file SRT, đọc lại SRT sửa lỗi chính tả/tên riêng (edit_file), rồi `video_captions(path, srt_path, out="out/05_caption.mp4", fontsize=16, margin=60)`.
6. **Chữ mở đầu / CTA** - `video_add_text(path, text, out="out/06_final.mp4", position="top", start=0, end=4)` cho tên tiệm, số điện thoại, ưu đãi. Giữ dưới 2 dòng, 3-4 giây.
7. `video_thumbnail(path, time=1.0)` để lấy ảnh bìa, `video_info` lần cuối để xác nhận 1080x1920 và độ dài.

## Kiểm tra trước khi giao
- Độ dài 20-60 giây là tốt nhất cho quảng cáo.
- Caption không che mặt; chữ CTA không trùng vị trí caption.
- Báo người dùng đường dẫn file cuối cùng và từng file trung gian (để họ quay lại bước nào nếu cần).
- Nếu ffmpeg báo lỗi: đọc kỹ thông báo, sửa tham số, không lặp lại y nguyên.
