import type { NextConfig } from 'next';

const backendOrigin = process.env.NEXT_PUBLIC_BACKEND_ORIGIN || 'http://localhost:8000';

const nextConfig: NextConfig = {
  devIndicators: false,
  experimental: {
    proxyTimeout: 300_000, // 5 minutes — LLM + PDF analysis can take a while
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
