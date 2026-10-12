import { dedupParts } from './dedup-core.js';

export default {
  id: 'genie-dedup',
  async setup(ctx) {
    await ctx.session.hook('context', async (event) => {
    if (process.env.GENIE_DEDUP_ENABLED === '0') return;
    try {
      dedupParts(event?.messages);
    } catch {
      // Fail open: the model sees the history verbatim.
    }
    });
  },
};
