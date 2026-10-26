import { Bounds, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useEffect, useRef, useState } from "react";
import { Box3, DoubleSide, Mesh, Object3D, PerspectiveCamera, Sphere, Vector3 } from "three";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";

interface MeshPreviewProps {
  url: string | null;
  label: string;
  live?: boolean;
}

export function MeshPreview({ url, label, live = false }: MeshPreviewProps) {
  const [webglAvailable, setWebglAvailable] = useState<boolean | null>(null);
  const [meshStatus, setMeshStatus] = useState<string | null>(null);

  useEffect(() => {
    setWebglAvailable(canCreateWebGLContext());
  }, []);

  return (
    <div className="mesh-preview" aria-label={label}>
      {!url ? (
        <div className="empty-preview">{live ? "Waiting for captured mesh." : "No mesh artifact selected."}</div>
      ) : webglAvailable === false ? (
        <PreviewFallback url={url} />
      ) : (
        <Canvas camera={{ position: [2.8, -2.2, 1.8], up: [0, 0, 1], fov: 45 }} fallback={<PreviewFallback url={url} />}>
          <color attach="background" args={["#f7f9fb"]} />
          <ambientLight intensity={0.8} />
          <directionalLight position={[3, 4, 5]} intensity={1.2} />
          <Suspense fallback={null}>
            {live ? <StreamingAsset key={url.split("?")[0]} url={url} onStatus={setMeshStatus} /> :
              <Bounds fit clip observe margin={1.25}><MeshAsset url={url} /></Bounds>}
          </Suspense>
          <Grid rotation={[Math.PI / 2, 0, 0]} args={[8, 8]} cellColor="#d4dde7" sectionColor="#8aa0b5" fadeDistance={14} fadeStrength={1.5} />
          <OrbitControls makeDefault enableDamping />
        </Canvas>
      )}
      {live && url && meshStatus && <div role="status" className="mesh-status">{meshStatus}</div>}
    </div>
  );
}

function disposeAsset(object: Object3D) {
  object.traverse((child) => {
    if (child instanceof Mesh) {
      child.geometry.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((material) => material.dispose());
    }
  });
}

function StreamingAsset({ url, onStatus }: { url: string; onStatus: (message: string | null) => void }) {
  const [object, setObject] = useState<Object3D | null>(null);
  const fittedSize = useRef("");
  const { camera, controls, size } = useThree();
  useEffect(() => {
    const abort = new AbortController();
    onStatus("Loading mesh");
    fetch(url, { signal: abort.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Mesh download failed (${response.status})`);
        return response.text();
      })
      .then((text) => {
        if (abort.signal.aborted) return;
        const next = new OBJLoader().parse(text);
        next.traverse((child) => {
          if (child instanceof Mesh) {
            const materials = Array.isArray(child.material) ? child.material : [child.material];
            materials.forEach((material) => { material.side = DoubleSide; });
          }
        });
        setObject(next);
        onStatus(null);
      })
      .catch((reason: Error) => { if (!abort.signal.aborted) onStatus(reason.message); });
    return () => abort.abort();
  }, [url, onStatus]);
  useEffect(() => {
    const sizeKey = `${size.width}:${size.height}`;
    if (!object || fittedSize.current === sizeKey || !(camera instanceof PerspectiveCamera)) return;
    if (!controls || !("target" in controls) || !(controls.target instanceof Vector3)) return;
    const sphere = new Box3().setFromObject(object).getBoundingSphere(new Sphere());
    if (!Number.isFinite(sphere.radius) || sphere.radius <= 0) return;
    // Fit once per viewport size; incoming snapshots must not reset the user's orbit.
    const halfFov = camera.fov * Math.PI / 360;
    const angle = Math.min(halfFov, Math.atan(Math.tan(halfFov) * camera.aspect));
    const distance = sphere.radius / Math.sin(angle) * 1.25;
    const direction = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(sphere.center).addScaledVector(direction, distance);
    camera.near = Math.max(distance / 1000, 0.001);
    camera.far = distance * 100;
    camera.lookAt(sphere.center);
    camera.updateProjectionMatrix();
    controls.target.copy(sphere.center);
    if ("update" in controls && typeof controls.update === "function") controls.update();
    fittedSize.current = sizeKey;
  }, [object, camera, controls, size.width, size.height]);
  useEffect(() => () => { if (object) disposeAsset(object); }, [object]);
  return object ? <primitive object={object} /> : null;
}

function canCreateWebGLContext(): boolean {
  try {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2") ?? canvas.getContext("webgl") ?? canvas.getContext("experimental-webgl");
    return Boolean(context);
  } catch {
    return false;
  }
}

function MeshAsset({ url }: { url: string }) {
  const lower = url.split("?")[0].toLowerCase();
  if (lower.endsWith(".glb") || lower.endsWith(".gltf")) {
    return <GlbAsset url={url} />;
  }
  return <ObjAsset url={url} />;
}

function GlbAsset({ url }: { url: string }) {
  const gltf = useGLTF(url);
  return <primitive object={gltf.scene} />;
}

function ObjAsset({ url }: { url: string }) {
  const object = useLoader(OBJLoader, url);
  return <primitive object={object} />;
}

function PreviewFallback({ url }: { url: string }) {
  return (
    <div className="empty-preview">
      <span>Preview unavailable.</span>
      <a href={url} target="_blank" rel="noreferrer">Open artifact</a>
    </div>
  );
}
