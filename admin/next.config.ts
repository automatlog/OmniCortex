import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  allowedDevOrigins: ["*.proxy.runpod.net"],
  
  // Increase timeout for API requests
  experimental: {
    proxyTimeout: 180_000, // 3 minutes
  },
  
  // Rewrites for API proxy (optional - helps with CORS in production)
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NEXT_PUBLIC_API_URL 
          ? `${process.env.NEXT_PUBLIC_API_URL}/:path*`
          : 'http://localhost:8000/:path*',
      },
    ];
  },
};

export default nextConfig;
