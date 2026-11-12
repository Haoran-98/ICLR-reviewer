import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { defineConfig } from "vite";
import { reviewAPI } from './review-api-plugin.js';
import { siteAuth } from './site-auth.js';

export default defineConfig(({ isPreview }) => ({
  plugins: [siteAuth(), reviewAPI()],
  build: { rollupOptions: { input: {
    main: new URL("./index.html", import.meta.url).pathname,
    reviewers: new URL("./reviewers.html", import.meta.url).pathname,
    review: new URL("./review.html", import.meta.url).pathname,
  } } },
  ...(isPreview ? {
  plugins: [siteAuth(), reviewAPI(), {
    name: "lan-entry",
    configurePreviewServer(server) {
      server.httpServer.on("tlsClientError", (error, socket) => {
        console.warn("LAN TLS:", socket.remoteAddress, error.code);
      });
      server.middlewares.use((request, response, next) => {
        response.on("finish", () => console.info("LAN HTTPS:", request.socket.remoteAddress,
          request.method, request.url?.split("?")[0], response.statusCode));
        next();
      });
      // ponytail: one HTTP entry redirects to the existing HTTPS page; no second app server.
      const entry = createServer((request, response) => {
        const path = request.url?.startsWith("/") ? request.url : "/";
        const target = `https://${request.socket.localAddress}:8443${path}`;
        console.info("LAN HTTP redirect:", request.socket.remoteAddress, target);
        response.writeHead(302, { Location: target, "Cache-Control": "no-store" });
        response.end();
      });
      entry.on("error", (error) => console.error("LAN HTTP entry:", error.message));
      entry.listen(5173, "0.0.0.0");
      server.httpServer.once("close", () => entry.close());
    },
  }],
  preview: {
    https: {
      key: readFileSync(new URL("../logs/web_visualization/lan/server-key.pem", import.meta.url)),
      cert: readFileSync(new URL("../logs/web_visualization/lan/server.pem", import.meta.url)),
    },
  },
} : {}),
}));
