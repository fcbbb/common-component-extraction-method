import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-library-publish";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_publish_library",
      description: "Publish the reviewed component library.",
      method: "publish_library",
      parameters: {"run_id": {"type": "string", "required": true}},
    },
  ]);
}
