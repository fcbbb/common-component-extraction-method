import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-task-execution";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_task",
      job: true,
      description: "Run one task arm.",
      method: "task",
      parameters: {"run_id": {"type": "string", "required": true}, "task_id": {"type": "string", "required": true}, "arm": {"type": "string", "enum": ["direct", "components"]}},
    },
  ]);
}
