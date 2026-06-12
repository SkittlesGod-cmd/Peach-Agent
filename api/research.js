// Research dashboard data — reads snapshot from Vercel KV.
// Set up: Vercel dashboard → Storage → Create KV database → connect to this project.

import { kv } from '@vercel/kv';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const data = await kv.get('research_snapshot');
    if (!data) {
      return res.status(200).json({
        professors: [],
        stats: {},
        total: 0,
        updated_at: null,
      });
    }
    return res.status(200).json(data);
  } catch (err) {
    return res.status(500).json({ error: String(err) });
  }
}
