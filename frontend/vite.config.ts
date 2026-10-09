import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 개발 모드(npm run dev, :5173)에서는 /api 요청을 FastAPI(:8000)로 넘긴다.
// 배포 모드(npm run build)에서는 dist/를 server.py가 직접 서빙한다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
