import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-ops";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_prepare_workspace",
      description: "Prepare a workspace.",
      method: "ops",
      parameters: {"module": {"type": "string", "required": true}, "args": {"type": "array", "items": {"type": "string"}}, "run_id": {"type": "string"}},
    },
    {
      name: "component_dataset_adapter",
      description: "Run the OS-Bench adapter.",
      method: "ops",
      parameters: {"module": {"type": "string", "required": true}, "args": {"type": "array", "items": {"type": "string"}}, "run_id": {"type": "string"}},
    },
  ]);
}
