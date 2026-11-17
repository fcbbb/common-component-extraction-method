import assert from "node:assert/strict";
import test from "node:test";

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
