import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// separate from vite.config.ts on purpose: that one hard-codes Tauri's
// fixed dev-server port/host (strictPort, TAURI_DEV_HOST) - options that
// make no sense for `vitest run` and would just make it fail to start if
// port 1420 happened to be in use by the real dev server. Same plugins
// (react() for JSX, tailwindcss() so importing a component that pulls in
// Tailwind-classed JSX doesn't error) without the dev-server-only bits.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
