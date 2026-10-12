// Lets the cc-hud board find this window's terminals and open new ones. See vscode_bridge.py for the file protocol.
const vscode = require("vscode");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HUD_HOME = process.env.HUD_DB ? path.dirname(process.env.HUD_DB) : path.join(os.homedir(), ".claude", "hud");
const BRIDGE = path.join(HUD_HOME, "vscode");
const REGISTRY_REFRESH_MS = 2 * 60 * 1000;
const POLL_MS = 1000;
// Only a resume command, so a file someone else drops in the folder can't make this window type anything else.
const RESUME_TEXT = /^claude (--resume|attach) [A-Za-z0-9][\w-]*$/;

let windowFile;

function activate(context) {
  const windowId = crypto.randomBytes(16).toString("hex");
  windowFile = path.join(BRIDGE, "windows", `${windowId}.json`);
  const log = vscode.window.createOutputChannel("cc-hud");
  context.subscriptions.push(log);

  const safely = (what, fn) => async (...args) => {
    try {
      await fn(...args);
    } catch (err) {
      log.appendLine(`${new Date().toISOString()} ${what}: ${err.message}`);
    }
  };

  const writeRegistry = safely("registry", async () => {
    const pids = await Promise.all(vscode.window.terminals.map((t) => t.processId));
    const folders = (vscode.workspace.workspaceFolders || [])
      .filter((f) => f.uri.scheme === "file")
      .map((f) => f.uri.fsPath);
    const data = { windowId, folders, shellPids: pids.filter(Number.isInteger), updatedAt: Math.floor(Date.now() / 1000) };
    fs.mkdirSync(path.dirname(windowFile), { recursive: true });
    fs.writeFileSync(`${windowFile}.tmp`, JSON.stringify(data));
    fs.renameSync(`${windowFile}.tmp`, windowFile);
  });

  const inWorkspace = (cwd) =>
    (vscode.workspace.workspaceFolders || []).some((f) => {
      const rel = path.relative(f.uri.fsPath.toLowerCase(), cwd.toLowerCase());
      return rel === "" || (rel !== ".." && !rel.startsWith(".." + path.sep) && !path.isAbsolute(rel));
    });

  async function handle(file) {
    const request = JSON.parse(fs.readFileSync(file, "utf8"));
    if (request.kind === "focus") {
      if (!Number.isInteger(request.shellPid)) throw new Error("focus needs a shellPid");
      for (const terminal of vscode.window.terminals) {
        if ((await terminal.processId) === request.shellPid) {
          terminal.show(false);
          return;
        }
      }
      throw new Error(`no terminal with shell pid ${request.shellPid}`);
    }
    if (request.kind === "resume") {
      const stat = typeof request.cwd === "string" ? fs.statSync(request.cwd, { throwIfNoEntry: false }) : undefined;
      if (!stat || !stat.isDirectory()) throw new Error("resume needs an existing cwd");
      if (typeof request.text !== "string" || !RESUME_TEXT.test(request.text)) {
        throw new Error("resume text must be a claude --resume or claude attach command");
      }
      const terminal = vscode.window.createTerminal({ name: "claude", cwd: request.cwd });
      terminal.show(false);
      terminal.sendText(request.text, true);
      return;
    }
    throw new Error(`unknown request kind ${JSON.stringify(request.kind)}`);
  }

  function wantsShared(file) {
    try {
      const request = JSON.parse(fs.readFileSync(file, "utf8"));
      return request.kind === "resume" && typeof request.cwd === "string" && inWorkspace(request.cwd);
    } catch {
      return false;
    }
  }

  const drain = safely("requests", async (dir, shared) => {
    if (!fs.existsSync(dir)) return;
    for (const name of fs.readdirSync(dir)) {
      if (!name.endsWith(".json")) continue;
      const file = path.join(dir, name);
      if (shared && !wantsShared(file)) continue;
      const claimed = file.replace(/\.json$/, ".claimed");
      try {
        fs.renameSync(file, claimed);
      } catch (err) {
        if (err.code === "ENOENT") continue; // another window claimed it first
        throw err;
      }
      try {
        await handle(claimed);
      } catch (err) {
        log.appendLine(`${new Date().toISOString()} ${name}: ${err.message}`);
        fs.writeFileSync(claimed.replace(/\.claimed$/, ".failed"), err.message);
      }
      fs.rmSync(claimed, { force: true });
    }
  });

  const mine = path.join(BRIDGE, "requests", windowId);
  const shared = path.join(BRIDGE, "requests", "any");
  fs.mkdirSync(mine, { recursive: true });

  writeRegistry();
  const poll = setInterval(() => {
    drain(mine, false);
    drain(shared, true);
  }, POLL_MS);
  const refresh = setInterval(writeRegistry, REGISTRY_REFRESH_MS);
  context.subscriptions.push(
    { dispose: () => clearInterval(poll) },
    { dispose: () => clearInterval(refresh) },
    { dispose: () => fs.rmSync(mine, { recursive: true, force: true }) },
    vscode.window.onDidOpenTerminal(writeRegistry),
    vscode.window.onDidCloseTerminal(writeRegistry),
    vscode.workspace.onDidChangeWorkspaceFolders(writeRegistry),
  );
}

function deactivate() {
  if (windowFile) fs.rmSync(windowFile, { force: true });
}

module.exports = { activate, deactivate };
