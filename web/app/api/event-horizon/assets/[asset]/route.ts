import blackHoleSource from '@/lib/black-hole.v1.js?raw';

export const runtime = 'edge';

const ASSET_NAME = 'black-hole.v1.js';
const RESPONSE_HEADERS = {
  'Cache-Control': 'public, max-age=31536000, immutable',
  'Content-Type': 'application/javascript; charset=utf-8',
  'Cross-Origin-Resource-Policy': 'same-origin',
  'X-Content-Type-Options': 'nosniff',
} as const;

type RouteContext = { params: Promise<{ asset: string }> };

async function isKnownAsset(context: RouteContext): Promise<boolean> {
  const { asset } = await context.params;
  return asset === ASSET_NAME;
}

export async function GET(
  _request: Request,
  context: RouteContext,
): Promise<Response> {
  if (!(await isKnownAsset(context))) {
    return new Response('asset_not_found', {
      status: 404,
      headers: { 'Cache-Control': 'no-store' },
    });
  }
  return new Response(blackHoleSource, { headers: RESPONSE_HEADERS });
}

export async function HEAD(
  _request: Request,
  context: RouteContext,
): Promise<Response> {
  if (!(await isKnownAsset(context))) {
    return new Response(null, {
      status: 404,
      headers: { 'Cache-Control': 'no-store' },
    });
  }
  return new Response(null, { headers: RESPONSE_HEADERS });
}
