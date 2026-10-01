// Cloudflare Worker: keeps a stored copy of Sidewalk Film Center's public
// showtimes pages (https://sidewalkfest.com/cinema/) and serves that copy
// to the Python fetcher.
//
// Why this exists: Sidewalk's site sits behind Cloudflare, which answers
// GitHub Actions' runners with a JavaScript challenge ("Just a moment...")
// that only a real browser can pass. Simply proxying the request through
// a Worker stopped helping in Sept 2026: the challenge was still issued
// whenever a GitHub runner was the one calling the Worker, while the same
// Worker called from a home IP got the real page.
//
// So the Worker no longer fetches Sidewalk on demand. A Cron Trigger runs
// `scheduled()` below, which scrapes every page with no caller involved
// and stores the result in KV. `fetch()` only ever reads from KV, so the
// GitHub runner never causes a request to Sidewalk at all.
//
// Setup (Cloudflare dashboard):
//   1. Create a KV namespace and bind it to this Worker as SIDEWALK_KV.
//   2. Add a Cron Trigger (e.g. `30 3,9,15,21 * * *`, half an hour before
//      each GitHub Actions run in .github/workflows/update.yml).
//   3. Paste this file's contents into the Worker and deploy.
//
// Endpoints:
//   /            stored page 1 (same HTML Sidewalk served)
//   /?_paged=N   stored page N
//   /status      JSON describing the stored copy and the latest attempt

const TARGET = "https://sidewalkfest.com/cinema/";

const MAX_PAGES = 30; // safety ceiling; the real page count is usually ~5
const PAGE_DELAY_MS = 500;

const SNAPSHOT_KEY = "snapshot";
const LAST_ATTEMPT_KEY = "last_attempt";

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
};

async function fetchSidewalkPage(page) {
  const target = new URL(TARGET);
  if (page > 1) {
    target.searchParams.set("_paged", String(page));
  }

  const upstream = await fetch(target.toString(), { headers: BROWSER_HEADERS });
  const body = await upstream.text();

  // A challenge page can come back with any status, so also require the
  // listing markup the Python parser depends on.
  if (upstream.status !== 200 || !body.includes('class="fwpl-result ')) {
    const mitigated = upstream.headers.get("cf-mitigated") || "none";
    throw new Error(
      `page ${page}: status ${upstream.status}, cf-mitigated ${mitigated}, ` +
        `cf-ray ${upstream.headers.get("cf-ray") || "?"}`
    );
  }

  return body;
}

async function refreshSnapshot(env) {
  const attempt = { attempted_at: new Date().toISOString(), ok: false };

  try {
    const pages = [await fetchSidewalkPage(1)];

    const match = pages[0].match(/"total_pages":(\d+)/);
    const totalPages = Math.min(match ? Number(match[1]) : 1, MAX_PAGES);

    for (let page = 2; page <= totalPages; page++) {
      await new Promise((resolve) => setTimeout(resolve, PAGE_DELAY_MS));
      pages.push(await fetchSidewalkPage(page));
    }

    // Only replace the stored copy once every page succeeded, so a failed
    // run leaves the last good copy in place.
    await env.SIDEWALK_KV.put(
      SNAPSHOT_KEY,
      JSON.stringify({ fetched_at: attempt.attempted_at, pages })
    );

    attempt.ok = true;
    attempt.pages = pages.length;
  } catch (err) {
    attempt.error = String(err && err.message ? err.message : err);
  }

  await env.SIDEWALK_KV.put(LAST_ATTEMPT_KEY, JSON.stringify(attempt));
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(refreshSnapshot(env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    const snapshot = await env.SIDEWALK_KV.get(SNAPSHOT_KEY, "json");

    if (url.pathname === "/status") {
      const lastAttempt = await env.SIDEWALK_KV.get(LAST_ATTEMPT_KEY, "json");
      return Response.json({
        stored_fetched_at: snapshot ? snapshot.fetched_at : null,
        stored_pages: snapshot ? snapshot.pages.length : 0,
        last_attempt: lastAttempt,
      });
    }

    if (!snapshot) {
      return new Response("No stored Sidewalk pages yet.", { status: 503 });
    }

    const page = Number(url.searchParams.get("_paged") || "1");
    const body = snapshot.pages[page - 1];

    if (!body) {
      return new Response(`No stored page ${page}.`, { status: 404 });
    }

    return new Response(body, {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "X-Fetched-At": snapshot.fetched_at,
      },
    });
  },
};
