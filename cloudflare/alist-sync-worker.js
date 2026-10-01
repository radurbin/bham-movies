// Cloudflare Worker: stores the A-List plan (the posters picked in
// docs/index.html's "A-List Plan Mode") so it follows you between
// devices. The page keeps its own copy in localStorage and uses this as
// the shared one.
//
// The site is public and has no login, so access is gated by a single
// sync code: a secret set on the Worker, typed once into each device.
// Requests without it get 401.
//
// Setup (Cloudflare dashboard):
//   1. Create a KV namespace and bind it to this Worker as ALIST_KV.
//   2. Add a secret named SYNC_CODE (Settings -> Variables and Secrets,
//      type "Secret") holding a long random phrase.
//   3. Paste this file's contents into the Worker and deploy.
//
// Endpoints (both need the header `Authorization: Bearer <sync code>`):
//   GET /plan   -> { selections: [...] | null, updated_at }
//   PUT /plan   <- { selections: [...] }

// Browsers only let these pages call the Worker.
const ALLOWED_ORIGINS = [
  "https://radurbin.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

const PLAN_KEY = "plan";

const MAX_BODY_BYTES = 100 * 1024;
const MAX_SELECTIONS = 2000;
const MAX_SELECTION_LENGTH = 300;

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  if (!origin || !ALLOWED_ORIGINS.includes(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(request, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(request),
    },
  });
}

async function sha256(text) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text)
  );
  return Array.from(new Uint8Array(digest));
}

// Compares digests rather than the strings themselves so the time taken
// doesn't reveal how much of a guess was right.
async function isAuthorized(request, env) {
  if (!env.SYNC_CODE) return false;

  const header = request.headers.get("Authorization") || "";
  const given = header.startsWith("Bearer ") ? header.slice(7) : "";

  const [a, b] = await Promise.all([sha256(given), sha256(env.SYNC_CODE)]);

  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }

    if (url.pathname !== "/plan") {
      return json(request, 404, { error: "Not found" });
    }

    if (!(await isAuthorized(request, env))) {
      return json(request, 401, { error: "Wrong or missing sync code" });
    }

    if (request.method === "GET") {
      const stored = await env.ALIST_KV.get(PLAN_KEY, "json");
      return json(request, 200, {
        selections: stored ? stored.selections : null,
        updated_at: stored ? stored.updated_at : null,
      });
    }

    if (request.method === "PUT") {
      const text = await request.text();
      if (text.length > MAX_BODY_BYTES) {
        return json(request, 413, { error: "Plan too large" });
      }

      let selections;
      try {
        selections = JSON.parse(text).selections;
      } catch (err) {
        return json(request, 400, { error: "Body must be JSON" });
      }

      if (
        !Array.isArray(selections) ||
        selections.length > MAX_SELECTIONS ||
        !selections.every(
          (s) => typeof s === "string" && s.length <= MAX_SELECTION_LENGTH
        )
      ) {
        return json(request, 400, { error: "selections must be a list of strings" });
      }

      const stored = { selections, updated_at: new Date().toISOString() };
      await env.ALIST_KV.put(PLAN_KEY, JSON.stringify(stored));
      return json(request, 200, stored);
    }

    return json(request, 405, { error: "Method not allowed" });
  },
};
