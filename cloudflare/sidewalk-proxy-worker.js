// Cloudflare Worker: keeps a stored copy of Sidewalk Film Center's public
// schedule page (https://www.sidewalkfest.com/cinema/now-playing) and
// serves that copy to the Python fetcher.
//
// Since Nov 4, 2026 Sidewalk's site is a Next.js app built by Elevent. The
// schedule page embeds every upcoming showtime (about six weeks) as JSON in
// a single page, so there is no paging any more. The old WordPress address
// (sidewalkfest.com/cinema/) now redirects to a page with no showtimes.
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
// Status (Nov 9, 2026): not in use. The pipeline reads Sidewalk's site
// directly, and this Worker's Cron Trigger has been deleted. Kept as the
// fallback in case GitHub's runners get challenged again; see README.
//
// Setup (Cloudflare dashboard):
//   1. Create a KV namespace and bind it to this Worker as SIDEWALK_KV.
//   2. Add a Cron Trigger (e.g. `30 3,9,15,21 * * *`, half an hour before
//      each GitHub Actions run in .github/workflows/update.yml).
//   3. Paste this file's contents into the Worker and deploy.
//
// Endpoints:
//   /            the stored schedule page (same HTML Sidewalk served)
//   /status      JSON describing the stored copy and the latest attempt

const TARGET = "https://www.sidewalkfest.com/cinema/now-playing?view=list";

// The schedule data the Python fetcher reads. In the raw HTML it sits
// inside a JavaScript string, so its quotes are backslash-escaped.
const SCHEDULE_MARKER = '\\"initialShowtimes\\":';

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

async function fetchSchedulePage() {
  const upstream = await fetch(TARGET, { headers: BROWSER_HEADERS });
  const body = await upstream.text();

  // A challenge page, a redirect to a page without showtimes, or another
  // redesign can all come back as 200, so also require the schedule data.
  if (upstream.status !== 200 || !body.includes(SCHEDULE_MARKER)) {
    const mitigated = upstream.headers.get("cf-mitigated") || "none";
    throw new Error(
      `status ${upstream.status}, schedule data ` +
        `${body.includes(SCHEDULE_MARKER) ? "present" : "missing"}, ` +
        `final URL ${upstream.url}, cf-mitigated ${mitigated}, ` +
        `cf-ray ${upstream.headers.get("cf-ray") || "?"}`
    );
  }

  return body;
}

async function refreshSnapshot(env) {
  const attempt = { attempted_at: new Date().toISOString(), ok: false };

  try {
    // Stored as a one-item list, the same shape as when the old site
    // needed several pages.
    const pages = [await fetchSchedulePage()];

    // Only replace the stored copy on success, so a failed run leaves
    // the last good copy in place.
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

    return new Response(snapshot.pages[0], {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "X-Fetched-At": snapshot.fetched_at,
      },
    });
  },
};
