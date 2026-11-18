import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { kernelTool } from "../../method-shared/dist/index.js";
import { apply } from "../dist/index.js";

function fakeJobs() {
  const starts = [];
  return {
    starts,
    jobs: {
      start(spec) {
        starts.push(spec);
        return "method-stage-fixture";
      },
    },
  };
}

test("run_stage registers one entry and hides the per-stage tools", () => {
  const registered = [];
  apply({ tools: { register: (tool) => registered.push(tool.name) } });
  assert.deepEqual(registered, ["component_run_stage"]);
});

test("a long stage is started through ctx.jobs and returns the running sheet", async () => {
  const { starts, jobs } = fakeJobs();
  const tools = [];
  apply({ tools: { register: (tool) => tools.push(tool) }, jobs });
  const runStage = tools.find((tool) => tool.name === "component_run_stage");
  const result = await runStage.execute(
    { run_id: "run-a", task_id: "task-a", stage: "extract" },
    { agent: { id: "session-a" }, callId: "call-1", rootCallId: "call-1" },
  );
  assert.equal(result.status, "running");
  assert.equal(result.job_id, "method-stage-fixture");
  assert.deepEqual(result.summary, {});
  assert.deepEqual(result.artifacts, {});
  assert.equal(result.error_code, null);
  assert.equal(starts.length, 1);
  assert.equal(starts[0].kind, "method-stage");
  assert.match(starts[0].label, /extract/);
});

test("a cheap stage stays synchronous and reports the unified sheet", async () => {
  const root = path.resolve(import.meta.dirname, "../../../..");
  process.env.COMPONENT_DSH_METHOD_ROOT = root;
  process.env.COMPONENT_DSH_PYTHON_BIN = path.join(root, ".venv/bin/python");
  process.env.COMPONENT_DSH_JOB_ROOT = await mkdtemp(path.join(tmpdir(), "component-jobs-"));
  const tool = kernelTool({
    name: "component_fixture_status",
    description: "fixture tool",
    method: "job_status",
  });
  const result = await tool.execute({ job_id: "missing-job" }, {});
  assert.equal(result.ok, false);
  assert.equal(result.status, "failed");
  assert.equal(result.error_code, "JOB_MISSING");
  assert.deepEqual(result.summary, {});
});

test("a background producer settles the job with the JSON envelope as its result", async () => {
  const root = path.resolve(import.meta.dirname, "../../../..");
  process.env.COMPONENT_DSH_METHOD_ROOT = root;
  process.env.COMPONENT_DSH_PYTHON_BIN = path.join(root, ".venv/bin/python");
  process.env.COMPONENT_DSH_JOB_ROOT = await mkdtemp(path.join(tmpdir(), "component-jobs-"));
  const { starts, jobs } = fakeJobs();
  const tool = kernelTool({
    name: "component_fixture_job",
    description: "fixture job",
    method: "job_status",
    job: true,
  }, { jobs });
  const started = await tool.execute({ job_id: "missing-job" }, {
    agent: { id: "session-a" },
    callId: "call-1",
    rootCallId: "call-1",
  });
  assert.equal(started.status, "running");
  const chunks = [];
  const hooks = starts[0].run({
    append: (text, options) => chunks.push([text, options?.channel]),
    updateProgress: () => {},
  });
  const outcome = await hooks.done;
  assert.equal(outcome.status, "failed");
  const envelope = JSON.parse(outcome.result);
  assert.equal(envelope.status, "failed");
  assert.equal(envelope.error_code, "JOB_MISSING");
});