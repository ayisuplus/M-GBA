import { describe, expect, it } from 'vitest';
import { canonicalLabIdentity, labRunId, parseLabExperimentRequest } from '@/lib/api';
import { LAB_REQUEST_SCHEMA, type LabExperimentRequest } from '@/lib/lab';

const request: LabExperimentRequest = {
  schema_version: LAB_REQUEST_SCHEMA,
  scenario_id: 'carm_high_immune_her2',
  protocol_id: 'state_conditioned_signal_expression',
  dose: 0.7,
  onset: 'late',
  exposure: 'long',
};

describe('restricted experiment contract', () => {
  it('matches the Python deterministic run identity', async () => {
    expect(parseLabExperimentRequest(request)).toEqual(request);
    expect(canonicalLabIdentity(request)).toContain('"dose":"0.7"');
    expect(await labRunId(request)).toBe('lab-run-a2c881bf9f696cd2');
  });

  it('fails closed on unknown fields and values', () => {
    expect(() => parseLabExperimentRequest({ ...request, path: 'secrets.txt' })).toThrow('unexpected_request_fields');
    expect(() => parseLabExperimentRequest({ ...request, dose: 0.4 })).toThrow('invalid_dose');
    expect(() => parseLabExperimentRequest({ ...request, onset: 'whenever' })).toThrow('invalid_onset');
  });
});
