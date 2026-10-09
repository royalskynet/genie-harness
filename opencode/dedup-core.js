/**
 * Zero-token context trimming for opencode, over the
 * `experimental.chat.messages.transform` payload ({ info, parts }[]).
 * Design borrowed from opencode-dynamic-context-pruning (AGPL, not copied):
 *
 *   1. dedup: the same tool with the same arguments ran again later → the
 *      older output is replaced by a marker; the newest stays verbatim.
 *   2. failed calls: `errorTurns` user turns after a call failed, its large
 *      string arguments (a whole file passed to a write that errored) are
 *      replaced; the error message itself stays.
 *
 * Deterministic and idempotent: the same history always comes out the same,
 * so the prompt-cache prefix only moves when a new duplicate appears. User and
 * assistant text is never touched. Touched parts are swapped for copies.
 */
export const DEFAULTS = { minChars: 200, errorTurns: 4 };

function stable(v) {
  if (Array.isArray(v)) return `[${v.map(stable).join(',')}]`;
  if (v && typeof v === 'object') {
    return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${stable(v[k])}`).join(',')}}`;
  }
  return JSON.stringify(v) ?? 'null';
}

export function dedupParts(messages, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const out = { deduped: 0, purged: 0 };
  if (!Array.isArray(messages)) return out;

  const sites = [];
  messages.forEach((m, mi) => (m?.parts ?? []).forEach((p, pi) => {
    if (p?.type === 'tool' && p.state) sites.push({ mi, pi, p });
  }));

  const latest = new Map();
  for (const s of sites) {
    if (s.p.state.status !== 'completed') continue;
    s.key = `${s.p.tool}\u0000${stable(s.p.state.input ?? {})}`;
    latest.set(s.key, s);
  }
  for (const s of sites) {
    if (!s.key || latest.get(s.key) === s) continue;
    const output = s.p.state.output;
    if (typeof output !== 'string' || output.length < o.minChars) continue;
    messages[s.mi].parts[s.pi] = {
      ...s.p,
      state: { ...s.p.state, output: `[genie-dedup: ${output.length} chars dropped; the same ${s.p.tool} call ran again later and its newer output is kept]` },
    };
    out.deduped += output.length;
  }

  // user turns after each message index
  const userAfter = new Array(messages.length).fill(0);
  for (let i = messages.length - 2; i >= 0; i--) {
    userAfter[i] = userAfter[i + 1] + (messages[i + 1]?.info?.role === 'user' ? 1 : 0);
  }
  for (const s of sites) {
    if (s.p.state.status !== 'error' || userAfter[s.mi] < o.errorTurns) continue;
    const input = s.p.state.input;
    if (!input || typeof input !== 'object') continue;
    let changed = false;
    const slim = { ...input };
    for (const [k, v] of Object.entries(input)) {
      if (typeof v === 'string' && v.length >= o.minChars) {
        slim[k] = `[genie-dedup: ${v.length} chars of a failed call's input dropped]`;
        out.purged += v.length;
        changed = true;
      }
    }
    if (changed) messages[s.mi].parts[s.pi] = { ...s.p, state: { ...s.p.state, input: slim } };
  }
  return out;
}
