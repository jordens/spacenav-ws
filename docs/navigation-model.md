# Navigation Model

This file is the reference for SpaceMouse-to-Onshape navigation math.

`dt` comes from upstream `spacenavd` / `libspnav` motion `period`, which is computed and transported in milliseconds.

## Raw Input

`spacenavd` provides a raw 6-axis input sample

`m = [tx, ty, tz, rx, ry, rz]^T`

where translation and rotation components are device-frame input signals, not pose deltas.

The adapter applies exactly one fixed signed-permutation map over all six raw
channels:

`u = S m`

where:

- `m = [tx, ty, tz, rx, ry, rz]^T`
- `u = [u_tx, u_ty, u_tz, u_rx, u_ry, u_rz]^T`

The current implementation exposes this as a six-character remap string such as
`XYzUWV`, with:

- positions 1..3 mapping model translation `x y z`
- positions 4..6 mapping model rotation `u v w`
- uppercase meaning positive raw axis
- lowercase meaning negative raw axis

Then the current implementation applies one linear gain map:

`v_c = diag(k_pan, k_pan, k_zoom) [u_tx, u_ty, u_tz]^T`

`ω_c = k_ang [u_rx, u_ry, u_rz]^T`

The camera-frame basis is exactly Onshape's `view.affine` basis:

`(e_x, e_y, e_z) = (right, up, -forward)`

So the third model axis is the camera-frame backward axis, not the view direction itself.

Current default raw SpaceMouse cap semantics (`XYzUWV`):

- push away: `+tz`
- push left: `-tx`
- push up: `+ty`
- tilt forward: `-rx`
- tilt right: `+rz`
- twist clockwise: `-ry`

## Camera Pose

Onshape `view.affine` is the camera frame in flat column-major form

`M = [ r  u  -f  e ]`

where:

- `r` is camera right in world coordinates
- `u` is camera up in world coordinates
- `f` is camera forward in world coordinates
- `e` is camera eye position in world coordinates

Equivalently, if `R = [r u -f]`, then `R ∈ SO(3)` maps camera-frame vectors into world-frame vectors.

The current Spaceball center of rotation is exposed separately as `pivot.position`.
It is not, in general, the same as `view.target`.

For perspective cameras, Onshape `view.frustum` is

`[left, right, bottom, top, near, far]`

and gives the exact near-plane view spans.

## Object-Mode Motion

Let `c` be the current center of rotation in world coordinates.

Let the current pivot depth along the view direction be

`d = |f^T (c - e)|`.

Then the exact world-space view spans at the pivot plane are:

Perspective:

`span_x = (right - left) d / near`

`span_y = (top - bottom) d / near`

Orthographic:

`span_x = right - left`

`span_y = top - bottom`

The adapter interprets x/y device translation as pan in units of screen spans
per second, so the camera-frame translation increment is

`Δt_c = [span_x * α_x, span_y * α_y, δ_dolly]^T dt`

where `α_x, α_y` are the pan-rate channels from the raw device input.

For timestep `dt`, define the incremental rotation

`ΔR_c = Exp(dt [ω_c]x)`

in camera coordinates, and the world-space translation

`Δt = R Δt_c`.

The intended object motion is

`x' = c + ΔR_w (x - c) + Δt`

with

`ΔR_w = R ΔR_c R^T`.

Because Onshape exposes the camera instead of the object, the camera receives the inverse transform:

`R' = ΔR_w^T R = R ΔR_c^T`

`e' = c + ΔR_w^T (e - c - Δt)`

This is the exact object-mode update law used by the adapter.

## Target-Camera Motion

Target-camera mode is direct camera motion about the current target/pivot.

Using the same incremental camera-frame rotation `ΔR_c` and world translation
`Δt = R Δt_c`, with world rotation `ΔR_w = R ΔR_c R^T`, the camera update is:

`R' = ΔR_w R = R ΔR_c`

`e' = c + ΔR_w (e - c + Δt)`

So:

- rotation is about the current target/pivot
- x/y translation is camera motion in the current screen plane
- perspective z translation is forward/back camera motion
- orthographic z translation still maps to extent scaling, not rigid camera motion

## Orthographic Zoom

In orthographic mode, zoom is not rigid motion.

Onshape `view.extents` is

`[left, bottom, -far, right, top, -near]`

and `setExtents()` only uses `left`, `right`, `bottom`, and `top`.

So orthographic zoom keeps the center fixed and scales the x/y half-spans:

`cx = (left + right) / 2`

`cy = (bottom + top) / 2`

`hx = (right - left) / 2`

`hy = (top - bottom) / 2`

`hx' = s hx`

`hy' = s hy`

`left' = cx - hx'`

`right' = cx + hx'`

`bottom' = cy - hy'`

`top' = cy + hy'`

The z entries of `view.extents` are clip values, not the orthographic zoom state.

Onshape's own orthographic zoom law is

`s = 2^{-δ/6}`

where `δ` is the scalar zoom command.

Perspective zoom is dolly with

`δ_dolly = d δ / 6`

using the same pivot depth `d`.

## Sources

- `spacenavd` computes motion `period` in milliseconds and writes it into AF_UNIX event field 7.
- `libspnav` exposes that same field as `spnav_event_motion.period`.
