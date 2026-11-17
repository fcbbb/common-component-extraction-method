import http from "node:http";
import { mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { performance } from "node:perf_hooks";

import { defineTool } from "@deepseek-ai/dsh-tools";


const DEFAULT_OUTPUT_LIMIT = 200_000;
const COMPLETION_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT";
const BASE_TOOL_ENV = [
  "HOME=/tmp",
  "LANG=C.UTF-8",
  "LC_ALL=C.UTF-8",
  "PAGER=cat",
  "PATH=/usr/local/bin:/usr/bin:/bin",
  "PYTHONDONTWRITEBYTECODE=1",
  "PYTHONPATH=/testbed",
  "TMPDIR=/tmp",
];

export const name = "component-method-controlled-bash";
export const inject = ["tools"];

interface DockerResponse {
  statusCode: number;
  body: Buffer;
}

interface ExecResult {
  exitCode: number;
  output: Buffer;
  durationMs: number;
}

interface ControlledBashResult {
  exit_code: number;
  duration_ms: number;
  output_bytes: number;
  truncated: boolean;
  output: string;
}

interface ValidatedSubmission {
  validated: true;
  transport: "files" | "patch";
  role: string;
  container_name: string;
  checker_exit_code: 0;
  validated_at: string;
}

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function toolEnvironment(): string[] {
  const role = process.env.COMPONENT_DSH_SUBMISSION_ROLE?.trim();
  if (role && !/^[a-z][a-z0-9_]*$/.test(role)) {
    throw new Error("COMPONENT_DSH_SUBMISSION_ROLE is invalid");
  }
  return role ? [...BASE_TOOL_ENV, `COMPONENT_OUTPUT_ROLE=${role}`] : BASE_TOOL_ENV;
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

export function submissionCheckerCommand(role: string): string {
  const configured = process.env.COMPONENT_DSH_CHECKER_COMMAND_JSON?.trim();
  if (configured) {
    let command: unknown;
    try {
      command = JSON.parse(configured);
    } catch (error) {
      throw new Error(`COMPONENT_DSH_CHECKER_COMMAND_JSON is invalid JSON: ${error}`);
    }
    if (
      !Array.isArray(command)
      || command.length === 0
      || command.some((argument) => typeof argument !== "string" || !argument)
    ) {
      throw new Error(
        "COMPONENT_DSH_CHECKER_COMMAND_JSON must be a non-empty string array",
      );
    }
    return command.map(shellQuote).join(" ");
  }
  const checkerPath = process.env.COMPONENT_DSH_CHECKER_PATH || "/component-tools/check_output.py";
  const outputDirectory = process.env.COMPONENT_DSH_OUTPUT_DIRECTORY || "/component-output";
  if (!checkerPath.startsWith("/") || !outputDirectory.startsWith("/")) {
    throw new Error("submission checker paths must be absolute container paths");
  }
  return [
    "python",
    shellQuote(checkerPath),
    "--role",
    shellQuote(role),
    "--output",
    shellQuote(outputDirectory),
  ].join(" ");
}

function commandWithActivation(command: string): string {
  const activation = process.env.COMPONENT_DSH_RUNTIME_ACTIVATION?.trim();
  return activation ? `${activation} && ${command}` : command;
}

function dockerRequest(
  socketPath: string,
  method: string,
  path: string,
  payload?: object,
): Promise<DockerResponse> {
  const body = payload === undefined ? undefined : Buffer.from(JSON.stringify(payload));
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        socketPath,
        method,
        path,
        headers: body === undefined ? undefined : {
          "Content-Type": "application/json",
          "Content-Length": body.byteLength,
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.on("end", () => resolve({
          statusCode: response.statusCode ?? 0,
          body: Buffer.concat(chunks),
        }));
      },
    );
    request.on("error", reject);
    if (body !== undefined) {
      request.write(body);
    }
    request.end();
  });
}

function requireSuccess(response: DockerResponse, operation: string): Buffer {
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const detail = response.body.toString("utf8").slice(0, 2_000);
    throw new Error(`${operation} failed with HTTP ${response.statusCode}: ${detail}`);
  }
  return response.body;
}

export function decodeDockerStream(payload: Buffer): Buffer {
  const chunks: Buffer[] = [];
  let offset = 0;
  while (offset + 8 <= payload.byteLength) {
    const size = payload.readUInt32BE(offset + 4);
    const end = offset + 8 + size;
    if (end > payload.byteLength) {
      return payload;
    }
    chunks.push(payload.subarray(offset + 8, end));
    offset = end;
  }
  return offset === payload.byteLength ? Buffer.concat(chunks) : payload;
}

async function executeInContainer(
  containerName: string,
  cwd: string,
  command: string,
  timeoutSeconds: number,
): Promise<ExecResult> {
  const socketPath = process.env.COMPONENT_DSH_DOCKER_SOCKET || "/var/run/docker.sock";
  const inspect = await dockerRequest(
    socketPath,
    "GET",
    `/containers/${encodeURIComponent(containerName)}/json`,
  );
  const container = JSON.parse(requireSuccess(inspect, "container inspection").toString("utf8"));
  if (container?.State?.Running !== true) {
    throw new Error("TaskEnvironmentLost: selected container is not running");
  }

  const wrapped = [
    "timeout",
    "--signal=TERM",
    "--kill-after=5s",
    `${timeoutSeconds}s`,
    "/bin/bash",
    "-lc",
    command,
  ];
  const create = await dockerRequest(
    socketPath,
    "POST",
    `/containers/${encodeURIComponent(containerName)}/exec`,
    {
      AttachStdout: true,
      AttachStderr: true,
      Tty: false,
      User: "10001:10001",
      WorkingDir: cwd,
      Env: toolEnvironment(),
      Cmd: wrapped,
    },
  );
  const execId = JSON.parse(requireSuccess(create, "exec creation").toString("utf8")).Id;
  if (!execId) {
    throw new Error("Docker exec creation returned no exec id");
  }

  const started = performance.now();
  const start = await dockerRequest(
    socketPath,
    "POST",
    `/exec/${encodeURIComponent(execId)}/start`,
    { Detach: false, Tty: false },
  );
  const output = decodeDockerStream(requireSuccess(start, "exec start"));
  const state = await dockerRequest(
    socketPath,
    "GET",
    `/exec/${encodeURIComponent(execId)}/json`,
  );
  const exitCode = JSON.parse(requireSuccess(state, "exec inspection").toString("utf8")).ExitCode;
  if (!Number.isInteger(exitCode)) {
    throw new Error("Docker exec inspection returned no exit code");
  }
  return { exitCode, output, durationMs: Math.round(performance.now() - started) };
}

export function firstEffectiveLine(output: Buffer): string | undefined {
  return output.toString("utf8").split(/\r?\n/).find((line) => line.trim())?.trim();
}

export function containsCompletionMarker(output: Buffer): boolean {
  return output
    .toString("utf8")
    .split(/\r?\n/)
    .some((line) => line.trim() === COMPLETION_MARKER);
}

async function writeValidatedSubmission(record: ValidatedSubmission): Promise<void> {
  const target = requiredEnvironment("COMPONENT_DSH_VALIDATED_SUBMISSION_PATH");
  const directory = path.dirname(target);
  await mkdir(directory, { recursive: true });
  const temporary = `${target}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(record, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  await rename(temporary, target);
}

async function validateCompletion(
  containerName: string,
  cwd: string,
  commandResult: ExecResult,
  timeoutSeconds: number,
): Promise<{ result: ExecResult; completed: boolean }> {
  const submissionMode = process.env.COMPONENT_DSH_SUBMISSION_MODE;
  if (
    !["files", "patch"].includes(submissionMode ?? "")
    || commandResult.exitCode !== 0
    || !containsCompletionMarker(commandResult.output)
  ) {
    return { result: commandResult, completed: false };
  }

  const role = requiredEnvironment("COMPONENT_DSH_SUBMISSION_ROLE");
  if (!/^[a-z][a-z0-9_]*$/.test(role)) {
    throw new Error("COMPONENT_DSH_SUBMISSION_ROLE is invalid");
  }
  const checkerCommand = commandWithActivation(submissionCheckerCommand(role));
  const checked = await executeInContainer(
    containerName,
    cwd,
    checkerCommand,
    Math.min(timeoutSeconds, 120),
  );
  if (checked.exitCode !== 0) {
    const rejection = Buffer.concat([
      Buffer.from("Submission rejected; correct the files and submit again.\n"),
      checked.output,
    ]);
    return {
      result: {
        exitCode: checked.exitCode || 1,
        output: rejection,
        durationMs: commandResult.durationMs + checked.durationMs,
      },
      completed: false,
    };
  }

  await writeValidatedSubmission({
    validated: true,
    transport: submissionMode as "files" | "patch",
    role,
    container_name: containerName,
    checker_exit_code: 0,
    validated_at: new Date().toISOString(),
  });
  return {
    result: {
      exitCode: 0,
      output: Buffer.from(`${COMPLETION_MARKER}\n{"transport":"${submissionMode}"}\n`),
      durationMs: commandResult.durationMs + checked.durationMs,
    },
    completed: true,
  };
}

export function cwdOrFallback(value: string): string {
  try {
    return allowedCwd(value);
  } catch (error) {
    const fallback = process.env.COMPONENT_DSH_DEFAULT_CWD?.trim();
    if (!fallback) throw error;
    return allowedCwd(fallback);
  }
}

export function allowedCwd(value: string): string {
  const allowed = JSON.parse(requiredEnvironment("COMPONENT_DSH_ALLOWED_CWDS"));
  if (!Array.isArray(allowed) || allowed.some((item) => typeof item !== "string")) {
    throw new Error("COMPONENT_DSH_ALLOWED_CWDS must be a JSON string array");
  }
  if (!value.startsWith("/") || value.includes("\0")) {
    throw new Error("cwd must be an absolute container path");
  }
  const normalizedValue = path.posix.normalize(value);
  const cwd = normalizedValue === "/" ? normalizedValue : normalizedValue.replace(/\/+$/, "");
  const valid = allowed.some((root) => {
    if (!root.startsWith("/") || root.includes("\0")) {
      throw new Error("allowed cwd roots must be absolute container paths");
    }
    const normalizedRoot = path.posix.normalize(root);
    const normalized = normalizedRoot === "/"
      ? normalizedRoot
      : normalizedRoot.replace(/\/+$/, "");
    return normalized === "/"
      ? cwd.startsWith("/")
      : cwd === normalized || cwd.startsWith(`${normalized}/`);
  });
  if (!valid) {
    throw new Error(`cwd is outside the allowed container paths: ${cwd}`);
  }
  return cwd;
}

export function canonicalResult(result: ExecResult): ControlledBashResult {
  const limit = Number(process.env.COMPONENT_DSH_OUTPUT_LIMIT || DEFAULT_OUTPUT_LIMIT);
  const originalBytes = result.output.byteLength;
  let output = result.output;
  let truncated = false;
  if (Number.isFinite(limit) && limit >= 2_000 && output.byteLength > limit) {
    const side = Math.floor(limit / 2);
    output = Buffer.concat([
      output.subarray(0, side),
      Buffer.from("\n... output truncated ...\n"),
      output.subarray(output.byteLength - side),
    ]);
    truncated = true;
  }
  return {
    exit_code: result.exitCode,
    duration_ms: result.durationMs,
    output_bytes: originalBytes,
    truncated,
    output: output.toString("utf8"),
  };
}

function renderOutput(result: ControlledBashResult): string {
  return [
    `exit_code=${result.exit_code}`,
    `duration_ms=${result.duration_ms}`,
    `output_bytes=${result.output_bytes}`,
    `truncated=${result.truncated}`,
    "--- output ---",
    result.output,
  ].join("\n");
}

export function apply(ctx: any): void {
  const controlledBash = defineTool({
    name: "controlled_bash",
    description: "Execute one non-interactive Bash command in the selected isolated task container.",
    parameters: {
      command: {
        type: "string",
        required: true,
        description: "The complete Bash command to execute.",
      },
      cwd: {
        type: "string",
        required: true,
        description: "Absolute working directory inside the container.",
      },
      timeout_seconds: {
        type: "number",
        required: true,
        description: "Command timeout in seconds.",
      },
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: false,
        properties: {
          exit_code: { type: "integer", required: true },
          duration_ms: { type: "integer", required: true },
          output_bytes: { type: "integer", required: true },
          truncated: { type: "boolean", required: true },
          output: { type: "string", required: true },
        },
      },
      render: (_args, value) => [{ type: "text", text: renderOutput(value) }],
    },
    async execute(args, execution) {
      const expectedContainer = requiredEnvironment("COMPONENT_DSH_CONTAINER_NAME");
      const cwd = cwdOrFallback(args.cwd);
      const configuredLimit = Number(requiredEnvironment("COMPONENT_DSH_COMMAND_TIMEOUT"));
      if (!Number.isFinite(configuredLimit) || configuredLimit < 1) {
        throw new Error("COMPONENT_DSH_COMMAND_TIMEOUT must be a positive number");
      }
      if (!Number.isFinite(args.timeout_seconds) || args.timeout_seconds < 1) {
        throw new Error("timeout_seconds must be a positive number");
      }
      const timeoutSeconds = Math.min(args.timeout_seconds, configuredLimit);
      const result = await executeInContainer(
        expectedContainer,
        cwd,
        commandWithActivation(args.command),
        timeoutSeconds,
      );
      const completion = await validateCompletion(
        expectedContainer,
        cwd,
        result,
        timeoutSeconds,
      );
      if (completion.completed) {
        execution.concludeTurn();
      }
      return canonicalResult(completion.result);
    },
  });

  ctx.tools.register(controlledBash);
}
