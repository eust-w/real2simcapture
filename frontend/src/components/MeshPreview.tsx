import { Bounds, Grid, Html, OrbitControls, useBounds, useGLTF } from "@react-three/drei";
import { Canvas, useLoader } from "@react-three/fiber";
import { Suspense, useEffect, useRef, useState } from "react";
import { DoubleSide, Mesh, Object3D } from "three";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";

interface MeshPreviewProps {
  url: string | null;
  label: string;
  live?: boolean;
}

export function MeshPreview({ url, label, live = false }: MeshPreviewProps) {
  const [webglAvailable, setWebglAvailable] = useState<boolean | null>(null);

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
          <Suspense fallback={<PreviewLoading />}>
            <Bounds fit={!live} clip={!live} observe={!live} margin={1.25}>
              {live ? <StreamingAsset key={url.split("?")[0]} url={url} /> : <MeshAsset url={url} />}
            </Bounds>
          </Suspense>
          <Grid rotation={[Math.PI / 2, 0, 0]} args={[8, 8]} cellColor="#d4dde7" sectionColor="#8aa0b5" fadeDistance={14} fadeStrength={1.5} />
          <OrbitControls makeDefault enableDamping />
        </Canvas>
      )}
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

function StreamingAsset({ url }: { url: string }) {
  const [object, setObject] = useState<Object3D | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fitted = useRef(false);
  const bounds = useBounds();
  useEffect(() => {
    const abort = new AbortController();
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
        setError(null);
      })
      .catch((reason: Error) => { if (!abort.signal.aborted) setError(reason.message); });
    return () => abort.abort();
  }, [url]);
  useEffect(() => {
    if (object && !fitted.current) {
      bounds.refresh(object).clip().fit();
      fitted.current = true;
    }
  }, [object, bounds]);
  useEffect(() => () => { if (object) disposeAsset(object); }, [object]);
  return <>
    {object && <primitive object={object} />}
    {error && <Html center><div role="alert" className="preview-loading">{error}</div></Html>}
    {!object && !error && <PreviewLoading />}
  </>;
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

function PreviewLoading() {
  return (
    <Html center>
      <div className="preview-loading">Loading mesh</div>
    </Html>
  );
}

function PreviewFallback({ url }: { url: string }) {
  return (
    <div className="empty-preview">
      <span>Preview unavailable.</span>
      <a href={url} target="_blank" rel="noreferrer">Open artifact</a>
    </div>
  );
}
