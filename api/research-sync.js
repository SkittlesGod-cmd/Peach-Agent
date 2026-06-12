// Receives a research snapshot from the local daemon and stores it in Vercel KV.
// Authenticated with RESEARCH_SYNC_TOKEN environment variable.

import { kv } from '@vercel/kv';

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

  const token = process.env.RESEARCH_SYNC_TOKEN;
  if (!token || req.headers['x-sync-token'] !== token) {
    return res.status(401).json({ error: 'unauthorized' });
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return res.status(400).json({ error: 'invalid_json' });
  }

  try {
    await kv.set('research_snapshot', body);
    return res.status(200).json({ ok: true, total: body.total ?? 0 });
  } catch (err) {
    return res.status(500).json({ error: String(err) });
  }
}
