import { dedupParts } from './dedup-core.js';

// Only the plugin is exported: opencode runs every exported function as one.
export const GenieDedup = async () => ({
  'experimental.chat.messages.transform': async (_input, output) => {
    if (process.env.GENIE_DEDUP_ENABLED === '0') return;
    try {
      dedupParts(output?.messages);
    } catch {
      // fail-open: the model sees the history verbatim
    }
  },
});
