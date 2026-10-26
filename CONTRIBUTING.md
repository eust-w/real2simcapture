# Contributing

This is a developer preview. Start with a small, reproducible issue or a focused pull request.

## Development

Use Python 3.11+, Node.js 22+, and macOS or Linux for the backend. iOS builds require full Xcode and XcodeGen. Hardware capture requires a compatible physical device; an unsigned CI build is not a device test.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e backend
npm --prefix frontend ci
.venv/bin/python -m pytest backend/tests -q -m 'not external'
npm --prefix frontend test
npm --prefix frontend run build
```

## Pull Requests

Contributions to the original project code are submitted under Apache-2.0, unless explicitly agreed otherwise. Only submit code and data you have the right to contribute; retain third-party notices and identify separately licensed material.

- Describe the input, resulting behavior, and what you actually verified.
- Add regression coverage for data integrity, coordinate transforms, geometry, and API behavior.
- Generated inputs are acceptable for tests. Label them as fixtures; do not represent them as real device captures or promotional results.
- Preserve errors from unavailable external tools. Never substitute fabricated geometry, successful statuses, or credentials.
- Keep capture data and credentials out of Git. Public datasets need an explicit license and provenance.
- External models, engines, APIs, and SDKs keep their own licenses. Do not vendor their binaries or weights without checking redistribution rights.
- Include hardware and version details for device or simulator results. Default CI only tests code and compilation.

## Coordinates

Exported geometry is right-handed, metric, z-up. ARKit poses are column-major camera-to-world matrices with y-up world coordinates. RGB-D intrinsics include `camera_convention: arkit` and `world_up_axis: y`; the backend converts optical depth into ARKit camera space and then z-up world space. The native mesh exporter applies the same world-axis conversion.

## Good First Contributions

Device compatibility reports, documented real datasets, exporter regression tests, reconstruction performance measurements, and installation fixes are useful. Include reproducible evidence rather than unverified performance claims.
