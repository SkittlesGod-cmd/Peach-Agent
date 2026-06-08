// Peach LLM proxy — forwards requests to OpenRouter.
// The real API key lives only in Vercel environment variables, never in git.

async function readBody(req) {
  // req.body is pre-parsed when Vercel's micro layer is active; fall back to
  // streaming for plain Node.js runtimes.
  if (req.body !== undefined) return req.body;
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', chunk => { raw += chunk; });
    req.on('end', () => {
      try { resolve(JSON.parse(raw)); }
      catch { reject(new Error('invalid_json')); }
    });
    req.on('error', reject);
  });
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  const key = process.env.OPENROUTER_API_KEY;
  if (!key) {
    return res.status(503).json({ error: 'service_unavailable' });
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return res.status(400).json({ error: 'invalid_json' });
  }

  let upstream, data;
  try {
    upstream = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://peach-agent.vercel.app',
        'X-Title': 'Peach',
      },
      body: JSON.stringify(body),
    });
    data = await upstream.json();
  } catch (err) {
    return res.status(502).json({ error: 'upstream_error', detail: String(err) });
  }

  return res.status(upstream.status).json(data);
}
