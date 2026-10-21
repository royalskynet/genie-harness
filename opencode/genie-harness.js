import { fileURLToPath } from "node:url"

const GENIE_DIR = fileURLToPath(new URL("..", import.meta.url))

async function runGenieScript(script, input, args = []) {
  const proc = Bun.spawn({
    cmd: ["python3", `${GENIE_DIR}/router/${script}`, ...args],
    stdin: input ? "pipe" : "ignore",
    stdout: "pipe",
    stderr: "pipe",
  })
  if (input) {
    proc.stdin.write(input)
    proc.stdin.end()
  }
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ])
  return { stdout: stdout.trim(), stderr: stderr.trim(), exitCode }
}

function lastUserText(messages) {
  if (!Array.isArray(messages)) return ""
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i]
    if (message?.info?.role !== "user") continue
    const text = (message.parts || [])
      .filter((part) => part?.type === "text" && typeof part.text === "string" && !part.synthetic)
      .map((part) => part.text)
      .join("\n")
      .trim()
    if (text) return text
  }
  return ""
}

// Both plugin APIs are exported from one module: opencode-ai 1.x (1.19 strict)
// calls `server` and rejects a module without it; @opencode/cli 2.x calls
// `setup`. Each ignores the other key (probed on 1.19.3 and 2.1.2).

// One hook call: the router's additionalContext already carries the turn's
// prefs (prefs.py); `--host codex` renders them every turn.
async function routerContext(text, cwd, sessionID) {
  const hookInput = JSON.stringify({ prompt: text, cwd, session_id: sessionID })
  const routerResult = await runGenieScript("genie_router.py", hookInput, ["--host", "codex"])
  try {
    return JSON.parse(routerResult.stdout).hookSpecificOutput?.additionalContext ?? ""
  } catch {
    return "" // Unparseable router output is dropped; the turn runs without it.
  }
}

// Throws `genie-guard: ...` to block; any other failure fails open.
async function guardTool(tool, input, cwd) {
  if (!["bash", "write", "edit", "patch"].includes(tool)) return
  try {
    const toolInput = input && typeof input === "object" ? { ...input } : input
    if (toolInput?.filePath && !toolInput.file_path) toolInput.file_path = toolInput.filePath
    const guardResult = await runGenieScript("guard_dangerous.py", JSON.stringify({ tool_input: toolInput, cwd }))
    if (!guardResult.stdout) return

    let guardData
    try {
      guardData = JSON.parse(guardResult.stdout)
    } catch {
      return
    }
    const decision = guardData.hookSpecificOutput
    if (decision?.permissionDecision === "deny") {
      throw new Error(`genie-guard: ${decision.permissionDecisionReason}`)
    }
  } catch (error) {
    if (error.message?.includes("genie-guard")) throw error
    // Guard failures fail open rather than breaking ordinary tool use.
  }
}

// V1 hooks (1.x). chat.message carries the user's text; system.transform has
// no messages, so the router runs once per user message and is replayed each step.
async function server({ directory } = {}) {
  const cwd = directory ?? process.cwd()
  const injected = new Map() // sessionID -> router context for the latest user message

  return {
    "chat.message": async (input, output) => {
      const sessionID = input?.sessionID
      if (!sessionID) return
      try {
        const text = lastUserText([{ info: { role: "user" }, parts: output?.parts }])
        if (!text) return
        const context = await routerContext(text, cwd, sessionID)
        if (injected.size >= 200) injected.delete(injected.keys().next().value)
        injected.set(sessionID, context)
      } catch {
        // Routing and preferences fail open; neither may block a model turn.
      }
    },

    "experimental.chat.system.transform": async (input, output) => {
      const context = injected.get(input?.sessionID)
      if (context && Array.isArray(output?.system)) output.system.push(context)
    },

    "tool.execute.before": async (input, output) => {
      await guardTool(input?.tool, output?.args, cwd)
    },
  }
}

// V2 hooks (2.x): the context event carries messages and system blocks.
async function setup(ctx) {
  const cwd = () => ctx.location?.directory ?? process.cwd()

  await ctx.session.hook("context", async (event) => {
    if (!event.sessionID) return
    try {
      const text = lastUserText(event.messages)
      if (!text) return
      const context = await routerContext(text, cwd(), event.sessionID)
      if (context) event.system.push({ type: "text", text: context })
    } catch {
      // Routing and preferences fail open; neither may block a model turn.
    }
  })

  await ctx.tool.hook("execute.before", async (event) => {
    await guardTool(event.tool, event.input, cwd())
  })
}

export default { id: "genie-harness", server, setup }
