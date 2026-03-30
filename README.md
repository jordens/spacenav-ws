# spacenav-ws

`spacenav-ws` exposes a local SpaceMouse to browser clients over TLS WebSocket.
The current target is Onshape on Linux via `spacenavd`.

## Requirements

- `uv` or a repo-local `.venv`
- running `spacenavd`
- a browser with a userscript manager

## Quick Start

```bash
git clone https://github.com/you/spacenav-ws.git
cd spacenav-ws
uv sync
make certs HOST=127.51.68.120
uv run spacenav-ws serve --hot-reload
```

Then:

1. Open `https://127.51.68.120:8181` and trust the generated cert.
2. Verify motion events appear when the SpaceMouse moves.
3. Install [`additional/onshape-3d-mouse-linux.user.js`](additional/onshape-3d-mouse-linux.user.js).
4. Open an Onshape document.

## Controls

- button `0`: toggle `object` / `target-camera`
- button `1`: cycle `all` -> `rotation-only` -> `translation-only` -> `all`

## CLI

Start the bridge:

```bash
uv run spacenav-ws serve --hot-reload
```

Read raw SpaceMouse packets:

```bash
uv run spacenav-ws read-mouse
```

Override the raw-axis remap:

```bash
uv run spacenav-ws serve --hot-reload --remap XYzUWV
```

`remap` is six characters:

- chars `1..3`: model translation `x y z`
- chars `4..6`: model rotation `u v w`
- uppercase: positive raw axis
- lowercase: negative raw axis
- `x y z u v w` must each appear exactly once

## Notes

- generated certs live in [`src/spacenav_ws/data/certs`](src/spacenav_ws/data/certs)
- `make certs` will not overwrite an existing cert/key pair
- keep `spacenavd` dead-zone/button handling sane; avoid extra gain scaling and `bnact*` remaps

## Development

```bash
uv sync
./.venv/bin/python -m pytest -q
```

## Reference

- [`docs/navigation-model.md`](docs/navigation-model.md): navigation math
- [`docs/onshape-observations.md`](docs/onshape-observations.md): Onshape bridge contract
