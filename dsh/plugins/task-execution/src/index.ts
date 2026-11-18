import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-task-execution";
// Task execution runs as a background job, so `jobs` is a required service.
export const inject = ["tools", "jobs"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_task",
      job: true,
      description: "Run one retrieval-selected task with the components arm.",
      method: "task",
      parameters: {"run_id": {"type": "string", "required": true}, "task_id": {"type": "string", "required": true}},
    },
  ]);
}
