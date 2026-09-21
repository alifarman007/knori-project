import type { NextConfig } from "next";

const apiOrigin = process.env.KNORI_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: false,
  eslint: {
    dirs: ["app", "components", "lib", "tests"],
  },
  // In dev the browser talks to Next on :3000 and Next forwards /api to the
  // FastAPI container, so the session cookie stays first-party.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
