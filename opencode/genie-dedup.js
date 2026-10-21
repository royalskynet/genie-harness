import { dedupParts } from './dedup-core.js';

// Both plugin APIs are exported from one module: opencode-ai 1.x (1.19 strict)
// calls `server` and rejects a module without it; @opencode/cli 2.x calls
// `setup`. Each ignores the other key (probed on 1.19.3 and 2.1.2).
const dedup = (messages) => {
  if (process.env.GENIE_DEDUP_ENABLED === '0') return;
  try {
    dedupParts(messages);
  } catch {
    // Fail open: the model sees the history verbatim.
  }
};

export default {
  id: 'genie-dedup',
  // V1 (1.x)
  server: async () => ({
    'experimental.chat.messages.transform': async (_input, output) => dedup(output?.messages),
  }),
  // V2 (2.x)
  async setup(ctx) {
    await ctx.session.hook('context', async (event) => dedup(event?.messages));
  },
};
