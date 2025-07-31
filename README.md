# Websockets exposer for the spacenav driver (spacenav‑ws)

![PyPI version](https://img.shields.io/pypi/v/spacenav-ws)
![Build Status](https://github.com/rmstorm/spacenav-ws/workflows/Test/badge.svg)
![License](https://img.shields.io/github/license/rmstorm/spacenav-ws)

## About

**spacenav‑ws** is a tiny Python CLI that exposes your 3Dconnexion SpaceMouse over a secure WebSocket, so Onshape on Linux can finally consume it. Under the hood it reverse‑engineers and re-implements the 3Dconnexion and Onshape interfaces.

This lets you use [FreeSpacenav/spacenavd](https://github.com/FreeSpacenav/spacenavd) on Linux with Onshape.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) or a working repo-local `.venv`
- a running instance of [spacenavd](https://github.com/FreeSpacenav/spacenavd)
- a modern browser with a userscript manager (Tampermonkey/Greasemonkey)

## Quick Start

1. Clone the repo, sync deps, generate the local cert, then start the server:

```bash
git clone https://github.com/you/spacenav-ws.git
cd spacenav-ws
uv sync
make certs HOST=127.51.68.120
uv run spacenav-ws serve --hot-reload
```

2. Open: [https://127.51.68.120:8181](https://127.51.68.120:8181) and trust the generated self-signed cert.
   Check that there are events on that page when touching your spacemouse.

3. Install Tampermonkey and add the platform-spoof userscript from
[`additional/onshape-3d-mouse-linux.user.js`](additional/onshape-3d-mouse-linux.user.js),
then open an Onshape document.

## Controls

- mode button `0`: toggle `object` / `target-camera`
- mode button `1`: cycle `all` -> `rotation-only` -> `translation-only` -> `all`

## Common Pitfalls

- `spacenavd` should have a sensible dead-zone, but no extra gains/sensitivity scaling and no `bnact*` button actions
- `make certs` is non-destructive and refuses to overwrite an existing cert/key pair
- generated certs live under [`src/spacenav_ws/data/certs`](src/spacenav_ws/data/certs)
- the raw remap is configuration, not a public standard

To override the raw-axis remap:

```bash
uv run spacenav-ws serve --hot-reload --remap XYzUWV
```

The remap string is six characters. The first three choose model translation
`x y z`, the last three choose model rotation `u v w`, from the six raw axes
`x y z u v w`. Uppercase means positive, lowercase means negative, and each of
`x y z u v w` must appear exactly once.

To validate raw SpaceMouse input:

```bash
uv run spacenav-ws read-mouse
```

## Development

```bash
uv sync
./.venv/bin/python -m pytest -q
```

Direct [`.venv`](.venv) usage also works for serving:

```bash
make certs HOST=127.51.68.120
./.venv/bin/python -m spacenav_ws.main serve --hot-reload
```

Reference docs:

- [docs/navigation-model.md](docs/navigation-model.md): mathematical model
- [docs/onshape-observations.md](docs/onshape-observations.md): Onshape interface specification
