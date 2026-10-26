# Third-Party Components

This repository contains integration code. It does not grant rights to Apple SDKs, simulator distributions, model weights, commercial services, or third-party capture datasets.

| Component | Role | Distribution boundary |
| --- | --- | --- |
| ARKit, RoomPlan, RealityKit, Xcode | Native capture and Apple reconstruction | Install from Apple under the applicable Apple agreements; SDKs are not bundled |
| React, Three.js, FastAPI, NumPy, trimesh | UI, API and geometry | See installed package license files and the dependency locks |
| MuJoCo, CoACD | Simulation validation and collision processing | See each upstream distribution's license and notices |
| COLMAP, OpenMVS, Blender | Optional external reconstruction/conversion commands | Install separately; audit the actual distribution and integration before redistribution |
| SAM2 / Grounded-SAM2 and checkpoints | Optional segmentation | Code and model-weight terms must both be checked |
| KIRI Engine | Optional paid reconstruction API | User-supplied credentials and service terms; no credential or subscription is included |
| MotrixSim, Isaac Sim, Genesis, Real2Motrix | Optional engine integrations | Install independently and verify the applicable license; adapters do not sublicense these tools |

OpenMVS identifies its license as AGPL in its [upstream copyright file](https://github.com/cdcseacave/openMVS/blob/develop/COPYRIGHT.md). Calling an executable does not by itself establish that every redistribution or deployment is compliant; review the actual packaging and use.

No public real-world capture dataset is currently bundled. A future sample needs provenance, consent where relevant, its own data license, and a reproducible processing record. Test fixtures are programmatically constructed test inputs, not recordings from an iPhone.

The project's own license selection and ownership confirmation are recorded in the release readiness document. This notice is not an exhaustive legal compatibility audit.
