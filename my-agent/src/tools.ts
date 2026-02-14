/**
 * Tool definitions for the code assistant agent.
 *
 * Each tool has a name, description, JSON Schema parameters, and an execute function.
 */

import { execSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

// ---------------------------------------------------------------------------
// Tool interface
// ---------------------------------------------------------------------------

export interface Tool {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  execute: (args: Record<string, unknown>) => Promise<unknown>;
}

// ---------------------------------------------------------------------------
// Helper: safe command execution
// ---------------------------------------------------------------------------

function runCommand(cmd: string, cwd?: string): string {
  try {
    return execSync(cmd, {
      cwd: cwd ?? process.cwd(),
      timeout: 30_000,
      encoding: "utf-8",
      maxBuffer: 1024 * 1024,
    }).trim();
  } catch (err: any) {
    return err.stderr?.trim() || err.message;
  }
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export const readFileTool: Tool = {
  name: "read_file",
  description:
    "Read the contents of a file at the given path. Returns the file text.",
  parameters: {
    type: "object",
    properties: {
      path: { type: "string", description: "Absolute or relative file path." },
    },
    required: ["path"],
  },
  async execute(args) {
    const filePath = resolve(String(args.path));
    if (!existsSync(filePath)) return { error: `File not found: ${filePath}` };
    return readFileSync(filePath, "utf-8");
  },
};

export const writeFileTool: Tool = {
  name: "write_file",
  description:
    "Write (or overwrite) a file with the given content. Creates parent directories if needed.",
  parameters: {
    type: "object",
    properties: {
      path: { type: "string", description: "File path to write." },
      content: { type: "string", description: "Content to write." },
    },
    required: ["path", "content"],
  },
  async execute(args) {
    const filePath = resolve(String(args.path));
    writeFileSync(filePath, String(args.content), "utf-8");
    return { success: true, path: filePath };
  },
};

export const listFilesTool: Tool = {
  name: "list_files",
  description:
    "List files and directories at the given path. Returns names with type indicators.",
  parameters: {
    type: "object",
    properties: {
      path: {
        type: "string",
        description: "Directory path. Defaults to current directory.",
      },
    },
    required: [],
  },
  async execute(args) {
    const dirPath = resolve(String(args.path ?? "."));
    if (!existsSync(dirPath)) return { error: `Directory not found: ${dirPath}` };

    const entries = readdirSync(dirPath).map((name) => {
      const full = join(dirPath, name);
      const isDir = statSync(full).isDirectory();
      return `${isDir ? "📁" : "📄"} ${name}`;
    });

    return entries.join("\n");
  },
};

export const runCommandTool: Tool = {
  name: "run_command",
  description:
    "Execute a shell command and return stdout. Use for running tests, linters, git, etc.",
  parameters: {
    type: "object",
    properties: {
      command: { type: "string", description: "Shell command to execute." },
      cwd: {
        type: "string",
        description: "Working directory (optional, defaults to cwd).",
      },
    },
    required: ["command"],
  },
  async execute(args) {
    return runCommand(String(args.command), args.cwd as string | undefined);
  },
};

export const searchFilesTool: Tool = {
  name: "search_files",
  description:
    "Search for a pattern in files using grep. Returns matching lines with file paths.",
  parameters: {
    type: "object",
    properties: {
      pattern: { type: "string", description: "Regex pattern to search for." },
      path: {
        type: "string",
        description: "Directory to search in (default: cwd).",
      },
      glob: {
        type: "string",
        description: "File glob filter, e.g. '*.ts' (optional).",
      },
    },
    required: ["pattern"],
  },
  async execute(args) {
    const dir = resolve(String(args.path ?? "."));
    const includeFlag = args.glob ? `--include='${args.glob}'` : "";
    return runCommand(
      `grep -rn ${includeFlag} '${String(args.pattern)}' '${dir}' 2>/dev/null | head -50`
    );
  },
};

// ---------------------------------------------------------------------------
// Default tool set
// ---------------------------------------------------------------------------

export const defaultTools: Tool[] = [
  readFileTool,
  writeFileTool,
  listFilesTool,
  runCommandTool,
  searchFilesTool,
];
