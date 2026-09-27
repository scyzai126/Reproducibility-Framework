import type { NextConfig } from 'next';

const backendOrigin = process.env.NEXT_PUBLIC_BACKEND_ORIGIN || 'http://localhost:8000';

const nextConfig: NextConfig = {
  devIndicators: false,
  experimental: {
    proxyTimeout: 900_000, // 15 minutes — a v8 paper run (13 LLM calls) plus grouping
  },
  async rewrites() {
    return [
      {
        source: '/backend/:path*',
        destination: `${backendOrigin}/:path*`,
      },
    ];
  },
};

export default nextConfig;
