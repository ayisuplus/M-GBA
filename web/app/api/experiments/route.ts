import { env } from 'cloudflare:workers';
import { jsonResponse, labRunId, parseLabExperimentRequest } from '@/lib/api';
import type { LabBundle } from '@/lib/lab';

export const runtime = 'edge';

const MAX_BODY_BYTES = 2048;
const RETENTION_SECONDS = 30 * 24 * 60 * 60;
const MAX_PER_HOUR = 5;
const requestWindows = new Map<string, { hour: number; count: number }>();

function allowClient(client: string): boolean {
  const hour = Math.floor(Date.now() / 3_600_000);
  const current = requestWindows.get(client);
  if (!current || current.hour !== hour) {
    requestWindows.set(client, { hour, count: 1 });
    return true;
  }
  if (current.count >= MAX_PER_HOUR) return false;
  current.count += 1;
  return true;
}

async function readCached(runId: string): Promise<LabBundle | null> {
  const object = await env.FILES.get(`lab-runs/${runId}.json`);
  if (!object) return null;
  const expiresAt = Number(object.customMetadata?.expires_at ?? 0);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await env.FILES.delete(`lab-runs/${runId}.json`);
    return null;
  }
  return JSON.parse(await object.text()) as LabBundle;
}

export async function POST(request: Request): Promise<Response> {
  if (!request.headers.get('content-type')?.toLowerCase().startsWith('application/json')) return jsonResponse({ error: 'content_type_must_be_json' }, 415);
  const declaredLength = Number(request.headers.get('content-length') ?? 0);
  if (declaredLength > MAX_BODY_BYTES) return jsonResponse({ error: 'request_too_large' }, 413);
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse({ error: 'request_too_large' }, 413);

  let normalized;
  try {
    normalized = parseLabExperimentRequest(JSON.parse(raw));
  } catch (error) {
    return jsonResponse({ error: error instanceof Error ? error.message : 'invalid_request' }, 400);
  }

  const runId = await labRunId(normalized);
  const cached = await readCached(runId);
  if (cached) return jsonResponse({ run_id: runId, cached: true, bundle: cached, share_url: `/runs/${runId}` });

  const client = request.headers.get('cf-connecting-ip') ?? 'anonymous';
  if (!allowClient(client)) return jsonResponse({ error: 'rate_limited', fallback_bundle_id: 'state-intervention' }, 429, { 'Retry-After': '3600' });
  if (env.LAB_LIVE_RUNS_ENABLED !== 'true' || !env.MGBA_RUNNER_BASE_URL || !env.MGBA_RUNNER_TOKEN) {
    return jsonResponse({ error: 'live_runner_disabled', fallback_bundle_id: 'state-intervention' }, 503);
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${env.MGBA_RUNNER_BASE_URL.replace(/\/$/, '')}/v1/experiments`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.MGBA_RUNNER_TOKEN}`,
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-MGBA-Client-IP': client,
      },
      body: JSON.stringify(normalized),
      signal: AbortSignal.timeout(45_000),
    });
  } catch {
    return jsonResponse({ error: 'runner_unavailable', fallback_bundle_id: 'state-intervention' }, 503);
  }

  const payload = await upstream.json().catch(() => null) as { run_id?: string; bundle?: LabBundle; error?: string } | null;
  if (!upstream.ok || !payload?.bundle || payload.run_id !== runId) {
    return jsonResponse({ error: payload?.error ?? 'invalid_runner_response', fallback_bundle_id: 'state-intervention' }, upstream.status === 429 ? 429 : 502);
  }

  const expiresAt = Date.now() + RETENTION_SECONDS * 1000;
  const serialized = JSON.stringify(payload.bundle);
  await env.FILES.put(`lab-runs/${runId}.json`, serialized, {
    httpMetadata: { contentType: 'application/json' },
    customMetadata: { expires_at: String(expiresAt) },
  });
  return jsonResponse({ run_id: runId, cached: false, bundle: payload.bundle, share_url: `/runs/${runId}` });
}
