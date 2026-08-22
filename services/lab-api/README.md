# M-GBA Lab API

Provider-neutral container for the competition site's allow-listed paired
CAR-M run. It exposes `GET /healthz` and authenticated
`POST /v1/experiments`; browsers call it only through the site Worker.

Required environment variables:

- `MGBA_RUNNER_TOKEN`: shared secret configured in both the site and service.
- `MGBA_PROJECT_ROOT`: defaults to `/app` in the container.
- `MGBA_LAB_PORT`: defaults to `8080`.

The service accepts only the frozen `mgba-lab-experiment-request-0.1` schema.
