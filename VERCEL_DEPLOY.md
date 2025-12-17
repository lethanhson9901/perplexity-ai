# Triển khai Perplexity API lên Vercel

FastAPI backend (có API key) chạy trong hàm Python của Vercel, hỗ trợ search thường, streaming NDJSON, upload file, và tạo tài khoản Emailnator.

## 1) Chuẩn bị
- Tài khoản Vercel + CLI (`npm i -g vercel`).
- API key bí mật cho backend: giá trị tùy ý, ví dụ chuỗi 32 ký tự (`PPLX_API_KEY`).
- Cookie Perplexity Pro dạng JSON (dùng cho `mode` pro/reasoning/deep research), ví dụ:
  ```json
  {
    "next-auth.session-token": "xxx",
    "next-auth.csrf-token": "yyy%3D"
  }
  ```
  > Nếu copy từ cURL, có thể dùng https://curlconverter.com/python để trích `cookies = {...}` rồi stringify JSON.
- (Tùy chọn) Cookie Emailnator dạng JSON cho endpoint `/v1/account` nếu muốn tự động tạo tài khoản mới (`EMAILNATOR_COOKIES`).
- Mã nguồn repo này (đã có `api/search.py` và `vercel.json` cấu hình `maxDuration` 60s).

## 2) Thiết lập biến môi trường trên Vercel
1. Đăng nhập: `vercel login`.
2. Tạo biến env:
   ```bash
   vercel env add PPLX_API_KEY          # bắt buộc
   vercel env add PPLX_COOKIES          # JSON cookies Perplexity
   vercel env add EMAILNATOR_COOKIES    # tùy chọn cho /v1/account
   ```
   Hoặc qua UI: Project Settings → Environment Variables.

Lưu ý: Giá trị cookie phải là JSON hợp lệ; server sẽ trả lỗi nếu parse thất bại.

## 3) Chạy thử cục bộ với Vercel Dev
```bash
export PPLX_API_KEY='super-secret-key'
export PPLX_COOKIES='{"next-auth.session-token":"...","next-auth.csrf-token":"..."}'
vercel dev
```
- Gọi thử search:
  ```bash
  curl -X POST http://localhost:3000/api/search/v1/search \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $PPLX_API_KEY" \
    -d '{"query":"Giải thích quantum computing","mode":"pro","model":"gpt-5.2"}'
  ```
- Streaming NDJSON:
  ```bash
  curl -N -X POST http://localhost:3000/api/search/v1/search \
    -H "Content-Type: application/json" \
    -H "Accept: application/x-ndjson" \
    -H "X-API-Key: $PPLX_API_KEY" \
    -d '{"query":"Kể một câu chuyện ngắn","stream":true}'
  ```
- Upload file (multipart):
  ```bash
  curl -X POST http://localhost:3000/api/search/v1/search/upload \
    -H "X-API-Key: $PPLX_API_KEY" \
    -F query="Tóm tắt nội dung file" \
    -F files=@document.pdf
  ```

## 4) Triển khai lên Vercel
```bash
vercel        # deploy preview
vercel --prod # deploy production
```
- Đảm bảo đã set env `PPLX_API_KEY`, `PPLX_COOKIES` (và `EMAILNATOR_COOKIES` nếu cần) cho cả Preview/Production.
- Nếu gặp lỗi runtime, nâng cấp CLI: `npm i -g vercel@latest` và deploy lại.
- Sau deploy, thử gọi:
  ```bash
  curl -X POST https://<project>.vercel.app/api/search/v1/search \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $PPLX_API_KEY" \
    -d '{"query":"Tóm tắt AI safety","mode":"pro","model":"gpt-5.2"}'
  ```

## 5) Payload API (tóm tắt)
- Base path: `/api/search`
- `POST /v1/search` (JSON): search thường hoặc stream (`"stream":true`)
- `POST /v1/search/upload` (multipart): search kèm `files=@...`
- `POST /v1/account` (JSON): tạo tài khoản mới bằng Emailnator cookies, trả về cookies mới
- `GET /health`: không cần API key, kiểm tra trạng thái
- `GET /v1/models`, `GET /v1/usage`: yêu cầu API key, cung cấp thông tin hỗ trợ

Trường yêu cầu chính: `query` (string), các trường khác giống README (mode/model/sources/language/incognito/follow_up/files).

## 6) Lưu ý bảo mật
- Không commit cookie vào repo.
- Luôn bật API key (`PPLX_API_KEY`) cho backend public.
- Xoay cookie khi hết hạn; update biến env và redeploy (hoặc `vercel env pull` + `vercel deploy`).
