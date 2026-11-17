import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-reporting";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_report",
      description: "Summarize the current run.",
      method: "report",
      parameters: {"run_id": {"type": "string", "required": true}},
    },
  ]);
}
