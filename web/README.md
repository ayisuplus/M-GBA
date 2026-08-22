# M-GBA Cross-Scale Virtual Lab

Competition website and observation-only experiment workspace for M-GBA. The
site never imports the L0–L4 model implementation into the browser and does not
mutate frozen experiment artifacts.

## Local development

```powershell
npm install
npm run dev
npm test
npm run lint
npm run build
```

Precomputed data is generated from repository-root artifacts:

```powershell
.\.venv\Scripts\mgba.exe lab-export `
  --dose-playbook artifacts\demo\carm-playbook.json `
  --output-dir web\public\lab-data
```

The public directory also keeps `offline/mgba-carm-demo.html` as a self-contained
fallback. Do not replace a missing real spatial Target with a synthetic fixture.

## Runtime configuration

- `LAB_LIVE_RUNS_ENABLED=false` is the safe release default.
- `MGBA_RUNNER_BASE_URL` is the HTTPS base URL of the containerized runner.
- `MGBA_RUNNER_TOKEN` is a Worker-only secret shared with the runner service.
- `NEXT_PUBLIC_SITE_URL` is used for absolute social metadata.

When live execution is disabled or unavailable, `POST /api/experiments` returns
an error and the browser explicitly switches to a frozen precomputed bundle. It
never presents that bundle as a new online result.
