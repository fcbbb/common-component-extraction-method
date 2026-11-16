import { defineTool } from "@deepseek-ai/dsh-tools";
import { kernelTool, runKernel } from "@component-method/dsh-method-shared";

export const name = "component-method-agent-runtime";
export const inject = ["tools"];

export function apply(ctx: any): void {
  ctx.tools.register(kernelTool({
    name: "component_check_submission",
    description: "Validate the current component output without ending the turn.",
    method: "check_submission",
    parameters: {},
  }));
  ctx.tools.register(defineTool({
    name: "component_submit",
    description: "Validate the current component output and finish the turn.",
    parameters: {},
    output: {
      schema: {
        type: "object",
        additionalProperties: true,
        properties: {
          ok: { type: "boolean", required: true },
          role: { type: "string" },
          error: { type: "string" },
        },
      },
      render: (_args: unknown, value: any) => [{
        type: "text",
        text: value.ok ? "submission validated" : String(value.error || "submission rejected"),
      }],
    },
    async execute(_args: unknown, execution: any) {
      const result = await runKernel("check_submission", {});
      if (result.ok === true) execution.concludeTurn();
      return result as any;
    },
  }));
  ctx.tools.register(kernelTool({
    name: "component_validate_draft",
    description: "Validate a component draft against the shared component contract.",
    method: "validate_draft",
    parameters: {
      component: { type: "object", required: true, additionalProperties: true },
      component_id: { type: "string" },
    },
  }));
  ctx.tools.register(kernelTool({
    name: "component_validate_artifact",
    description: "Validate a component artifact with the selected language backend.",
    method: "validate_artifact",
    parameters: {
      artifact: { type: "object", required: true, additionalProperties: true },
    },
  }));
  ctx.tools.register(kernelTool({
    name: "component_check_patch",
    description: "Run git apply --check for the controller-owned patch.",
    method: "check_patch",
    parameters: {},
  }));
}
