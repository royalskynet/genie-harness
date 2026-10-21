import { dedupParts } from './dedup-core.js';

// opencode 1.19 loads only `export default { id, server }`; it rejects the V2
// `{ id, setup }` shape ("must default export an object with server()").
export default {
  id: 'genie-dedup',
  server: async () => ({
    'experimental.chat.messages.transform': async (_input, output) => {
      if (process.env.GENIE_DEDUP_ENABLED === '0') return;
      try {
        dedupParts(output?.messages);
      } catch {
        // Fail open: the model sees the history verbatim.
      }
    },
  }),
};
