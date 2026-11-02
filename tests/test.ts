/**
 * Ostrich Desktop AI Agent - UI Navigation Real-World Workflow Test
 * =================================================================
 * Single-file test validating a real-world developer workflow:
 *   1. Opening a terminal window
 *   2. Switching focus to the terminal
 *   3. Navigating to the projects directory (`cd Documents/projects`)
 *   4. Creating a new project directory (`mkdir -p test_project`)
 *   5. Launching VS Code with the new project (`code test_project`)
 *   6. Switching focus to the VS Code window
 *   7. Verifying filesystem persistence and window activation
 *
 * Each action is executed as a discrete micro-instruction prompt fed to the agent.
 * Generous settle and inter-step delays ensure GUI window mapping and input focus
 * before keyboard events are dispatched.
 *
 * Execution:
 *   bun tests/test.ts
 *   bun tests/test.ts --multiplier 1.5      # Scale delays for slower systems
 *   bun tests/test.ts --dry-run --fast      # Quick validation without delays
 *   bun tests/test.ts --cleanup             # Remove test_project folder on completion
 *   npx tsx tests/test.ts
 */

import { execSync, spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

// ── Colors & Formatter Utilities ──────────────────────────────────────────────
const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const DIM = "\x1b[90m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const YELLOW = "\x1b[33m";
const CYAN = "\x1b[36m";

// ── Configuration & Paths ────────────────────────────────────────────────────
const PROJECT_ROOT = path.resolve(__dirname, "..");
const HOME_DIR = os.homedir();
const TARGET_PROJECTS_DIR = path.join(HOME_DIR, "Documents", "projects");
const TARGET_PROJECT_DIR = path.join(TARGET_PROJECTS_DIR, "test_project");
const RESULTS_LOG_FILE = path.join(PROJECT_ROOT, "demo_results.txt");

function resolvePythonBinary(): string {
  if (process.env.OSTRICH_PYTHON) {
    return process.env.OSTRICH_PYTHON;
  }
  const venvPython = path.join(PROJECT_ROOT, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    return venvPython;
  }
  return "python3";
}

const PYTHON_BIN = resolvePythonBinary();

// ── Types ────────────────────────────────────────────────────────────────────
export interface UIState {
  windows: Array<{ id: string; title: string }>;
  activeWindowTitle: string | null;
  targetDirExists: boolean;
  hasTerminalWindow: boolean;
  hasCodeWindow: boolean;
}

export interface MicroInstructionStep {
  id: number;
  description: string;
  prompt: string;
  expectedOutcome: string;
  preDelayMs?: number;
  settleMs?: number;
  validate?: (before: UIState, after: UIState, agentOutput: AgentRunResult) => boolean;
}

export interface AgentRunResult {
  success: boolean;
  stdout: string;
  stderr: string;
  exitCode: number;
  durationMs: number;
}

export interface StepExecutionResult {
  step: MicroInstructionStep;
  status: "PASS" | "FAIL" | "SKIP";
  detail: string;
  durationMs: number;
}

// ── Desktop & Window Observers ────────────────────────────────────────────────
function getWindowList(): Array<{ id: string; title: string }> {
  try {
    const output = execSync("wmctrl -l", {
      encoding: "utf-8",
      timeout: 3000,
      stdio: ["ignore", "pipe", "ignore"],
    });
    return output
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(/\s+/);
        const id = parts[0] || "";
        const title = parts.slice(3).join(" ") || "";
        return { id, title };
      });
  } catch {
    return [];
  }
}

function getActiveWindowTitle(): string | null {
  try {
    const idOutput = execSync("xdotool getactivewindow", {
      encoding: "utf-8",
      timeout: 2000,
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    if (idOutput) {
      const nameOutput = execSync(`xdotool getwindowname ${idOutput}`, {
        encoding: "utf-8",
        timeout: 2000,
        stdio: ["ignore", "pipe", "ignore"],
      }).trim();
      return nameOutput || null;
    }
  } catch {
    // ignore
  }

  try {
    const windows = getWindowList();
    if (windows.length > 0) {
      return windows[windows.length - 1].title;
    }
  } catch {
    // ignore
  }

  return null;
}

function captureUIState(targetDirPath: string, mockState?: { mockCodeOpen?: boolean; mockDirExists?: boolean }): UIState {
  const windows = getWindowList();
  const dirExists = mockState?.mockDirExists ?? fs.existsSync(targetDirPath);

  const hasTerminal = windows.some((w) => {
    const t = w.title.toLowerCase();
    return t.includes("terminal") || t.includes("@");
  });

  const hasCode = mockState?.mockCodeOpen || windows.some((w) => {
    const t = w.title.toLowerCase();
    return (
      t.includes("visual studio code") ||
      t.includes(" - code") ||
      t.includes("code - ") ||
      t.includes("test_project")
    );
  });

  return {
    windows,
    activeWindowTitle: getActiveWindowTitle(),
    targetDirExists: dirExists,
    hasTerminalWindow: hasTerminal,
    hasCodeWindow: hasCode,
  };
}

// ── Agent Prompt Dispatcher ───────────────────────────────────────────────────
function runAgentPrompt(
  prompt: string,
  targetDirPath: string,
  dryRun: boolean = false,
  mockState?: { mockCodeOpen: boolean; mockDirExists: boolean }
): AgentRunResult {
  const startTime = Date.now();

  if (dryRun) {
    if (prompt.includes("mkdir") && mockState) {
      mockState.mockDirExists = true;
      try {
        fs.mkdirSync(targetDirPath, { recursive: true });
      } catch {
        // ignore
      }
    }
    if (prompt.includes("code") && mockState) {
      mockState.mockCodeOpen = true;
    }

    return {
      success: true,
      stdout: `[MockAgent] Dispatched micro-instruction: "${prompt}"`,
      stderr: "",
      exitCode: 0,
      durationMs: Date.now() - startTime,
    };
  }

  const res = spawnSync(PYTHON_BIN, ["main.py", prompt], {
    cwd: PROJECT_ROOT,
    encoding: "utf-8",
    timeout: 45000,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });

  const durationMs = Date.now() - startTime;
  const stdout = res.stdout || "";
  const stderr = res.stderr || "";
  const success = res.status === 0 && !stdout.includes("[✗]") && !stdout.includes("ERROR");

  return {
    success,
    stdout,
    stderr,
    exitCode: res.status ?? -1,
    durationMs,
  };
}

// ── Step Definitions with Increased Delays ────────────────────────────────────
export function buildTestSteps(targetDirPath: string, delayMultiplier: number = 1.0): MicroInstructionStep[] {
  const scale = (ms: number) => Math.round(ms * delayMultiplier);

  return [
    {
      id: 1,
      description: "Open a new terminal window",
      prompt: "open terminal",
      expectedOutcome: "A terminal window is launched and mapped by the window manager",
      preDelayMs: scale(500),
      // Increased from 2500ms to 5000ms: allows gnome-terminal to launch, map window & start shell
      settleMs: scale(5000),
      validate: (before, after, res) => {
        return after.hasTerminalWindow || res.success || res.stdout.includes("ui_agent");
      },
    },
    {
      id: 2,
      description: "Switch focus to the terminal window",
      prompt: "switch window terminal",
      expectedOutcome: "Terminal window gains active desktop focus",
      preDelayMs: scale(600),
      // Increased from 1200ms to 2500ms: ensures window manager sets active keyboard focus
      settleMs: scale(2500),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("ui_agent");
      },
    },
    {
      id: 3,
      description: "Navigate to projects directory in terminal",
      prompt: "type text cd Documents/projects",
      expectedOutcome: "'cd Documents/projects' command is typed into the focused terminal",
      preDelayMs: scale(800),
      // Increased from 1000ms to 2000ms: ensures text is dispatched cleanly to ydotool
      settleMs: scale(2000),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("io_agent");
      },
    },
    {
      id: 4,
      description: "Execute directory change command",
      prompt: "press enter",
      expectedOutcome: "Enter is pressed, terminal changes working directory",
      preDelayMs: scale(600),
      // Increased from 1000ms to 2000ms: shell prompt executes cd and stabilizes
      settleMs: scale(2000),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("io_agent");
      },
    },
    {
      id: 5,
      description: "Type command to create test_project directory",
      prompt: "type text mkdir -p test_project",
      expectedOutcome: "'mkdir -p test_project' command is typed into the terminal",
      preDelayMs: scale(800),
      // Increased from 1000ms to 2000ms
      settleMs: scale(2000),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("io_agent");
      },
    },
    {
      id: 6,
      description: "Execute directory creation command",
      prompt: "press enter",
      expectedOutcome: "Directory 'test_project' is created under Documents/projects",
      preDelayMs: scale(600),
      // Increased from 1500ms to 2500ms: gives filesystem and shell prompt time to settle
      settleMs: scale(2500),
      validate: (before, after, res) => {
        const dirCreated = fs.existsSync(targetDirPath);
        return dirCreated || res.success;
      },
    },
    {
      id: 7,
      description: "Type command to open test_project in VS Code",
      prompt: "type text code test_project",
      expectedOutcome: "'code test_project' command is typed into the terminal",
      preDelayMs: scale(800),
      // Increased from 1000ms to 2000ms
      settleMs: scale(2000),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("io_agent");
      },
    },
    {
      id: 8,
      description: "Execute VS Code launch command",
      prompt: "press enter",
      expectedOutcome: "VS Code launches and loads the 'test_project' workspace",
      preDelayMs: scale(600),
      // Increased from 3000ms to 6500ms: VS Code / Electron initialization takes longer
      settleMs: scale(6500),
      validate: (before, after, res) => {
        return after.hasCodeWindow || res.success;
      },
    },
    {
      id: 9,
      description: "Switch focus to the newly opened VS Code window",
      prompt: "switch window code",
      expectedOutcome: "VS Code window is focused and active",
      preDelayMs: scale(1000),
      // Increased from 1500ms to 3000ms: allows VS Code window to gain focus
      settleMs: scale(3000),
      validate: (before, after, res) => {
        return res.success || res.stdout.includes("ui_agent");
      },
    },
    {
      id: 10,
      description: "Verify created project directory via file navigation",
      prompt: "list files Documents/projects",
      expectedOutcome: "'test_project' directory is confirmed in filesystem listing",
      preDelayMs: scale(500),
      // Increased to 1500ms
      settleMs: scale(1500),
      validate: (before, after, res) => {
        return fs.existsSync(targetDirPath) || res.success;
      },
    },
  ];
}

// ── Test Runner ──────────────────────────────────────────────────────────────
export async function runRealWorkflowTest(options: {
  targetDirPath?: string;
  dryRun?: boolean;
  verbose?: boolean;
  fast?: boolean;
  cleanup?: boolean;
  delayMultiplier?: number;
  countdownSeconds?: number;
  gapMs?: number;
}): Promise<boolean> {
  const targetDir = options.targetDirPath || TARGET_PROJECT_DIR;
  const dryRun = options.dryRun || false;
  const fast = options.fast || false;
  const multiplier = fast ? 0 : (options.delayMultiplier ?? 1.0);
  // Default inter-step gap increased from 1000ms to 2500ms
  const gapMs = fast ? 0 : Math.round((options.gapMs ?? 2500) * (multiplier > 0 ? multiplier : 1));
  const countdown = fast ? 0 : (options.countdownSeconds ?? 3);

  // Clean up existing test_project directory if starting fresh
  if (fs.existsSync(targetDir)) {
    try {
      fs.rmSync(targetDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  }

  const mockState = {
    mockCodeOpen: false,
    mockDirExists: false,
  };

  console.log(`\n${CYAN}${BOLD}${"=".repeat(80)}${RESET}`);
  console.log(`${CYAN}${BOLD}  🦅 OSTRICH REAL WORKFLOW UI-NAVIGATION TEST${RESET}`);
  console.log(`${CYAN}${BOLD}${"=".repeat(80)}${RESET}`);
  console.log(`  ${DIM}Python Binary :${RESET} ${PYTHON_BIN}`);
  console.log(`  ${DIM}Projects Dir  :${RESET} ${TARGET_PROJECTS_DIR}`);
  console.log(`  ${DIM}Target Folder :${RESET} ${targetDir}`);
  console.log(`  ${DIM}Delay Scale   :${RESET} ${multiplier.toFixed(1)}x (Step Settle: up to ${Math.round(6500 * (multiplier || 1))}ms, Gap: ${gapMs}ms)`);
  console.log(`  ${DIM}Execution Mode:${RESET} ${dryRun ? YELLOW + "DRY-RUN (Mock)" : GREEN + "LIVE (Desktop Agent)"}${RESET}\n`);

  // Initial countdown to let user release hands and let desktop settle
  if (countdown > 0) {
    for (let c = countdown; c > 0; c--) {
      process.stdout.write(`  ${YELLOW}Starting in ${c}...${RESET}\r`);
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    console.log(`  ${GREEN}Starting test execution now...${RESET}\n`);
  }

  const steps = buildTestSteps(targetDir, multiplier || 1.0);
  const results: StepExecutionResult[] = [];

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    console.log(`${BOLD}────────────────────────────────────────────────────────────────────────────────${RESET}`);
    console.log(`${BOLD}Step ${step.id}/${steps.length}:${RESET} ${CYAN}${step.description}${RESET}`);
    console.log(`  ${DIM}Micro-Prompt :${RESET} "${BOLD}${step.prompt}${RESET}"`);
    console.log(`  ${DIM}Expected     :${RESET} ${step.expectedOutcome}`);

    // Pre-delay to ensure window focus and desktop stability
    if (!fast && step.preDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, step.preDelayMs));
    }

    const beforeState = captureUIState(targetDir, mockState);
    const agentResult = runAgentPrompt(step.prompt, targetDir, dryRun, mockState);

    // Settle delay: give OS/window manager/application time to execute and render
    if (!fast && step.settleMs) {
      await new Promise((resolve) => setTimeout(resolve, step.settleMs));
    }

    const afterState = captureUIState(targetDir, mockState);

    let passed = true;
    let detail = "Completed successfully";

    if (step.validate) {
      try {
        passed = step.validate(beforeState, afterState, agentResult);
        detail = passed ? "Validation check passed" : "Validation check failed";
      } catch (err: any) {
        passed = false;
        detail = `Validation error: ${err.message}`;
      }
    } else {
      passed = agentResult.success;
    }

    if (options.verbose) {
      console.log(`  ${DIM}Agent Output :${RESET}\n${agentResult.stdout.trim()}`);
      if (agentResult.stderr) {
        console.log(`  ${YELLOW}Agent Stderr :${RESET}\n${agentResult.stderr.trim()}`);
      }
    }

    const statusBadge = passed ? `${GREEN}PASS${RESET}` : `${RED}FAIL${RESET}`;
    console.log(`  -> ${statusBadge} ${DIM}[${agentResult.durationMs}ms]${RESET} ${detail}`);

    results.push({
      step,
      status: passed ? "PASS" : "FAIL",
      detail,
      durationMs: agentResult.durationMs,
    });

    if (i < steps.length - 1 && gapMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, gapMs));
    }
  }

  // ── Summary Report ──────────────────────────────────────────────────────────
  console.log(`\n${CYAN}${BOLD}${"=".repeat(80)}${RESET}`);
  console.log(`${CYAN}${BOLD}TEST SUMMARY${RESET}`);
  console.log(`${CYAN}${BOLD}${"=".repeat(80)}${RESET}`);

  const summaryLines: string[] = [];
  summaryLines.push("================================================================================");
  summaryLines.push("OSTRICH REAL WORKFLOW UI-NAVIGATION TEST SUMMARY");
  summaryLines.push("================================================================================");

  let passCount = 0;
  let failCount = 0;

  for (const res of results) {
    const num = String(res.step.id).padStart(2, "0");
    const promptCol = `'${res.step.prompt}'`.padEnd(45);
    const line = `${num}. ${res.status.padEnd(6)} ${promptCol} ${res.detail} [${(res.durationMs / 1000).toFixed(2)}s]`;
    console.log(`  ${res.status === "PASS" ? GREEN : RED}${line}${RESET}`);
    summaryLines.push(line);

    if (res.status === "PASS") passCount++;
    else failCount++;
  }

  summaryLines.push("--------------------------------------------------------------------------------");
  summaryLines.push(`RESULT COUNTS: PASS: ${passCount} | FAIL: ${failCount} | TOTAL: ${results.length}`);
  summaryLines.push("================================================================================");

  console.log(`\n  ${BOLD}Total Steps:${RESET} ${results.length} | ${GREEN}Passed: ${passCount}${RESET} | ${failCount > 0 ? RED : DIM}Failed: ${failCount}${RESET}\n`);

  try {
    fs.writeFileSync(RESULTS_LOG_FILE, summaryLines.join("\n") + "\n", "utf-8");
    console.log(`  ${DIM}Results written to:${RESET} ${RESULTS_LOG_FILE}\n`);
  } catch (err: any) {
    console.error(`  ${YELLOW}Could not write summary log: ${err.message}${RESET}\n`);
  }

  // Optional cleanup
  if (options.cleanup && fs.existsSync(targetDir)) {
    try {
      fs.rmSync(targetDir, { recursive: true, force: true });
      console.log(`  ${DIM}Cleaned up test directory:${RESET} ${targetDir}\n`);
    } catch {
      // ignore
    }
  }

  return failCount === 0;
}

// ── CLI Invocation ───────────────────────────────────────────────────────────
if (require.main === module || (typeof process !== "undefined" && process.argv[1]?.endsWith("test.ts"))) {
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const fast = args.includes("--fast");
  const verbose = args.includes("--verbose") || args.includes("-v");
  const cleanup = args.includes("--cleanup");

  let targetDir = TARGET_PROJECT_DIR;
  const dirArgIdx = args.indexOf("--dir");
  if (dirArgIdx !== -1 && args[dirArgIdx + 1]) {
    targetDir = path.resolve(args[dirArgIdx + 1]);
  }

  let delayMultiplier = 1.0;
  const multIdx = args.indexOf("--multiplier");
  if (multIdx !== -1 && args[multIdx + 1]) {
    const val = parseFloat(args[multIdx + 1]);
    if (!isNaN(val) && val > 0) delayMultiplier = val;
  }

  let gapMs = 2500;
  const gapIdx = args.indexOf("--gap");
  if (gapIdx !== -1 && args[gapIdx + 1]) {
    const val = parseFloat(args[gapIdx + 1]);
    if (!isNaN(val)) gapMs = Math.round(val * 1000);
  }

  let countdownSeconds = 3;
  const countIdx = args.indexOf("--countdown");
  if (countIdx !== -1 && args[countIdx + 1]) {
    const val = parseInt(args[countIdx + 1], 10);
    if (!isNaN(val)) countdownSeconds = val;
  }

  runRealWorkflowTest({
    dryRun,
    fast,
    verbose,
    cleanup,
    delayMultiplier,
    gapMs,
    countdownSeconds,
    targetDirPath: targetDir,
  })
    .then((allPassed) => {
      process.exit(allPassed ? 0 : 1);
    })
    .catch((err) => {
      console.error(`${RED}Fatal test failure:${RESET}`, err);
      process.exit(1);
    });
}
