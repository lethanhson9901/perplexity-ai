# Triển khai Perplexity API lên Vercel

Hướng dẫn triển khai `api/search.py` (wrapper `perplexity.Client`) trên Vercel với cookie tài khoản Pro.

## 1) Chuẩn bị
- Tài khoản Vercel + CLI (`npm i -g vercel`).
- Cookie Perplexity Pro dạng JSON, ví dụ:
  ```json
  {
    "next-auth.session-token": "xxx",
    "next-auth.csrf-token": "yyy%3D"
  }
  ```
  > Nếu copy từ cURL, có thể dùng https://curlconverter.com/python để trích `cookies = {...}` rồi stringify JSON.
- Mã nguồn repo này (đã có `api/search.py` và `vercel.json` cấu hình `maxDuration` cho hàm Python).

## 2) Thiết lập biến môi trường trên Vercel
1. Đăng nhập: `vercel login`.
2. Tạo biến env:
   ```bash
   vercel env add PPLX_COOKIES
   # dán chuỗi JSON cookie vào prompt
   ```
   Hoặc qua UI: Project Settings → Environment Variables → key `PPLX_COOKIES`, value là chuỗi JSON ở trên (Production + Preview + Development).

Lưu ý: Giá trị phải là một chuỗi JSON hợp lệ; server sẽ báo lỗi nếu không parse được hoặc không phải dict.

## 3) Chạy thử cục bộ với Vercel Dev
```bash
vercel dev
```
- Đặt env `PPLX_COOKIES` trong shell trước khi chạy (`export PPLX_COOKIES='{"next-auth.session-token":"..."}'`).
- Gọi thử:
  ```bash
  curl -X POST http://localhost:3000/api/search \
    -H "Content-Type: application/json" \
    -d '{"query":"Giải thích quantum computing", "mode":"pro", "model":"gpt-5.2"}'
  ```
- Phản hồi: `{"data": {...}}` hoặc lỗi kèm thông báo.

## 4) Triển khai lên Vercel
```bash
vercel        # deploy preview
vercel --prod # deploy production
```
- Đảm bảo đã set env ở bước 2 cho cả môi trường Preview/Production.
- Nếu gặp lỗi runtime, nâng cấp CLI: `npm i -g vercel@latest` và deploy lại.
- Mặc định `maxDuration` của hàm Python đã set 60s trong `vercel.json`; nếu query Pro lâu, giữ nguyên để tránh 504 timeout.
- Sau deploy, thử gọi:
  ```bash
  curl -X POST https://<project>.vercel.app/api/search \
    -H "Content-Type: application/json" \
    -d '{"query":"Tóm tắt AI safety", "mode":"pro", "model":"gpt-5.2"}'
  ```

## 5) Payload API
- URL: `/api/search`
- Method: `POST` JSON.
- Trường:
  - `query` (string, bắt buộc)
  - `mode` (string, mặc định `auto`)
  - `model` (optional, tùy `mode`)
  - `sources` (list, mặc định `["web"]`)
  - `language` (mặc định `en-US`)
  - `incognito` (bool, mặc định `false`)
  - `follow_up`, `files` (tùy chọn; `files` hiện chỉ nhận dict tên→dữ liệu, không encode multipart trong handler này).
- Stream chưa bật; trả full JSON `{"data": ...}`.

## 6) Lưu ý bảo mật
- Không commit cookie vào repo.
- Nếu dùng repo công khai, chỉ set `PPLX_COOKIES` trong env trên Vercel/CI.
- Xoay cookie khi hết hạn; update biến env và redeploy (hoặc `vercel env pull` + `vercel deploy`).
