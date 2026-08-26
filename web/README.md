# M-GBA Cross-Scale Virtual Lab

Competition website and observation-only experiment workspace for M-GBA. The
site never imports the L0–L4 model implementation into the browser and does not
mutate frozen experiment artifacts.

The workbench also renders the ADR-0031 collective-dynamics observer output:
a synchronized direction–intensity phase plot, frozen state transitions,
external cohort summaries, Cell archetype counts, and temporally associated L4
observations. These are reference proxies, not physical phase transitions or
clinical predictions. Bundles created before ADR-0031 remain readable.

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

A single saved formal run can be analyzed independently:

```powershell
.\.venv\Scripts\mgba.exe collective-analyze `
  --input artifacts\run.json `
  --output artifacts\collective.json
```

The public directory also keeps `offline/mgba-carm-demo.html` as a self-contained
fallback. Do not replace a missing real spatial Target with a synthetic fixture.

## Event Horizon visual

Normal landing-page visits do not load or render the black-hole component. The
versioned, same-origin Web Component is an opt-in presentation layer for an
explicit host integration or a separate trap-themed page. It does not read
experiment bundles, call the API, or participate in the L0–L4 model:

```html
<script defer src="/__event-horizon/assets/black-hole.v1.js"></script>
<event-horizon-visual
  scene="home"
  depth="0"
  intensity="0.68"
  aria-label="事件视界视觉"
></event-horizon-visual>
```

Set the host element's width, height, and border radius with ordinary CSS. The
renderer uses Shadow DOM, performs no network requests, pauses in background
tabs, draws a static frame for `prefers-reduced-motion`, and removes its
listeners when detached. Without JavaScript, the host page keeps its own
content and layout.

## CI and delivery

`.github/workflows/site-ci.yml` runs for pull requests and relevant pushes to
`main`. It installs from `package-lock.json`, runs the component/API tests and
lint, builds the Vinext production bundle, and validates the required Sites
files. A successful `main` build also publishes a 14-day, commit-addressed
`mgba-site-<sha>.tar.gz` workflow artifact containing the complete `dist/`
tree. Production publication still uses the existing Sites project and a saved
version from the same Git commit; no long-lived production credential is stored
in GitHub Actions.

## Runtime configuration

- `LAB_LIVE_RUNS_ENABLED=false` is the safe release default.
- `MGBA_RUNNER_BASE_URL` is the HTTPS base URL of the containerized runner.
- `MGBA_RUNNER_TOKEN` is a Worker-only secret shared with the runner service.
- `NEXT_PUBLIC_SITE_URL` is used for absolute social metadata.

When live execution is disabled or unavailable, `POST /api/experiments` returns
an error and the browser explicitly switches to a frozen precomputed bundle. It
never presents that bundle as a new online result.
