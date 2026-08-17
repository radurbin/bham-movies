// Cloudflare Worker: proxies requests to Sidewalk Film Center's public
// showtimes page (https://sidewalkfest.com/cinema/).
//
// Why this exists: GitHub Actions' runner IPs get a flat 403 from
// Sidewalk's site (something in front of it -- likely Cloudflare/WAF --
// distrusts known cloud/CI IP ranges), even though the identical request
// with the identical headers works fine from a home IP. Routing the
// fetch through this Worker instead makes the request originate from
// Cloudflare's own edge network rather than GitHub's datacenter IPs.
//
// Deploy via the Cloudflare dashboard: Workers & Pages -> Create ->
// Create Worker -> paste this file's contents in -> Save and Deploy.
// The resulting URL (https://<name>.<subdomain>.workers.dev) is what
// fetchers/sidewalk.py's SIDEWALK_CINEMA_URL should point to.

const TARGET = "https://sidewalkfest.com/cinema/";

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = new URL(TARGET);

    // Forward Sidewalk's own pagination param through unchanged so the
    // Python fetcher doesn't need to know anything changed.
    const page = url.searchParams.get("_paged");
    if (page) {
      target.searchParams.set("_paged", page);
    }

    const upstream = await fetch(target.toString(), {
      headers: BROWSER_HEADERS,
    });

    const body = await upstream.text();

    return new Response(body, {
      status: upstream.status,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  },
};
