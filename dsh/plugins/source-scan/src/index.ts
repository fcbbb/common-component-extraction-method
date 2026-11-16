import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-source-scan";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_source_scan",
      description: "Run stage 1 source scan and packet preparation.",
      method: "source_scan",
      parameters: {"run_id": {"type": "string", "required": true, "description": "Registered run id."}, "task_id": {"type": "string", "description": "Optional registered task id."}},
    },
  ]);
}
