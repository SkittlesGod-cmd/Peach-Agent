// Peach email proxy — forwards to Resend.
// RESEND_API_KEY lives only in Vercel environment variables, never in git.

async function readBody(req) {
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

  const key = process.env.RESEND_API_KEY;
  if (!key) {
    return res.status(503).json({ error: 'service_unavailable' });
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return res.status(400).json({ error: 'invalid_json' });
  }

  const { to, subject, html, text } = body;
  if (!to || !subject) {
    return res.status(400).json({ error: 'missing_fields', required: ['to', 'subject'] });
  }

  let upstream, data;
  try {
    upstream = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'Peach <onboarding@resend.dev>',
        to: Array.isArray(to) ? to : [to],
        subject,
        html: html || `<pre style="font-family:monospace;white-space:pre-wrap">${text || ''}</pre>`,
      }),
    });
    data = await upstream.json();
  } catch (err) {
    return res.status(502).json({ error: 'upstream_error', detail: String(err) });
  }

  return res.status(upstream.status).json(data);
}
