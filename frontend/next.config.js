/** @type {import('next').NextConfig} */
const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${ORCHESTRATOR_URL}/api/v1/:path*` },
    ];
  },
};

module.exports = nextConfig;
