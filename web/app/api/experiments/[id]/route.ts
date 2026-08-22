import { env } from 'cloudflare:workers';
import { jsonResponse } from '@/lib/api';
import type { LabBundle } from '@/lib/lab';

export const runtime = 'edge';

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await context.params;
  if (!/^lab-run-[0-9a-f]{16}$/.test(id)) return jsonResponse({ error: 'experiment_not_found' }, 404);
  const key = `lab-runs/${id}.json`;
  const object = await env.FILES.get(key);
  if (!object) return jsonResponse({ error: 'experiment_not_found' }, 404);
  const expiresAt = Number(object.customMetadata?.expires_at ?? 0);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) {
    await env.FILES.delete(key);
    return jsonResponse({ error: 'experiment_expired' }, 410);
  }
  const bundle = JSON.parse(await object.text()) as LabBundle;
  return jsonResponse({ run_id: id, expires_at: new Date(expiresAt).toISOString(), bundle });
}
