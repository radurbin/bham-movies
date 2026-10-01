// Cloudflare Worker: returns the live seat map (which seats are taken)
// for one AMC showtime, for the hover tooltip in docs/index.html.
//
// Why this exists: AMC's API doesn't give this vendor key any seating
// endpoint (every showtime links to /seating-layouts/..., but it 404s),
// and AMC's own website refuses anything that isn't a real browser. The
// two third-party sources used before this (walzr.com, then SeatDrop's
// backend) both stopped being usable. Fandango sells tickets for the same
// AMC showtimes and its checkout pages load their seat map as JSON, which
// is what this Worker reads.
//
// How a lookup works:
//   1. Fetch Fandango's showtime listing for that theater and date, and
//      pick the showtime(s) starting at the same time.
//   2. Get an anonymous checkout token (loading any seat-selection page
//      hands out a session; one more request turns it into a token that
//      lasts 20 minutes and works for every showtime).
//   3. Fetch the seat map. Fandango's ticket codes embed AMC's own
//      showtime ID (e.g. "TICKET-RS-147495013-ADULT"), so the match is
//      confirmed rather than assumed from the start time.
//
// None of this is a documented API. If Fandango changes it, lookups fail
// with a JSON error and the frontend falls back to linking to AMC's own
// seat page.
//
// Request:
//   /seats?theater_id=4101&showtime_id=147495013&datetime=2026-10-01T22:30:00
// (theater_id, showtime_id and datetime exactly as they appear in
// docs/movies.json)
//
// Deploy via the Cloudflare dashboard: paste this file's contents into
// the Worker and deploy. No bindings or triggers are needed.

// AMC theatre ID -> Fandango theater code.
const FANDANGO_THEATERS = {
  4101: "AAHLN", // AMC Summit 16
  4103: "AASVB", // AMC Patton Creek 15
  4105: "AARCA", // AMC Vestavia Hills 10
};

// Browsers only let these pages read the response.
const ALLOWED_ORIGINS = [
  "https://radurbin.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

const LISTING_TTL_MS = 30 * 60 * 1000;
const SEATMAP_TTL_MS = 2 * 60 * 1000;
const TOKEN_SAFETY_MS = 60 * 1000;

// Kept in memory only. A Worker instance is reused for many requests but
// can be discarded at any time, in which case these are simply refetched.
const listingCache = new Map(); // "tid|date" -> { at, showtimes }
const seatmapCache = new Map(); // AMC showtime id -> { at, payload }
let cachedToken = null; // { value, expiresAt }

class LookupError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// --------------------------------------------------
// Fandango requests
// --------------------------------------------------

async function fetchListing(tid, date) {
  const key = `${tid}|${date}`;
  const cached = listingCache.get(key);
  if (cached && Date.now() - cached.at < LISTING_TTL_MS) {
    return cached.showtimes;
  }

  const response = await fetch(
    `https://www.fandango.com/napi/theaterMovieShowtimes/${tid}` +
      `?startDate=${date}&isdesktop=true&partnerRestrictedTicketing=`,
    {
      headers: {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        // The listing answers 403 without a fandango.com Referer.
        "Referer": "https://www.fandango.com/",
      },
    }
  );
  if (!response.ok) {
    throw new LookupError(502, `Fandango listing returned ${response.status}`);
  }

  const data = await response.json();
  const showtimes = [];
  for (const movie of data?.viewModel?.movies || []) {
    for (const variant of movie.variants || []) {
      for (const group of variant.amenityGroups || []) {
        for (const show of group.showtimes || []) {
          // ticketingDate looks like "2026-10-01+22:30"
          const [showDate, showTime] = String(show.ticketingDate || "").split("+");
          if (!show.id || !showDate || !showTime) continue;
          showtimes.push({
            id: show.id,
            movieId: movie.id,
            title: movie.title,
            date: showDate,
            time: showTime,
          });
        }
      }
    }
  }

  listingCache.set(key, { at: Date.now(), showtimes });
  return showtimes;
}

async function getToken(tid, show) {
  if (cachedToken && Date.now() < cachedToken.expiresAt - TOKEN_SAFETY_MS) {
    return cachedToken.value;
  }

  // Any valid seat-selection page sets the two cookies the token
  // request needs.
  const page = await fetch(
    "https://tickets.fandango.com/mobileexpress/seatselection" +
      `?row_count=${show.id}&mid=${show.movieId}&chainCode=AMC` +
      `&sdate=${encodeURIComponent(`${show.date} ${show.time}`)}&tid=${tid}`,
    {
      headers: { "User-Agent": USER_AGENT, "Accept": "text/html" },
      redirect: "manual",
    }
  );
  if (page.status !== 200) {
    throw new LookupError(502, `Fandango seat page returned ${page.status}`);
  }

  const cookies = {};
  for (const line of page.headers.getSetCookie()) {
    const pair = line.split(";")[0];
    const eq = pair.indexOf("=");
    if (eq > 0) cookies[pair.slice(0, eq).trim()] = pair.slice(eq + 1);
  }
  const csrf = cookies["_csrf"];
  const session = cookies["ASP.NET_SessionId"];
  if (!csrf || !session) {
    throw new LookupError(502, "Fandango seat page did not set a session");
  }

  const response = await fetch("https://tickets.fandango.com/token", {
    method: "POST",
    headers: {
      "User-Agent": USER_AGENT,
      "Accept": "application/json",
      "X-CSRF-Token": csrf,
      "Cookie": `_csrf=${csrf}; ASP.NET_SessionId=${session}`,
    },
  });
  if (!response.ok) {
    throw new LookupError(502, `Fandango token request returned ${response.status}`);
  }

  const data = await response.json();
  if (!data.access_token) {
    throw new LookupError(502, "Fandango token response had no token");
  }

  cachedToken = {
    value: data.access_token,
    expiresAt: Date.now() + (Number(data.expires_in) || 1200) * 1000,
  };
  return cachedToken.value;
}

async function fetchSeatMap(tid, show) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const token = await getToken(tid, show);
    const response = await fetch(
      `https://tickets.fandango.com/checkoutapi/showtimes/v2/${show.id}/seat-map/`,
      {
        headers: {
          "User-Agent": USER_AGENT,
          "Accept": "application/json",
          "Authorization": token,
        },
      }
    );

    if (response.status === 401 && attempt === 0) {
      cachedToken = null; // expired early; get a fresh one and retry once
      continue;
    }
    if (!response.ok) {
      throw new LookupError(502, `Fandango seat map returned ${response.status}`);
    }

    const data = await response.json();
    if (!data || !data.data || !Array.isArray(data.data.seats)) {
      throw new LookupError(502, "Fandango seat map had no seats");
    }
    return data.data;
  }
}

// --------------------------------------------------
// Matching and shaping
// --------------------------------------------------

// Fandango's ticket codes carry AMC's showtime ID between dashes.
function isAmcShowtime(seatMap, amcShowtimeId) {
  const needle = `-${amcShowtimeId}-`;
  for (const area of seatMap.areas || []) {
    for (const ticket of area.ticketInfo || []) {
      if (String(ticket.code || "").includes(needle)) return true;
    }
  }
  return false;
}

// Turns Fandango's pixel-positioned seats into rows of equal-width
// cells, with nulls for aisles and gaps, ordered screen-first.
function buildRows(seats) {
  const byRow = new Map();
  for (const seat of seats) {
    if (!byRow.has(seat.row)) byRow.set(seat.row, []);
    byRow.get(seat.row).push(seat);
  }

  // Column width = the smallest gap between neighbouring seats anywhere.
  let pitch = Infinity;
  for (const rowSeats of byRow.values()) {
    rowSeats.sort((a, b) => a.x - b.x);
    for (let i = 1; i < rowSeats.length; i++) {
      const gap = rowSeats[i].x - rowSeats[i - 1].x;
      if (gap > 1 && gap < pitch) pitch = gap;
    }
  }
  if (!isFinite(pitch)) pitch = 1;

  const minX = Math.min(...seats.map((s) => s.x));

  const rows = [];
  for (const rowSeats of byRow.values()) {
    const cells = [];
    const labelCounts = {};
    for (const seat of rowSeats) {
      const column = Math.round((seat.x - minX) / pitch);
      while (cells.length < column) cells.push(null);
      cells.push({
        name: seat.id,
        available: seat.status === "A",
        type: seat.type || "standard",
      });

      const letters = String(seat.id).replace(/\d+$/, "");
      labelCounts[letters] = (labelCounts[letters] || 0) + 1;
    }

    // Wheelchair spaces are named like "WC2" inside a lettered row, so
    // label the row by whichever prefix most of its seats share.
    const label = Object.keys(labelCounts).sort(
      (a, b) => labelCounts[b] - labelCounts[a]
    )[0];

    rows.push({ label: label || "", y: rowSeats[0].y, seats: cells });
  }

  // Fandango draws the screen at the top, so smallest y is the front row.
  rows.sort((a, b) => a.y - b.y);
  return rows.map(({ label, seats: cells }) => ({ label, seats: cells }));
}

function previousDate(date) {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

async function lookup(theaterId, showtimeId, datetime) {
  const cached = seatmapCache.get(showtimeId);
  if (cached && Date.now() - cached.at < SEATMAP_TTL_MS) {
    return cached.payload;
  }

  const tid = FANDANGO_THEATERS[theaterId];
  const date = datetime.slice(0, 10);
  const time = datetime.slice(11, 16);

  // After-midnight showtimes may be listed under the previous day's
  // schedule, so look there too.
  const listings = [await fetchListing(tid, date)];
  if (time < "05:00") {
    listings.push(await fetchListing(tid, previousDate(date)));
  }

  const candidates = [];
  const seen = new Set();
  for (const show of listings.flat()) {
    if (show.date === date && show.time === time && !seen.has(show.id)) {
      seen.add(show.id);
      candidates.push(show);
    }
  }
  if (candidates.length === 0) {
    throw new LookupError(404, "Fandango lists no showtime at that time");
  }

  // Two films can start at the same minute, so check each candidate
  // until one carries this AMC showtime ID.
  for (const show of candidates) {
    const seatMap = await fetchSeatMap(tid, show);
    if (!isAmcShowtime(seatMap, showtimeId)) continue;

    const payload = {
      showtime_id: Number(showtimeId),
      theater: seatMap.theaterName || null,
      auditorium: seatMap.auditoriumId ?? null,
      available: seatMap.totalAvailableSeatCount ?? null,
      total: seatMap.totalSeatCount ?? null,
      fetched_at: new Date().toISOString(),
      rows: buildRows(seatMap.seats),
    };

    if (seatmapCache.size > 500) seatmapCache.clear();
    seatmapCache.set(showtimeId, { at: Date.now(), payload });
    return payload;
  }

  throw new LookupError(404, "No Fandango showtime matched that AMC showtime");
}

// --------------------------------------------------
// HTTP
// --------------------------------------------------

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  return origin && ALLOWED_ORIGINS.includes(origin)
    ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" }
    : {};
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

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (request.method !== "GET" || url.pathname !== "/seats") {
      return json(request, 404, { error: "Not found" });
    }

    const theaterId = url.searchParams.get("theater_id") || "";
    const showtimeId = url.searchParams.get("showtime_id") || "";
    const datetime = url.searchParams.get("datetime") || "";

    if (
      !FANDANGO_THEATERS[theaterId] ||
      !/^\d{1,12}$/.test(showtimeId) ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(datetime)
    ) {
      return json(request, 400, {
        error: "Expected theater_id, showtime_id and datetime as in movies.json",
      });
    }

    try {
      return json(request, 200, await lookup(theaterId, showtimeId, datetime));
    } catch (err) {
      const status = err instanceof LookupError ? err.status : 502;
      return json(request, status, { error: String(err.message || err) });
    }
  },
};
