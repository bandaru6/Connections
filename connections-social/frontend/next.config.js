/** @type {import('next').NextConfig} */
const nextConfig = {
  // Disable strict mode to avoid double-renders in dev
  reactStrictMode: false,

  // Enable standalone output for Docker
  output: 'standalone',

  // Environment variables exposed to the browser
  env: {
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000',
  },
}

module.exports = nextConfig
