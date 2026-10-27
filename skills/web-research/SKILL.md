---
name: web-research
description: Cách nghiên cứu một chủ đề trên web bằng web_search / web_fetch / browser và trả lời có trích nguồn.
---
# Nghiên cứu web có trích nguồn

## Nguyên tắc
- Mỗi kết luận phải có nguồn (URL). Không bịa số liệu; nếu không tìm được, nói rõ.
- Ưu tiên nguồn gốc (trang chính thức, tài liệu, bài báo lớn) hơn blog tổng hợp.
- Dùng ít lượt gọi nhất đủ để trả lời; đừng mở 10 trang khi 3 trang đã đủ.

## Quy trình
1. **Tách câu hỏi** thành 2-4 câu hỏi con cụ thể (giá? ngày? so sánh gì với gì?).
2. **web_search** từng câu hỏi con. Viết truy vấn ngắn, có từ khóa tiếng Anh nếu chủ đề quốc tế, thêm năm nếu cần số liệu mới.
3. **web_fetch** 2-3 URL hứa hẹn nhất cho mỗi câu hỏi con. Đọc kỹ, ghi lại: số liệu, ngày đăng, câu trích.
4. Trang cần đăng nhập / render JavaScript / có nút bấm: dùng `browser_navigate` + `browser_state` + `browser_get_text` (và `browser_click` theo số phần tử). Chụp `browser_screenshot` khi cần nhìn bố cục.
5. **Đối chiếu**: hai nguồn mâu thuẫn -> ghi cả hai và nói nguồn nào mới hơn/đáng tin hơn.
6. Chủ đề rộng: chia việc cho `spawn_subagents_parallel` (mỗi subagent một câu hỏi con, tools `["web"]`, tier `cheap`), rồi tổng hợp.

## Định dạng trả lời
- Mở đầu bằng kết luận ngắn (2-3 câu).
- Thân bài: bảng hoặc gạch đầu dòng, mỗi số liệu kèm `[n]`.
- Cuối: mục **Nguồn** liệt kê `[n] tiêu đề - URL (ngày truy cập)`.
- Trả lời bằng ngôn ngữ của người dùng (tiếng Việt nếu họ viết tiếng Việt), giữ nguyên tên riêng/thuật ngữ gốc.
