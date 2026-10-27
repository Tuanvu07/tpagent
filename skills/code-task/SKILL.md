---
name: code-task
description: Vòng lặp làm việc với mã nguồn - đọc hiểu, lên kế hoạch, sửa bằng edit_file, chạy test, lặp cho tới khi xanh.
---
# Làm việc với mã nguồn: đọc -> kế hoạch -> sửa -> test

## 1. Đọc trước khi sửa
- `list_dir` / `glob_files` để nắm cấu trúc; `grep_files` để tìm nơi dùng hàm, cấu hình, test liên quan.
- `read_file` những file sẽ sửa VÀ file gọi tới chúng. Đừng đoán chữ ký hàm.
- Tìm cách chạy test của dự án (pytest, npm test, go test...) trong README / pyproject / package.json.

## 2. Kế hoạch
- Việc > 2 bước: tạo `task_create` cho từng bước, cập nhật `task_update` khi làm.
- Nêu kế hoạch 2-4 dòng cho người dùng rồi làm ngay; không hỏi lại những gì có thể tự quyết (ghi giả định).
- Chỗ mơ hồ ảnh hưởng lớn (xóa dữ liệu, đổi API công khai): `ask_user`.

## 3. Sửa
- Dùng `edit_file` với `old_string` chép y nguyên (đủ ngữ cảnh để duy nhất). Chỉ `write_file` khi tạo file mới hoặc viết lại gần hết.
- Sửa nhỏ, theo từng đơn vị có thể test được. Giữ phong cách code sẵn có (đặt tên, định dạng, import).
- Không để code chết, không thêm comment "TODO" thay cho việc phải làm.

## 4. Kiểm chứng
- Chạy test liên quan bằng `bash` (có timeout). Lỗi -> đọc traceback, sửa nguyên nhân, chạy lại. Không lặp lại cùng một lệnh mong kết quả khác.
- Sau khi xanh: chạy toàn bộ bộ test một lần, `read_file` lại vùng vừa sửa để soát.
- Git: `git status` / `git diff` để xác nhận chỉ đổi những gì định đổi. Chỉ commit khi người dùng yêu cầu.

## 5. Báo cáo
- Đã làm gì, ở file nào (đường dẫn), kết quả test (số pass/fail), việc còn dở và lý do. Ngắn gọn, không kể lể.
- Ghi vào `memory_append` những quy ước dự án đáng nhớ cho lần sau (cách chạy test, cấu trúc đặc biệt).
