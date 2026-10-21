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

// opencode 1.19 loads only `export default { id, server }`; it rejects the V2
// `{ id, setup }` shape ("must default export an object with server()").
// chat.message carries the user's text; system.transform has no messages, so
// the router output is computed once per user message and replayed each step.
export default {
  id: "genie-harness",
  server: async ({ directory } = {}) => {
    const injected = new Map() // sessionID -> system strings for the latest user message

    return {
      "chat.message": async (input, output) => {
        const sessionID = input?.sessionID
        if (!sessionID) return
        try {
          const text = lastUserText([{ info: { role: "user" }, parts: output?.parts }])
          if (!text) return
          // One hook call: the router's additionalContext already carries the
          // turn's prefs (prefs.py); `--host codex` renders them every turn.
          const hookInput = JSON.stringify({ prompt: text, cwd: directory ?? process.cwd(), session_id: sessionID })
          const routerResult = await runGenieScript("genie_router.py", hookInput, ["--host", "codex"])
          let context = ""
          try {
            context = JSON.parse(routerResult.stdout).hookSpecificOutput?.additionalContext ?? ""
          } catch {
            // Unparseable router output is dropped; the turn runs without it.
          }
          const system = context ? [context] : []
          if (injected.size >= 200) injected.delete(injected.keys().next().value)
          injected.set(sessionID, system)
        } catch {
          // Routing and preferences fail open; neither may block a model turn.
        }
      },

      "experimental.chat.system.transform": async (input, output) => {
        const system = injected.get(input?.sessionID)
        if (system?.length && Array.isArray(output?.system)) output.system.push(...system)
      },

      "tool.execute.before": async (input, output) => {
        if (!["bash", "write", "edit", "patch"].includes(input?.tool)) return
        try {
          const args = output?.args
          const toolInput = args && typeof args === "object" ? { ...args } : args
          if (toolInput?.filePath && !toolInput.file_path) toolInput.file_path = toolInput.filePath
          const guardInput = JSON.stringify({ tool_input: toolInput, cwd: directory ?? process.cwd() })
          const guardResult = await runGenieScript("guard_dangerous.py", guardInput)
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
      },
    }
  },
}
