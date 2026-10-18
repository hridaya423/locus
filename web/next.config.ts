import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: false,
  devIndicators: false,
  // EXTRA_DEV_ORIGINS adds hosts (comma-separated) allowed to load the dev server, e.g. a workstation IP opened from another machine.
  allowedDevOrigins: ["*.ngrok-free.app", "*.ngrok-free.dev", "*.ngrok.app", "*.ngrok.dev", "*.ngrok.io", ...(process.env.EXTRA_DEV_ORIGINS?.split(",").filter(Boolean) ?? [])],
  // OMICS_API_URL points /api at the backend; set it when the API runs on a port other than 8000 (see OMICS_API_PORT).
  rewrites: async () => [{ source: "/api/:path*", destination: `${process.env.OMICS_API_URL ?? "http://localhost:8000"}/:path*` }],
  // The proxy behind /api gives up after 30 s by default: a cold GEO record took 28 s, a cold search 21–30 s, and the
  // first read of a large series' methods up to three minutes. A 500 from the proxy looked like a locus failure.
  experimental: { proxyTimeout: 300_000 },

  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
