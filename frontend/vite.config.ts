import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    base: "/",
    build: { outDir: "../app/static/studio", emptyOutDir: true },
    server: { proxy: { "/studio/api": "http://127.0.0.1:8014" } },
});
