/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  /*
   * Two `next dev` processes started from the same directory both write to
   * `.next`, and they corrupt each other's build manifests — the failure shows
   * up as `__webpack_modules__[moduleId] is not a function` and a 500 on every
   * route. The demo sandbox therefore builds into its own directory, so it can
   * run on :3001 while the primary terminal keeps serving :3000 untouched.
   */
  distDir: process.env.NEXT_DIST_DIR || ".next",

  env: {
    NEXT_PUBLIC_MAGNO_API:
      process.env.NEXT_PUBLIC_MAGNO_API ?? "http://127.0.0.1:8000",
  },
};

export default nextConfig;
