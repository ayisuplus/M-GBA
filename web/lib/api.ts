import { LAB_EXECUTION_REVISION, LAB_REQUEST_SCHEMA, type LabExperimentRequest } from '@/lib/lab';

const allowedKeys = ['dose', 'exposure', 'onset', 'protocol_id', 'scenario_id', 'schema_version'] as const;

export function parseLabExperimentRequest(value: unknown): LabExperimentRequest {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('request_must_be_object');
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (keys.length !== allowedKeys.length || keys.some((key, index) => key !== allowedKeys[index])) throw new Error('unexpected_request_fields');
  if (record.schema_version !== LAB_REQUEST_SCHEMA) throw new Error('invalid_schema_version');
  if (record.scenario_id !== 'carm_high_immune_her2') throw new Error('invalid_scenario_id');
  if (record.protocol_id !== 'state_conditioned_signal_expression') throw new Error('invalid_protocol_id');
  if (![0, 0.7, 1].includes(record.dose as number)) throw new Error('invalid_dose');
  if (!['early', 'late'].includes(record.onset as string)) throw new Error('invalid_onset');
  if (!['short', 'long'].includes(record.exposure as string)) throw new Error('invalid_exposure');
  return record as unknown as LabExperimentRequest;
}

export function canonicalLabIdentity(request: LabExperimentRequest): string {
  return JSON.stringify({
    execution_revision: LAB_EXECUTION_REVISION,
    request: {
      dose: request.dose.toFixed(1),
      exposure: request.exposure,
      onset: request.onset,
      protocol_id: request.protocol_id,
      scenario_id: request.scenario_id,
      schema_version: request.schema_version,
    },
  });
}

export async function labRunId(request: LabExperimentRequest): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalLabIdentity(request)));
  const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `lab-run-${hex.slice(0, 16)}`;
}

export function jsonResponse(value: unknown, status = 200, headers?: HeadersInit): Response {
  return Response.json(value, { status, headers: { 'Cache-Control': 'no-store', ...headers } });
}
