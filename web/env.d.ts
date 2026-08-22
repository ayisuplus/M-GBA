declare namespace Cloudflare {
  interface Env {
    FILES: R2Bucket;
    LAB_LIVE_RUNS_ENABLED?: string;
    MGBA_RUNNER_BASE_URL?: string;
    MGBA_RUNNER_TOKEN?: string;
    NEXT_PUBLIC_SITE_URL?: string;
  }
}
