import { describe, expect, it } from "vitest";

import { ApiClient, buildApiBase, groupArtifactsByFolder } from "./api";

describe("api helpers", () => {
  it("uses the current browser host for the default API base", () => {
    const base = buildApiBase("http://127.0.0.1:5173/tasks", undefined);

    expect(base).toBe("http://127.0.0.1:8000");
  });

  it("keeps configured API base values without adding slashes", () => {
    const base = buildApiBase("http://127.0.0.1:5173", "http://localhost:9000/");

    expect(base).toBe("http://localhost:9000");
  });

  it("groups artifacts by package folder", () => {
    const grouped = groupArtifactsByFolder([
      { path: "scene.xml", size_bytes: 10, url: "/api/artifacts/t/scene.xml" },
      { path: "assets/box_visual.obj", size_bytes: 20, url: "/api/artifacts/t/assets/box_visual.obj" },
      { path: "assets/box_collision.obj", size_bytes: 15, url: "/api/artifacts/t/assets/box_collision.obj" },
    ]);

    expect(grouped).toEqual([
      {
        folder: "root",
        artifacts: [{ path: "scene.xml", size_bytes: 10, url: "/api/artifacts/t/scene.xml" }],
      },
      {
        folder: "assets",
        artifacts: [
          { path: "assets/box_visual.obj", size_bytes: 20, url: "/api/artifacts/t/assets/box_visual.obj" },
          { path: "assets/box_collision.obj", size_bytes: 15, url: "/api/artifacts/t/assets/box_collision.obj" },
        ],
      },
    ]);
  });

  it("builds encoded standalone scene object export urls", () => {
    const client = new ApiClient("http://127.0.0.1:8000");

    expect(client.sceneObjectExportUrl("task 1", "bottle/001")).toBe(
      "http://127.0.0.1:8000/api/tasks/task%201/scene/objects/bottle%2F001/export",
    );
  });
});
