import assert from "node:assert/strict";
import test from "node:test";

import { validateJsonSchemaValue } from "@deepseek-ai/dsh-tools";

import { kernelTool, registerTools } from "../dist/index.js";

function fakeContext() {
  const registered = [];
  return {
    registered,
    tools: { register: (definition) => registered.push(definition) },
  };
}

test("kernelTool exposes the declared model-facing name and description", () => {
  const tool = kernelTool({
    name: "component_fixture",
    description: "fixture tool",
    method: "job_status",
    parameters: { job_id: { type: "string", required: true } },
  });
  assert.equal(tool.name, "component_fixture");
  assert.match(tool.description, /fixture tool/);
});

test("registerTools registers every tool without executing it", () => {
  const context = fakeContext();
  registerTools(context, [
    { name: "component_a", description: "a", method: "job_status" },
    { name: "component_b", description: "b", method: "job_status" },
  ]);
  assert.deepEqual(context.registered.map((tool) => tool.name), ["component_a", "component_b"]);
});

test("output schema accepts a running job's null exit code and a finished job's integer", () => {
  const tool = kernelTool({
    name: "component_fixture",
    description: "fixture tool",
    method: "job_status",
  });
  const schema = tool.output.schema;
  const running = {
    ok: true,
    schema: "component-method-dsh-job-v1",
    job_id: "20260101-000000-extract-deadbeef",
    method: "extract",
    status: "running",
    pid: 42,
    exit_code: null,
    stdout_tail: "",
  };
  assert.deepEqual(validateJsonSchemaValue(schema, running, "value"), []);

  const succeeded = { ...running, status: "succeeded", exit_code: 0 };
  assert.deepEqual(validateJsonSchemaValue(schema, succeeded, "value"), []);
});
