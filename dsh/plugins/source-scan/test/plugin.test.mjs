import assert from "node:assert/strict";
import test from "node:test";

import { apply } from "../dist/index.js";

test("source scan plugin registers only its stage tool", () => {
  const registered = [];
  apply({ tools: { register: (tool) => registered.push(tool) } });
  assert.deepEqual(registered.map((tool) => tool.name), ["component_source_scan"]);
});
