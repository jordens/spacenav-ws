# Onshape Interface Specification

This document is the normative reference for how `spacenav-ws` interprets and
updates the Onshape 3Dconnexion bridge.

Everything below is grounded in live inspection of the current Onshape browser
session and direct page-side experiments.

## Scope

This specification covers only the geometry and navigation interface exposed by
Onshape's page-side 3Dconnexion bridge:

- view state
- pivot state
- pan / rotate / zoom semantics
- orthographic vs perspective differences
- redraw / motion lifecycle hooks

It does not specify:

- exact raw SpaceMouse axis/sign policy
- adapter-side button policy
- WAMP protocol details beyond the properties and commands actually used here

## Exposed Read Properties

The live bridge exposes at least these read properties:

- `view.affine`
- `view.extents`
- `view.fov`
- `view.frustum`
- `view.perspective`
- `view.target`
- `model.extents`
- `pivot.position`
- `hit.lookat`
- `selection.extents`
- `views.front`

For exact SpaceMouse navigation, the required properties are:

- `view.affine`
- `view.perspective`
- `view.extents`
- `view.frustum`
- `pivot.position`

## `view.affine`

`view.affine` is exactly `camera.getFrame()`.

Its value is a flat 16-element column-major matrix:

`M = [ r  u  -f  e ]`

where:

- `r` is camera right in world coordinates
- `u` is camera up in world coordinates
- `f` is camera forward in world coordinates
- `e` is camera eye position in world coordinates

Equivalent matrix form:

- column 0 = `r`
- column 1 = `u`
- column 2 = `-f`
- column 3 = `e`

The homogeneous last row is `[0 0 0 1]`.

The adapter must:

- read `view.affine` as column-major
- treat it as the camera pose
- write the updated camera pose back in the same column-major format

## `view.perspective`

`view.perspective` is the camera-mode discriminator:

- `true`: perspective
- `false`: orthographic

This bit determines whether zoom is rigid camera motion or extent scaling.

## `view.extents`

In orthographic mode:

`view.extents = [left, bottom, -far, right, top, -near]`

Onshape uses only:

- `left`
- `right`
- `bottom`
- `top`

for orthographic zoom and pan framing.

The z entries are clip values, not zoom state.

Therefore:

- orthographic pan/rotation live in `view.affine`
- orthographic zoom lives in `view.extents`
- changing only `extents[2]` / `extents[5]` must not be used for zoom

## `view.frustum`

In perspective mode:

`view.frustum = [left, right, bottom, top, near, far]`

This is the exact near-plane frustum geometry of the active camera.

It must be used to derive perspective screen-plane pan scale at a given pivot
depth:

`span_x(d) = (right - left) d / near`

`span_y(d) = (top - bottom) d / near`

## `pivot.position`

`pivot.position` is the current Spaceball rotation/pan center.

It is produced by Onshape's own dynamic Spaceball pivot logic:

- it is not adapter policy
- it is not a fixed origin
- it is not generally equal to `view.target`

The adapter must use `pivot.position` as the primary center-of-rotation input.

`view.target` must not be treated as equivalent.

## Auto Rotation Center

Onshape's internal Spaceball pivot is dynamic.

Its internal fallback chain is:

1. bounds-based center if model bounds fit the viewport
2. depth hit under the screen center
3. depth-averaged samples without planes
4. depth-averaged samples with planes
5. center-screen ray plus bounds-depth fallback

The adapter does not reimplement this logic.
It consumes the exposed result through `pivot.position`.

## Pan Semantics

Onshape pan is screen-plane camera motion relative to the current pivot plane.

For perspective:

- pan scale depends on `view.frustum` and pivot depth
- not merely on Euclidean eye-to-pivot distance

For orthographic:

- pan scale depends on `view.extents`

Therefore the adapter must derive:

- perspective pan from frustum spans at the pivot depth
- orthographic pan from orthographic x/y extents

## Zoom Semantics

### Orthographic

Onshape's orthographic zoom law is:

`scale = 2^(-delta / 6)`

and this rescales only:

- `left`
- `right`
- `bottom`
- `top`

So orthographic zoom is 2D extent scaling, not rigid camera motion.

### Perspective

Onshape's perspective zoom law is dolly:

`dolly = distance * delta / 6`

where `distance` is the current distance to the pivot/center, subject to
Onshape's own internal minimum-distance floor.

So perspective zoom must be modeled as camera motion in `view.affine`, not as
FOV change.

## Navigation Modes

### Object Mode

Object mode is inverse camera motion about `pivot.position`.

The adapter must update the camera so that the object appears to undergo the
requested rigid transform around the pivot.

### Target-Camera Mode

Target-camera mode is direct camera motion about `pivot.position`.

The adapter must:

- rotate the camera about the pivot
- translate the camera directly in the current camera frame
- still use orthographic extent scaling for orthographic z-zoom

### Not Specified Here

Pure fly/camera-eye mode is not part of the current public mode cycle and is
not part of this interface specification.

## Redraw And Motion Lifecycle

The adapter currently relies on two non-geometric hooks:

- `motion`
- `transaction = 0`

These are not geometric state, but they are required in practice:

- `motion` controls Onshape's internal Spaceball moving lifecycle
- `transaction = 0` reliably triggers redraw after navigation updates

So a geometrically correct update is not sufficient by itself.
The adapter must also drive these lifecycle hooks.

## Verified Equivalences

Page-side experiments established the following equivalences:

- object-mode rotation matches `camera.rotateAbout(...)`
- object-mode translation matches `camera.pan(...)`
- orthographic zoom matches `OrthographicCamera.zoom(...)`
- perspective zoom matches `PerspectiveCamera.dolly(...)`

This means the remaining adapter choices are mainly:

- raw device remap/sign policy
- exact mode policy
- lifecycle / transport behavior

not the underlying Onshape camera geometry itself.
