#!/usr/bin/env node
/**
 * Writes vercel.json before build.
 * Set POOL_API_ORIGIN in Vercel env (e.g. https://your-tunnel.example.com)
 * to proxy /api/* to your home pool server so the dashboard uses one domain.
 */
import { writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const origin = (process.env.POOL_API_ORIGIN || "").replace(/\/$/, "");

const rewrites = [];

if (origin) {
  rewrites.push({
    source: "/api/:path*",
    destination: `${origin}/api/:path*`,
  });
}

rewrites.push(
  { source: "/wallet/:path*", destination: "/index.html" },
  { source: "/((?!assets/)(?!api/).*)", destination: "/index.html" },
);

const vercel = { rewrites };

writeFileSync(join(root, "vercel.json"), JSON.stringify(vercel, null, 2) + "\n");
console.log(
  origin
    ? `vercel.json: proxy /api -> ${origin}`
    : "vercel.json: SPA only (set POOL_API_ORIGIN or VITE_POOL_API_URL)",
);