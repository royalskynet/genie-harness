import { fileURLToPath } from "node:url"

const GENIE_DIR = fileURLToPath(new URL("..", import.meta.url))

async function runGenieScript(script, input) {
  const proc = Bun.spawn({
    cmd: ["python3", `${GENIE_DIR}/router/${script}`],
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

export default {
  id: "genie-harness",
  async setup(ctx) {
    await ctx.session.hook("context", async (event) => {
      if (!event.sessionID) return
      try {
        const text = lastUserText(event.messages)
        if (!text) return

        const routerResult = await runGenieScript("genie_router.py", text)
        if (routerResult.stdout) {
          event.system.push({ type: "text", text: routerResult.stdout })
        }

        const prefsResult = await runGenieScript("prefs_hook.py", JSON.stringify({ prompt: text }))
        if (prefsResult.stdout) {
          try {
            const prefsData = JSON.parse(prefsResult.stdout)
            if (prefsData.hookSpecificOutput?.additionalContext) {
              event.system.push({ type: "text", text: prefsData.hookSpecificOutput.additionalContext })
            }
          } catch {
            // Invalid preference output is ignored; routing still applies.
          }
        }
      } catch {
        // Routing and preferences fail open; neither may block a model turn.
      }
    })

    await ctx.tool.hook("execute.before", async (event) => {
      if (!["bash", "write", "edit", "patch"].includes(event.tool)) return
      try {
        const toolInput = event.input && typeof event.input === "object" ? { ...event.input } : event.input
        if (toolInput?.filePath && !toolInput.file_path) toolInput.file_path = toolInput.filePath
        const guardInput = JSON.stringify({ tool_input: toolInput, cwd: ctx.location.directory })
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
    })
  },
}
