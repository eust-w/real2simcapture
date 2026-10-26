import {
  Activity,
  Box,
  CheckCircle2,
  Download,
  FileArchive,
  FolderPlus,
  GitMerge,
  Layers3,
  ListPlus,
  Play,
  Radio,
  RefreshCw,
  Save,
  Scissors,
  Trash2,
  Upload,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { MeshPreview } from "./components/MeshPreview";
import {
  ApiClient,
  Artifact,
  buildApiBase,
  groupArtifactsByFolder,
  LiveSessionPayload,
  Project,
  resolveArtifactUrl,
  SceneObject,
  TaskPayload,
  type HealthPayload,
} from "./lib/api";
import "./styles.css";

const apiBase = buildApiBase(window.location.href, import.meta.env.VITE_API_BASE_URL);
const api = new ApiClient(apiBase);

type PreviewTab = "live" | "visual" | "collision" | "scene";

function App() {
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<TaskPayload[]>([]);
  const [liveSessions, setLiveSessions] = useState<LiveSessionPayload[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [selectedLiveSessionId, setSelectedLiveSessionId] = useState<string>("");
  const [previewTab, setPreviewTab] = useState<PreviewTab>("live");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const selectedTask = useMemo(() => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0] ?? null, [tasks, selectedTaskId]);
  const selectedLiveSession = useMemo(
    () => liveSessions.find((session) => session.id === selectedLiveSessionId) ?? liveSessions[0] ?? null,
    [liveSessions, selectedLiveSessionId],
  );

  const refresh = useCallback(async () => {
    setError(null);
    const [healthPayload, projectPayload, taskPayload, livePayload] = await Promise.all([
      api.health(),
      api.projects(),
      api.tasks(selectedProjectId || undefined),
      api.liveSessions(selectedProjectId || undefined),
    ]);
    setHealth(healthPayload);
    setProjects(projectPayload);
    setTasks(taskPayload);
    setLiveSessions(livePayload);
    if (!selectedProjectId && projectPayload[0]) {
      setSelectedProjectId(projectPayload[0].id);
    }
    if (!selectedTaskId && taskPayload[0]) {
      setSelectedTaskId(taskPayload[0].id);
    }
    if (!selectedLiveSessionId && livePayload[0]) {
      setSelectedLiveSessionId(livePayload[0].id);
    }
  }, [selectedProjectId, selectedTaskId, selectedLiveSessionId]);

  useEffect(() => {
    refresh().catch((err: Error) => setError(err.message));
  }, [refresh]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      api.liveSessions(selectedProjectId || undefined)
        .then((payload) => {
          setLiveSessions(payload);
          if (!selectedLiveSessionId && payload[0]) {
            setSelectedLiveSessionId(payload[0].id);
          }
        })
        .catch((err: Error) => setError(err.message));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedProjectId, selectedLiveSessionId]);

  async function handleCreateProject(name: string) {
    setBusy(true);
    try {
      const project = await api.createProject(name);
      setSelectedProjectId(project.id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload(input: UploadInput) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(input);
      setSelectedTaskId(task.id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunTask(taskId: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.runTask(taskId);
      setTasks((current) => upsertTask(current, task));
      setSelectedTaskId(task.id);
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handleEnqueueTask(taskId: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.enqueueTask(taskId);
      setTasks((current) => upsertTask(current, task));
      setSelectedTaskId(task.id);
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifySimulation(taskId: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.verifySimulation(taskId);
      setTasks((current) => upsertTask(current, task));
      setSelectedTaskId(task.id);
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handleResegmentScene(taskId: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.resegmentScene(taskId);
      setTasks((current) => upsertTask(current, task));
      setSelectedTaskId(task.id);
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function handlePatchObject(taskId: string, objectId: string, patch: Partial<SceneObject>) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.patchSceneObject(taskId, objectId, patch);
      setTasks((current) => upsertTask(current, task));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteObject(taskId: string, objectId: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.deleteSceneObject(taskId, objectId);
      setTasks((current) => upsertTask(current, task));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSplitObject(taskId: string, objectId: string, axis: "x" | "y" | "z") {
    setBusy(true);
    setError(null);
    try {
      const task = await api.splitSceneObject(taskId, objectId, { axis });
      setTasks((current) => upsertTask(current, task));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleMergeObjects(taskId: string, objectIds: string[], name: string, category: string) {
    setBusy(true);
    setError(null);
    try {
      const task = await api.mergeSceneObjects(taskId, { object_ids: objectIds, name, category });
      setTasks((current) => upsertTask(current, task));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleExportObject(taskId: string, objectId: string) {
    window.open(api.sceneObjectExportUrl(taskId, objectId), "_blank", "noopener,noreferrer");
  }

  async function handleFinalizeLiveSession(sessionId: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.finalizeLiveSession(sessionId);
      setLiveSessions((current) => upsertLiveSession(current, result.session));
      setTasks((current) => upsertTask(current, result.task));
      setSelectedTaskId(result.task.id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const previewArtifact = pickPreviewArtifact(selectedTask, previewTab);
  const previewUrl = resolveArtifactUrl(apiBase, previewArtifact);

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Layers3 size={18} /></div>
          <div>
            <strong>iPhone Real2Sim</strong>
            <span>Capture Console</span>
          </div>
        </div>

        <ProjectCreator onCreate={handleCreateProject} disabled={busy} />
        <section className="rail-section">
          <div className="rail-title">Projects</div>
          <div className="project-list">
            {projects.map((project) => (
              <button
                className={project.id === selectedProjectId ? "row-button selected" : "row-button"}
                key={project.id}
                onClick={() => {
                  setSelectedProjectId(project.id);
                  Promise.all([api.tasks(project.id), api.liveSessions(project.id)]).then(([taskPayload, livePayload]) => {
                    setTasks(taskPayload);
                    setSelectedTaskId(taskPayload[0]?.id ?? "");
                    setLiveSessions(livePayload);
                    setSelectedLiveSessionId(livePayload[0]?.id ?? "");
                  }).catch((err: Error) => setError(err.message));
                }}
              >
                <span>{project.name}</span>
              </button>
            ))}
            {projects.length === 0 && <div className="empty-text">No project yet.</div>}
          </div>
        </section>

        <section className="rail-section grow">
          <div className="rail-title">Tasks</div>
          <div className="task-list">
            {tasks.map((task) => (
              <button
                key={task.id}
                className={task.id === selectedTask?.id ? "task-row selected" : "task-row"}
                onClick={() => setSelectedTaskId(task.id)}
              >
                <StatusIcon status={task.status} />
                <span>
                  <strong>{task.name}</strong>
                  <small>{task.category} / {task.mode}</small>
                </span>
              </button>
            ))}
            {tasks.length === 0 && <div className="empty-text">No capture task.</div>}
          </div>
        </section>

        <section className="rail-section">
          <div className="rail-title">Live Sessions</div>
          <div className="task-list compact">
            {liveSessions.map((session) => (
              <button
                key={session.id}
                className={session.id === selectedLiveSession?.id ? "task-row selected" : "task-row"}
                onClick={() => setSelectedLiveSessionId(session.id)}
              >
                <Radio size={16} className={session.status === "recording" ? "ok" : "pending"} />
                <span>
                  <strong>{session.name}</strong>
                  <small>{session.frame_count} frames / {session.status}</small>
                </span>
              </button>
            ))}
            {liveSessions.length === 0 && <div className="empty-text">No live session.</div>}
          </div>
        </section>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>Real Capture To Simulation Package</h1>
            <p>{apiBase}</p>
          </div>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => refresh().catch((err: Error) => setError(err.message))} title="Refresh">
              <RefreshCw size={17} />
            </button>
            {selectedTask && (
              <>
                <button
                  className="secondary-button"
                  onClick={() => handleEnqueueTask(selectedTask.id)}
                  disabled={busy || !["queued", "failed"].includes(selectedTask.status)}
                >
                  <ListPlus size={16} />
                  Enqueue
                </button>
                <button className="primary-button" onClick={() => handleRunTask(selectedTask.id)} disabled={busy || selectedTask.status === "running"}>
                  <Play size={16} />
                  Run real pipeline
                </button>
              </>
            )}
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <div className="main-grid">
          <section className="left-pane">
            <LiveSessionPanel session={selectedLiveSession} onFinalize={handleFinalizeLiveSession} disabled={busy} />
            <UploadPanel projects={projects} selectedProjectId={selectedProjectId} onUpload={handleUpload} disabled={busy || projects.length === 0} />
            <DependencyPanel health={health} />
          </section>

          <section className="preview-pane">
            <div className="preview-toolbar">
              <div className="segmented">
                {(["live", "visual", "collision", "scene"] as PreviewTab[]).map((tab) => (
                  <button key={tab} className={previewTab === tab ? "active" : ""} onClick={() => setPreviewTab(tab)}>
                    {tab === "live" ? "Live Mesh" : tab === "visual" ? "Visual Asset" : tab === "collision" ? "Collision Asset" : "Motrix Scene"}
                  </button>
                ))}
              </div>
              <span className="artifact-path">{previewTab === "live" ? `Mesh v${selectedLiveSession?.mesh_version ?? 0}` : previewArtifact?.path ?? "No artifact"}</span>
            </div>
            <MeshPreview
              url={previewTab === "live" ? (selectedLiveSession?.mesh_url ? `${apiBase}${selectedLiveSession.mesh_url}` : null) : previewUrl}
              label={`${previewTab} preview`}
              live={previewTab === "live"}
            />
          </section>

          <aside className="right-pane">
            <TaskInspector
              task={selectedTask}
              apiBase={apiBase}
              onVerifySimulation={handleVerifySimulation}
              onResegmentScene={handleResegmentScene}
              onPatchObject={handlePatchObject}
              onDeleteObject={handleDeleteObject}
              onSplitObject={handleSplitObject}
              onMergeObjects={handleMergeObjects}
              onExportObject={handleExportObject}
              disabled={busy}
            />
          </aside>
        </div>
      </section>
    </main>
  );
}

interface UploadInput {
  projectId: string;
  name: string;
  mode: "asset" | "scene";
  category: string;
  materialCategory?: string;
  massKg?: string;
  friction?: string;
  file: File;
}

function ProjectCreator({ onCreate, disabled }: { onCreate: (name: string) => void; disabled: boolean }) {
  const [name, setName] = useState("");
  return (
    <form
      className="project-creator"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) {
          onCreate(name.trim());
          setName("");
        }
      }}
    >
      <input value={name} onChange={(event) => setName(event.target.value)} placeholder="New project" disabled={disabled} />
      <button className="icon-button" disabled={disabled || !name.trim()} title="Create project">
        <FolderPlus size={16} />
      </button>
    </form>
  );
}

function UploadPanel({
  projects,
  selectedProjectId,
  onUpload,
  disabled,
}: {
  projects: Project[];
  selectedProjectId: string;
  onUpload: (input: UploadInput) => void;
  disabled: boolean;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"asset" | "scene">("asset");
  const [category, setCategory] = useState("object");
  const [materialCategory, setMaterialCategory] = useState("");
  const [massKg, setMassKg] = useState("");
  const [friction, setFriction] = useState("");
  const [file, setFile] = useState<File | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !selectedProjectId || !name.trim()) {
      return;
    }
    onUpload({
      projectId: selectedProjectId,
      name: name.trim(),
      mode,
      category: category.trim(),
      materialCategory: materialCategory.trim(),
      massKg,
      friction,
      file,
    });
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <Upload size={17} />
        <h2>Capture Upload</h2>
      </div>
      <form className="stack-form" onSubmit={submit}>
        <label>
          Task name
          <input value={name} onChange={(event) => setName(event.target.value)} disabled={disabled} />
        </label>
        <label>
          Project
          <select value={selectedProjectId} disabled={disabled}>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        <div className="two-col">
          <label>
            Mode
            <select value={mode} onChange={(event) => setMode(event.target.value as "asset" | "scene")} disabled={disabled}>
              <option value="asset">Asset</option>
              <option value="scene">Scene</option>
            </select>
          </label>
          <label>
            Category
            <input value={category} onChange={(event) => setCategory(event.target.value)} disabled={disabled} />
          </label>
        </div>
        <label>
          Material category
          <input value={materialCategory} onChange={(event) => setMaterialCategory(event.target.value)} placeholder="optional measured or annotated material" disabled={disabled} />
        </label>
        <div className="two-col">
          <label>
            Mass kg
            <input value={massKg} onChange={(event) => setMassKg(event.target.value)} inputMode="decimal" disabled={disabled} />
          </label>
          <label>
            Friction
            <input value={friction} onChange={(event) => setFriction(event.target.value)} inputMode="decimal" disabled={disabled} />
          </label>
        </div>
        <label>
          Capture package
          <input
            type="file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            accept=".obj,.glb,.gltf,.ply,.stl,.zip,.json,.mp4,.mov,.m4v"
            disabled={disabled}
          />
        </label>
        <button className="primary-button" disabled={disabled || !file || !name.trim()}>
          <Upload size={16} />
          Upload
        </button>
      </form>
    </section>
  );
}

function LiveSessionPanel({
  session,
  onFinalize,
  disabled,
}: {
  session: LiveSessionPayload | null;
  onFinalize: (sessionId: string) => void;
  disabled: boolean;
}) {
  const liveObject = session?.scene.objects[0] ?? null;
  return (
    <section className="panel">
      <div className="panel-heading">
        <Radio size={17} />
        <h2>Live Scene</h2>
      </div>
      {!session ? (
        <div className="empty-text">Start Live in the iPhone RGB-D view.</div>
      ) : (
        <div className="live-session">
          <dl className="metrics">
            <div><dt>Status</dt><dd>{session.status}</dd></div>
            <div><dt>Frames</dt><dd>{session.frame_count} total / {session.depth_frame_count} depth</dd></div>
            <div><dt>Latest</dt><dd>{session.latest_frame_id ?? "None"}</dd></div>
            <div><dt>Source</dt><dd>{session.scene.source_kind ?? "live"}</dd></div>
            <div><dt>Task</dt><dd>{session.task_id ?? "Not finalized"}</dd></div>
          </dl>
          {liveObject && (
            <div className="live-object">
              <div className="section-title">Current Geometry</div>
              <strong>{liveObject.name}</strong>
              <span>{liveObject.category}</span>
              <small>
                {liveObject.dimensions?.map((value) => `${value.toFixed(2)}m`).join(" x ") ?? "No dimensions"}
              </small>
            </div>
          )}
          {!liveObject && <div className="empty-text">Waiting for RGB-D frames.</div>}
          <button className="secondary-button" disabled={disabled || session.status !== "recording" || session.frame_count === 0} onClick={() => onFinalize(session.id)}>
            <CheckCircle2 size={15} /> Finalize as task
          </button>
        </div>
      )}
    </section>
  );
}

function DependencyPanel({ health }: { health: HealthPayload | null }) {
  const dependencies = Object.values(health?.dependencies ?? {});
  return (
    <section className="panel">
      <div className="panel-heading">
        <Activity size={17} />
        <h2>Dependency Gate</h2>
      </div>
      <div className="dependency-list">
        {health?.database && (
          <div className="dependency-row">
            {health.database.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>database:{health.database.backend}</span>
            <small>{health.database.reason ?? "available"}</small>
          </div>
        )}
        {health?.queue && (
          <div className="dependency-row">
            {health.queue.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>queue:{health.queue.backend}</span>
            <small>{health.queue.reason ?? "available"}</small>
          </div>
        )}
        {health?.storage_backend && (
          <div className="dependency-row">
            {health.storage_backend.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>storage:{health.storage_backend.backend}</span>
            <small>{health.storage_backend.reason ?? "available"}</small>
          </div>
        )}
        {health?.reconstruction && (
          <div className="dependency-row">
            {health.reconstruction.providers[health.reconstruction.provider]?.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>recon:{health.reconstruction.provider}</span>
            <small>{health.reconstruction.providers[health.reconstruction.provider]?.reason ?? "available"}</small>
          </div>
        )}
        {health?.segmentation && (
          <div className="dependency-row">
            {health.segmentation.providers[health.segmentation.provider]?.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>seg:{health.segmentation.provider}</span>
            <small>{health.segmentation.providers[health.segmentation.provider]?.reason ?? "available"}</small>
          </div>
        )}
        {Object.entries(health?.simulators?.providers ?? {}).map(([name, provider]) => (
          <div className="dependency-row" key={`sim-${name}`}>
            {provider.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>sim:{name}</span>
            <small>{provider.reason ?? provider.executable ?? "available"}</small>
          </div>
        ))}
        {dependencies.map((dependency) => (
          <div className="dependency-row" key={dependency.name}>
            {dependency.available ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="bad" />}
            <span>{dependency.name}</span>
            <small>{dependency.path ?? "missing"}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function TaskInspector({
  task,
  apiBase,
  onVerifySimulation,
  onResegmentScene,
  onPatchObject,
  onDeleteObject,
  onSplitObject,
  onMergeObjects,
  onExportObject,
  disabled,
}: {
  task: TaskPayload | null;
  apiBase: string;
  onVerifySimulation: (taskId: string) => void;
  onResegmentScene: (taskId: string) => void;
  onPatchObject: (taskId: string, objectId: string, patch: Partial<SceneObject>) => void;
  onDeleteObject: (taskId: string, objectId: string) => void;
  onSplitObject: (taskId: string, objectId: string, axis: "x" | "y" | "z") => void;
  onMergeObjects: (taskId: string, objectIds: string[], name: string, category: string) => void;
  onExportObject: (taskId: string, objectId: string) => void;
  disabled: boolean;
}) {
  const [selectedObjectId, setSelectedObjectId] = useState("");
  const objects = task?.scene?.objects ?? [];
  const object = objects.find((candidate) => candidate.id === selectedObjectId) ?? objects[0] ?? null;
  useEffect(() => {
    if (objects.length > 0 && !objects.some((candidate) => candidate.id === selectedObjectId)) {
      setSelectedObjectId(objects[0].id);
    }
  }, [objects, selectedObjectId]);
  return (
    <section className="inspector">
      <div className="panel-heading">
        <Box size={17} />
        <h2>Task Inspector</h2>
      </div>
      {!task ? (
        <div className="empty-text">Select or upload a task.</div>
      ) : (
        <>
          <dl className="metrics">
            <div><dt>Status</dt><dd><StatusPill status={task.status} /></dd></div>
            <div><dt>Input</dt><dd>{task.original_filename}</dd></div>
            <div><dt>Failure</dt><dd>{task.failure_reason ?? "None"}</dd></div>
            <div><dt>Artifacts</dt><dd>{task.artifacts.length}</dd></div>
          </dl>
          <CaptureQualityPanel report={task.report} />
          <MeshQualityPanel report={task.report} />
          <PackageValidationPanel report={task.report} />
          <button className="secondary-button" disabled={disabled || task.status !== "completed"} onClick={() => onVerifySimulation(task.id)}>
            <ShieldCheck size={15} /> Verify simulation package
          </button>
          {object && (
            <>
              <ObjectSelector objects={objects} selectedObjectId={object.id} onSelect={setSelectedObjectId} disabled={disabled} />
              <ObjectEditor taskId={task.id} object={object} onPatch={onPatchObject} disabled={disabled} />
              <SegmentationActions
                taskId={task.id}
                objects={objects}
                selectedObject={object}
                canResegment={task.mode === "scene" && task.status === "completed"}
                onResegment={onResegmentScene}
                onDelete={onDeleteObject}
                onSplit={onSplitObject}
                onMerge={onMergeObjects}
                onExport={onExportObject}
                disabled={disabled}
              />
            </>
          )}
          <ArtifactTree artifacts={task.artifacts} apiBase={apiBase} />
          <LogPanel logs={task.logs} />
        </>
      )}
    </section>
  );
}

interface CaptureQuality {
  valid: boolean;
  issues: string[];
  frame_count: number;
  usable_frame_count: number;
  blurry_frame_count: number;
  underexposed_frame_count: number;
  overexposed_frame_count: number;
  has_scale_reference: boolean;
  coverage_angle_degrees: number | null;
  tracking_lost_events: number;
}

function CaptureQualityPanel({ report }: { report: Record<string, unknown> | null }) {
  const quality = getCaptureQuality(report);
  if (!quality) {
    return null;
  }
  return (
    <div className="quality-panel">
      <div className="section-title">Capture Quality</div>
      <dl className="metrics">
        <div><dt>Status</dt><dd>{quality.valid ? "pass" : "needs recapture"}</dd></div>
        <div><dt>Frames</dt><dd>{quality.usable_frame_count}/{quality.frame_count} usable</dd></div>
        <div><dt>Blur</dt><dd>{quality.blurry_frame_count}</dd></div>
        <div><dt>Exposure</dt><dd>{quality.underexposed_frame_count + quality.overexposed_frame_count}</dd></div>
        <div><dt>Scale</dt><dd>{quality.has_scale_reference ? "present" : "missing"}</dd></div>
        <div><dt>Tracking</dt><dd>{quality.tracking_lost_events}</dd></div>
        <div><dt>Coverage</dt><dd>{quality.coverage_angle_degrees == null ? "unknown" : `${quality.coverage_angle_degrees.toFixed(0)}°`}</dd></div>
        <div><dt>Issues</dt><dd>{quality.issues.length ? quality.issues.join(", ") : "None"}</dd></div>
      </dl>
    </div>
  );
}

function getCaptureQuality(report: Record<string, unknown> | null): CaptureQuality | null {
  const quality = report?.capture_quality;
  if (!quality || typeof quality !== "object") {
    return null;
  }
  const value = quality as Record<string, unknown>;
  if (typeof value.valid !== "boolean" || typeof value.frame_count !== "number" || typeof value.usable_frame_count !== "number") {
    return null;
  }
  return {
    valid: value.valid,
    issues: Array.isArray(value.issues) ? value.issues.map(String) : [],
    frame_count: value.frame_count,
    usable_frame_count: value.usable_frame_count,
    blurry_frame_count: Number(value.blurry_frame_count ?? 0),
    underexposed_frame_count: Number(value.underexposed_frame_count ?? 0),
    overexposed_frame_count: Number(value.overexposed_frame_count ?? 0),
    has_scale_reference: Boolean(value.has_scale_reference),
    coverage_angle_degrees: typeof value.coverage_angle_degrees === "number" ? value.coverage_angle_degrees : null,
    tracking_lost_events: Number(value.tracking_lost_events ?? 0),
  };
}

interface PackageValidation {
  valid: boolean;
  artifact_completeness?: { valid?: boolean; artifact_count?: number; asset_file_count?: number };
  manifest?: { valid?: boolean; asset_count?: number };
  mjcf?: { mujoco_load_valid?: boolean; step_valid?: boolean; contact_count?: number };
  urdf?: { valid?: boolean; link_count?: number };
  usd?: { valid?: boolean; mesh_count?: number };
  usdz?: { valid?: boolean; entry_count?: number };
  contact_relationships?: { valid?: boolean; support_relation_count?: number; unsupported_objects?: string[]; skipped?: boolean };
  zip?: { valid?: boolean; entry_count?: number };
  native_simulators?: {
    valid?: boolean;
    configured_count?: number;
    motrixsim?: NativeSimulatorValidation;
    isaacsim?: NativeSimulatorValidation;
    genesis?: NativeSimulatorValidation;
  };
}

interface NativeSimulatorValidation {
  valid?: boolean;
  command_configured?: boolean;
  attempted?: boolean;
  reason?: string | null;
}

interface MeshQuality {
  visual_faces: number;
  collision_faces: number;
  collision_part_count: number;
  collision_backend: string;
  material_category: string;
  material_category_source: string;
  watertight: boolean;
  textures_present: boolean;
  removed_component_count: number;
  removed_face_count: number;
}

function MeshQualityPanel({ report }: { report: Record<string, unknown> | null }) {
  const quality = getMeshQuality(report);
  if (!quality) {
    return null;
  }
  return (
    <div className="quality-panel">
      <div className="section-title">Mesh Quality</div>
      <dl className="metrics">
        <div><dt>Visual</dt><dd>{quality.visual_faces} faces</dd></div>
        <div><dt>Collision</dt><dd>{quality.collision_faces} faces</dd></div>
        <div><dt>Parts</dt><dd>{quality.collision_part_count} / {quality.collision_backend}</dd></div>
        <div><dt>Material</dt><dd>{quality.material_category} / {quality.material_category_source}</dd></div>
        <div><dt>Watertight</dt><dd>{quality.watertight ? "yes" : "no"}</dd></div>
        <div><dt>Textures</dt><dd>{quality.textures_present ? "present" : "missing"}</dd></div>
        <div><dt>Cleanup</dt><dd>{quality.removed_component_count} components / {quality.removed_face_count} faces</dd></div>
      </dl>
    </div>
  );
}

function getMeshQuality(report: Record<string, unknown> | null): MeshQuality | null {
  const mesh = report?.mesh;
  if (!mesh || typeof mesh !== "object") {
    return null;
  }
  const meshValue = mesh as Record<string, unknown>;
  if (typeof meshValue.visual_faces !== "number" || typeof meshValue.collision_faces !== "number") {
    return null;
  }
  const cleanup = typeof report?.mesh_cleanup === "object" && report.mesh_cleanup !== null ? report.mesh_cleanup as Record<string, unknown> : {};
  const quality = typeof report?.quality === "object" && report.quality !== null ? report.quality as Record<string, unknown> : {};
  const physics = typeof report?.physics === "object" && report.physics !== null ? report.physics as Record<string, unknown> : {};
  return {
    visual_faces: meshValue.visual_faces,
    collision_faces: meshValue.collision_faces,
    collision_part_count: Number(meshValue.collision_part_count ?? 1),
    collision_backend: String(meshValue.collision_backend ?? "unknown"),
    material_category: String(physics.material_category ?? "unknown"),
    material_category_source: String(physics.material_category_source ?? "not_provided"),
    watertight: Boolean(meshValue.watertight),
    textures_present: Boolean(quality.textures_present),
    removed_component_count: Number(cleanup.removed_component_count ?? 0),
    removed_face_count: Number(cleanup.removed_face_count ?? 0),
  };
}

function PackageValidationPanel({ report }: { report: Record<string, unknown> | null }) {
  const validation = getPackageValidation(report);
  if (!validation) {
    return null;
  }
  return (
    <div className="quality-panel">
      <div className="section-title">Package Validation</div>
      <dl className="metrics">
        <div><dt>Status</dt><dd>{validation.valid ? "pass" : "failed"}</dd></div>
        <div><dt>Artifacts</dt><dd>{statusText(validation.artifact_completeness?.valid)} / {validation.artifact_completeness?.artifact_count ?? 0}</dd></div>
        <div><dt>Manifest</dt><dd>{statusText(validation.manifest?.valid)} / {validation.manifest?.asset_count ?? 0} assets</dd></div>
        <div><dt>MJCF</dt><dd>{statusText(Boolean(validation.mjcf?.mujoco_load_valid && validation.mjcf?.step_valid))}</dd></div>
        <div><dt>URDF</dt><dd>{statusText(validation.urdf?.valid)} / {validation.urdf?.link_count ?? 0} links</dd></div>
        <div><dt>USD</dt><dd>{statusText(validation.usd?.valid)} / {validation.usd?.mesh_count ?? 0} meshes</dd></div>
        <div><dt>USDZ</dt><dd>{statusText(validation.usdz?.valid)} / {validation.usdz?.entry_count ?? 0} files</dd></div>
        <div><dt>Contacts</dt><dd>{contactSummary(validation.contact_relationships)}</dd></div>
        <div><dt>Zip</dt><dd>{statusText(validation.zip?.valid)} / {validation.zip?.entry_count ?? 0} files</dd></div>
        <div><dt>Native</dt><dd>{nativeSimulatorSummary(validation.native_simulators)}</dd></div>
      </dl>
    </div>
  );
}

function getPackageValidation(report: Record<string, unknown> | null): PackageValidation | null {
  const validation = report?.package_validation;
  if (!validation || typeof validation !== "object") {
    return null;
  }
  const value = validation as PackageValidation;
  return typeof value.valid === "boolean" ? value : null;
}

function statusText(value: unknown): string {
  return value ? "pass" : "fail";
}

function nativeSimulatorSummary(native?: PackageValidation["native_simulators"]): string {
  if (!native) {
    return "not verified";
  }
  const configured = native.configured_count ?? 0;
  if (configured === 0) {
    return "0 configured";
  }
  const passed = ["motrixsim", "isaacsim", "genesis"].filter((name) => {
    const key = name as keyof Pick<NonNullable<PackageValidation["native_simulators"]>, "motrixsim" | "isaacsim" | "genesis">;
    return native[key]?.valid;
  }).length;
  return `${passed}/${configured} pass`;
}

function contactSummary(contact?: PackageValidation["contact_relationships"]): string {
  if (!contact) {
    return "not verified";
  }
  if (contact.skipped) {
    return "skipped";
  }
  const unsupported = contact.unsupported_objects?.length ?? 0;
  if (!contact.valid) {
    return `fail / ${unsupported} unsupported`;
  }
  return `pass / ${contact.support_relation_count ?? 0} supports`;
}

function ObjectSelector({
  objects,
  selectedObjectId,
  onSelect,
  disabled,
}: {
  objects: SceneObject[];
  selectedObjectId: string;
  onSelect: (objectId: string) => void;
  disabled: boolean;
}) {
  return (
    <label>
      Object
      <select value={selectedObjectId} onChange={(event) => onSelect(event.target.value)} disabled={disabled}>
        {objects.map((object) => (
          <option key={object.id} value={object.id}>{object.name} / {object.category}</option>
        ))}
      </select>
    </label>
  );
}

function ObjectEditor({
  taskId,
  object,
  onPatch,
  disabled,
}: {
  taskId: string;
  object: SceneObject;
  onPatch: (taskId: string, objectId: string, patch: Partial<SceneObject>) => void;
  disabled: boolean;
}) {
  const [name, setName] = useState(object.name);
  const [category, setCategory] = useState(object.category);
  const [materialCategory, setMaterialCategory] = useState(object.material_category ?? "");
  const [massKg, setMassKg] = useState(String(object.mass_kg));
  const [friction, setFriction] = useState(String(object.friction));

  useEffect(() => {
    setName(object.name);
    setCategory(object.category);
    setMaterialCategory(object.material_category ?? "");
    setMassKg(String(object.mass_kg));
    setFriction(String(object.friction));
  }, [object]);

  return (
    <form
      className="object-editor"
      onSubmit={(event) => {
        event.preventDefault();
        onPatch(taskId, object.id, {
          name,
          category,
          material_category: materialCategory,
          mass_kg: Number(massKg),
          friction: Number(friction),
        });
      }}
    >
      <div className="section-title">QA Edit</div>
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} disabled={disabled} /></label>
      <label>Category<input value={category} onChange={(event) => setCategory(event.target.value)} disabled={disabled} /></label>
      <label>Material category<input value={materialCategory} onChange={(event) => setMaterialCategory(event.target.value)} disabled={disabled} /></label>
      <div className="two-col">
        <label>Mass<input value={massKg} onChange={(event) => setMassKg(event.target.value)} disabled={disabled} /></label>
        <label>Friction<input value={friction} onChange={(event) => setFriction(event.target.value)} disabled={disabled} /></label>
      </div>
      <button className="secondary-button" disabled={disabled}><Save size={15} /> Save QA edit</button>
    </form>
  );
}

function SegmentationActions({
  taskId,
  objects,
  selectedObject,
  canResegment,
  onResegment,
  onDelete,
  onSplit,
  onMerge,
  onExport,
  disabled,
}: {
  taskId: string;
  objects: SceneObject[];
  selectedObject: SceneObject;
  canResegment: boolean;
  onResegment: (taskId: string) => void;
  onDelete: (taskId: string, objectId: string) => void;
  onSplit: (taskId: string, objectId: string, axis: "x" | "y" | "z") => void;
  onMerge: (taskId: string, objectIds: string[], name: string, category: string) => void;
  onExport: (taskId: string, objectId: string) => void;
  disabled: boolean;
}) {
  const canDelete = objects.length > 1;
  const canSplit = Boolean(selectedObject.dimensions);
  const mergeTargets = objects.slice(0, 2);
  const canMerge = mergeTargets.length === 2;
  return (
    <div className="segmentation-actions">
      <div className="section-title">Segmentation</div>
      <div className="button-row">
        <button className="secondary-button danger" disabled={disabled || !canDelete} onClick={() => onDelete(taskId, selectedObject.id)}>
          <Trash2 size={15} /> Delete
        </button>
        <button className="secondary-button" disabled={disabled || !canSplit} onClick={() => onSplit(taskId, selectedObject.id, "x")}>
          <Scissors size={15} /> Split X
        </button>
      </div>
      <button
        className="secondary-button"
        disabled={disabled || !canMerge}
        onClick={() => onMerge(taskId, mergeTargets.map((object) => object.id), `${mergeTargets[0].name} merged`, mergeTargets[0].category)}
      >
        <GitMerge size={15} /> Merge First Two
      </button>
      <button className="secondary-button" disabled={disabled || !canResegment} onClick={() => onResegment(taskId)}>
        <RefreshCw size={15} /> Re-segment
      </button>
      <button className="secondary-button" disabled={disabled} onClick={() => onExport(taskId, selectedObject.id)}>
        <Download size={15} /> Export Object
      </button>
    </div>
  );
}

function ArtifactTree({ artifacts, apiBase }: { artifacts: Artifact[]; apiBase: string }) {
  const groups = groupArtifactsByFolder(artifacts);
  return (
    <div className="artifact-tree">
      <div className="section-title">Export Package</div>
      {groups.map((group) => (
        <div className="artifact-group" key={group.folder}>
          <strong>{group.folder}</strong>
          {group.artifacts.map((artifact) => (
            <a key={artifact.path} href={resolveArtifactUrl(apiBase, artifact) ?? "#"} target="_blank" rel="noreferrer">
              <FileArchive size={14} />
              <span>{artifact.path}</span>
              <small>{formatBytes(artifact.size_bytes)}</small>
              <Download size={13} />
            </a>
          ))}
        </div>
      ))}
      {artifacts.length === 0 && <div className="empty-text">No exported files yet.</div>}
    </div>
  );
}

function LogPanel({ logs }: { logs: string[] }) {
  return (
    <div className="logs">
      <div className="section-title">Job Logs</div>
      <pre>{logs.slice(-14).join("\n")}</pre>
    </div>
  );
}

function StatusIcon({ status }: { status: TaskPayload["status"] }) {
  if (status === "completed") return <CheckCircle2 size={16} className="ok" />;
  if (status === "failed") return <XCircle size={16} className="bad" />;
  return <Activity size={16} className="pending" />;
}

function StatusPill({ status }: { status: TaskPayload["status"] }) {
  return <span className={`status-pill ${status}`}>{status}</span>;
}

function pickPreviewArtifact(task: TaskPayload | null, tab: PreviewTab): Artifact | undefined {
  if (!task?.scene) return undefined;
  const object = task.scene.objects[0];
  const target = tab === "collision" ? object.collision_mesh : object.visual_mesh;
  return task.artifacts.find((artifact) => artifact.path === target) ?? task.artifacts.find((artifact) => artifact.path.endsWith(".obj"));
}

function upsertTask(tasks: TaskPayload[], task: TaskPayload): TaskPayload[] {
  const exists = tasks.some((candidate) => candidate.id === task.id);
  return exists ? tasks.map((candidate) => (candidate.id === task.id ? task : candidate)) : [task, ...tasks];
}

function upsertLiveSession(sessions: LiveSessionPayload[], session: LiveSessionPayload): LiveSessionPayload[] {
  const exists = sessions.some((candidate) => candidate.id === session.id);
  return exists ? sessions.map((candidate) => (candidate.id === session.id ? session : candidate)) : [session, ...sessions];
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default App;
