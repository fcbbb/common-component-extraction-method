import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { apply } from "../dist/index.js";

test("orchestrator job status reaches the Python kernel without a model call", async () => {
  const root = path.resolve(import.meta.dirname, "../../../..");
  process.env.COMPONENT_DSH_METHOD_ROOT = root;
  process.env.COMPONENT_DSH_PYTHON_BIN = path.join(root, ".venv/bin/python");
  process.env.COMPONENT_DSH_JOB_ROOT = await mkdtemp(path.join(tmpdir(), "component-jobs-"));
  const tools = [];
  apply({ tools: { register: (tool) => tools.push(tool) } });
  const status = tools.find((tool) => tool.name === "component_job_status");
  const result = await status.execute({ job_id: "missing-job" }, {});
  assert.equal(result.ok, false);
  assert.equal(result.status, "missing");
});
