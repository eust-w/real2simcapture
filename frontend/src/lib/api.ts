export interface DependencyStatus {
  name: string;
  available: boolean;
  path: string | null;
  version: string | null;
}

export interface HealthPayload {
  status: string;
  storage: { data_dir: string; output_dir: string };
  dependencies: Record<string, DependencyStatus>;
  database?: { backend: string; available: boolean; reason: string | null };
  queue?: { backend: string; available: boolean; reason: string | null };
  storage_backend?: { backend: string; available: boolean; reason: string | null };
  reconstruction?: {
    provider: string;
    providers: Record<string, { available: boolean; reason: string | null; command?: string; base_url?: string }>;
  };
  segmentation?: {
    provider: string;
    providers: Record<string, { available: boolean; reason: string | null; command?: string; requires?: string[] }>;
  };
  simulators?: {
    configured_count: number;
    providers: Record<string, { available: boolean; command_configured: boolean; reason: string | null; executable: string | null }>;
  };
}

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface Artifact {
  path: string;
  size_bytes: number;
  url: string;
}

export interface SceneObject {
  id: string;
  name: string;
  category: string;
  material_category?: string;
  material_category_source?: string;
  visual_mesh: string;
  visual_glb?: string;
  collision_mesh: string;
  collision_meshes?: string[];
  texture_files?: string[];
  pose: { position: number[]; quaternion: number[] };
  scale: number[];
  dimensions?: number[];
  mass_kg: number;
  friction: number;
  inertia_diagonal: number[];
  confidence: Record<string, number>;
}

export interface ScenePayload {
  unit: string;
  up_axis: string;
  objects: SceneObject[];
}

export interface TaskPayload {
  id: string;
  project_id: string;
  name: string;
  mode: "asset" | "scene";
  category: string;
  material_category: string | null;
  status: "queued" | "running" | "completed" | "failed";
  original_filename: string;
  mass_kg: number | null;
  friction: number | null;
  failure_reason: string | null;
  logs: string[];
  report: Record<string, unknown> | null;
  scene: ScenePayload | null;
  artifacts: Artifact[];
  created_at: string;
  updated_at: string;
}

export interface LiveSessionPayload {
  id: string;
  project_id: string;
  name: string;
  category: string;
  material_category: string | null;
  status: "recording" | "finalized";
  frame_count: number;
  depth_frame_count: number;
  mesh_version: number;
  mesh_url: string | null;
  latest_frame_id: string | null;
  task_id: string | null;
  scene: ScenePayload & { source_kind?: string; metrics?: Record<string, unknown> };
  capture_root: string;
  created_at: string;
  updated_at: string;
}

export interface LiveFinalizePayload {
  session: LiveSessionPayload;
  task: TaskPayload;
}

export interface ArtifactGroup {
  folder: string;
  artifacts: Artifact[];
}

export function buildApiBase(currentHref: string, configured?: string): string {
  if (configured?.trim()) {
    return configured.trim().replace(/\/+$/, "");
  }
  const url = new URL(currentHref);
  const port = url.port === "5173" || url.port === "5174" ? "8000" : url.port;
  return `${url.protocol}//${url.hostname}${port ? `:${port}` : ""}`;
}

export function groupArtifactsByFolder(artifacts: Artifact[]): ArtifactGroup[] {
  const groups = new Map<string, Artifact[]>();
  for (const artifact of artifacts) {
    const [folder] = artifact.path.includes("/") ? artifact.path.split("/", 1) : ["root"];
    const key = artifact.path.includes("/") ? folder : "root";
    groups.set(key, [...(groups.get(key) ?? []), artifact]);
  }
  return [...groups.entries()].map(([folder, groupedArtifacts]) => ({ folder, artifacts: groupedArtifacts }));
}

export function resolveArtifactUrl(apiBase: string, artifact?: Artifact): string | null {
  if (!artifact) {
    return null;
  }
  if (/^https?:\/\//.test(artifact.url)) {
    return artifact.url;
  }
  return `${apiBase}${artifact.url.startsWith("/") ? "" : "/"}${artifact.url}`;
}

export class ApiClient {
  constructor(private readonly baseUrl: string) {}

  async health(): Promise<HealthPayload> {
    return this.request<HealthPayload>("/api/health");
  }

  async projects(): Promise<Project[]> {
    return this.request<Project[]>("/api/projects");
  }

  async createProject(name: string): Promise<Project> {
    return this.request<Project>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  }

  async tasks(projectId?: string): Promise<TaskPayload[]> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request<TaskPayload[]>(`/api/tasks${query}`);
  }

  async liveSessions(projectId?: string): Promise<LiveSessionPayload[]> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
    return this.request<LiveSessionPayload[]>(`/api/live-sessions${query}`);
  }

  async liveSession(sessionId: string): Promise<LiveSessionPayload> {
    return this.request<LiveSessionPayload>(`/api/live-sessions/${encodeURIComponent(sessionId)}`);
  }

  async finalizeLiveSession(sessionId: string): Promise<LiveFinalizePayload> {
    return this.request<LiveFinalizePayload>(`/api/live-sessions/${encodeURIComponent(sessionId)}/finalize`, { method: "POST" });
  }

  async createTask(input: {
    projectId: string;
    name: string;
    mode: "asset" | "scene";
    category: string;
    materialCategory?: string;
    massKg?: string;
    friction?: string;
    file: File;
  }): Promise<TaskPayload> {
    const form = new FormData();
    form.append("project_id", input.projectId);
    form.append("name", input.name);
    form.append("mode", input.mode);
    form.append("category", input.category);
    if (input.materialCategory) {
      form.append("material_category", input.materialCategory);
    }
    if (input.massKg) {
      form.append("mass_kg", input.massKg);
    }
    if (input.friction) {
      form.append("friction", input.friction);
    }
    form.append("capture", input.file);
    return this.request<TaskPayload>("/api/tasks", { method: "POST", body: form });
  }

  async runTask(taskId: string): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/run`, { method: "POST" });
  }

  async enqueueTask(taskId: string): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/enqueue`, { method: "POST" });
  }

  async verifySimulation(taskId: string): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/verify-simulation`, { method: "POST" });
  }

  async resegmentScene(taskId: string): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/scene/resegment`, { method: "POST" });
  }

  sceneObjectExportUrl(taskId: string, objectId: string): string {
    return `${this.baseUrl}/api/tasks/${encodeURIComponent(taskId)}/scene/objects/${encodeURIComponent(objectId)}/export`;
  }

  async patchSceneObject(
    taskId: string,
    objectId: string,
    payload: Partial<Pick<SceneObject, "name" | "category" | "material_category" | "mass_kg" | "friction">>,
  ): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/scene/objects/${objectId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async deleteSceneObject(taskId: string, objectId: string): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/scene/objects/${objectId}`, { method: "DELETE" });
  }

  async splitSceneObject(taskId: string, objectId: string, payload: { axis: "x" | "y" | "z"; left_name?: string; right_name?: string }): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/scene/objects/${objectId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async mergeSceneObjects(taskId: string, payload: { object_ids: string[]; name: string; category: string }): Promise<TaskPayload> {
    return this.request<TaskPayload>(`/api/tasks/${taskId}/scene/objects/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, init);
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : payload;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (!contentType.includes("application/json")) {
      throw new Error("Expected JSON from API. Check VITE_API_BASE_URL or the /api proxy configuration.");
    }
    return payload as T;
  }
}
