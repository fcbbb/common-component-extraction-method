import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-source-scan";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_source_scan",
      description: "Run stage 1 source scan and packet preparation.",
      method: "source_scan",
      // libclang parses every eligible file; large trees take far longer than
      // the generic budget, and killing the scan mid-parse makes the agent
      // retry a stage that would otherwise succeed.
      timeoutMs: 1_800_000,
      parameters: {"run_id": {"type": "string", "required": true, "description": "Registered run id."}, "task_id": {"type": "string", "description": "Optional registered task id."}},
    },
  ]);
}
