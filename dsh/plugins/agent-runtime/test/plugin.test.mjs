import assert from "node:assert/strict";
import test from "node:test";

import { apply } from "../dist/index.js";

test("agent runtime registers the worker tools", () => {
  const registered = [];
  apply({ tools: { register: (tool) => registered.push(tool) } });
  assert.deepEqual(
    registered.map((tool) => tool.name).sort(),
    [
      "component_check_patch",
      "component_check_submission",
      "component_submit",
      "component_validate_artifact",
      "component_validate_draft",
    ],
  );
});
