import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/__event-horizon/assets/:asset',
        destination: '/api/event-horizon/assets/:asset',
      },
    ];
  },
};

export default nextConfig;
