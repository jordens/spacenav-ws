from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from spacenav_ws.navigation import camera_state_from_affine, camera_state_to_affine
from spacenav_ws.types import CameraState, NavigationState
from spacenav_ws.wamp import WampSession


def _center_from_extents(extents: list[float]) -> np.ndarray:
    bounds = np.asarray(extents, dtype=float)
    return (bounds[:3] + bounds[3:6]) * 0.5


@dataclass
class OnshapeBridge:
    session: WampSession
    controller_uri: str

    async def remote_write(self, *args):
        return await self.session.client_rpc(self.controller_uri, "self:update", *args)

    async def remote_read(self, *args):
        return await self.session.client_rpc(self.controller_uri, "self:read", *args)

    async def try_remote_read(self, *args):
        try:
            return await self.remote_read(*args)
        except Exception:
            return None

    async def read_navigation_state(self) -> NavigationState:
        perspective = bool(await self.remote_read("view.perspective"))
        affine = await self.remote_read("view.affine")
        extents = await self.try_remote_read("view.extents")
        frustum = await self.try_remote_read("view.frustum")
        camera = camera_state_from_affine(affine, perspective=perspective, extents=extents, frustum=frustum)
        pivot = await self.read_pivot(camera)
        return NavigationState(camera=camera, pivot=pivot)

    async def read_pivot(self, camera: CameraState) -> np.ndarray:
        value = await self.try_remote_read("pivot.position")
        if isinstance(value, list) and len(value) >= 3:
            return np.asarray(value[:3], dtype=float)

        selection_extents = await self.try_remote_read("selection.extents")
        if isinstance(selection_extents, list) and len(selection_extents) >= 6:
            return _center_from_extents(selection_extents)

        model_extents = await self.try_remote_read("model.extents")
        if isinstance(model_extents, list) and len(model_extents) >= 6:
            return _center_from_extents(model_extents)

        distance = 10.0
        if camera.extents is not None:
            distance = max(camera.extents[3] - camera.extents[0], 1.0)
        return camera.position - camera.rotation[:, 2] * distance

    async def write_navigation_state(self, state: NavigationState, previous_state: NavigationState | None = None):
        await self.remote_write("view.affine", camera_state_to_affine(state.camera))
        previous_extents = previous_state.camera.extents if previous_state is not None else None
        extents_changed = state.camera.extents is not None and (previous_extents is None or not np.allclose(state.camera.extents, previous_extents))
        if not state.camera.perspective and extents_changed:
            await self.remote_write("view.extents", state.camera.extents.tolist())
        # Onshape only requests another viewer redraw when transaction is reset to 0.
        await self.remote_write("transaction", 0)

    async def set_motion(self, active: bool):
        await self.remote_write("motion", active)

    async def reset_view(self):
        front_view = await self.try_remote_read("views.front")
        if front_view is not None:
            await self.remote_write("view.affine", front_view)
