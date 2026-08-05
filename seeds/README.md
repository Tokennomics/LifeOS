# City seed packs

A seed pack is a list of venue websites for one city. Loading one subscribes to every
venue's calendar in a single call, so somebody arriving in a city that already has a pack
gets a populated weekend on first open instead of an empty list and an invitation to do
data entry.

**There are no real packs committed here yet, and that is deliberate.** The URLs have to be
checked by someone who can actually reach them — a pack full of guessed addresses is a list
of 404s wearing a hat, and it would be worse than an empty directory because it would look
like the feature is broken rather than unseeded. `example.json` shows the format using
`example.com` addresses that are obviously not real.

## Making a real pack

1. Collect venue **websites** — not feed URLs. `POST /v1/feeds/discover` finds the feed, and
   the whole point is that nobody knows their favourite bar's `.ics` link.
2. Put them in `seeds/<city>.json` (lowercase, hyphens for spaces: `lisbon.json`,
   `new-york.json`).
3. `POST /v1/feeds/seeds/lisbon` subscribes to all of them. Add `{"sync": true}` to pull
   them straight away and see what actually arrives.
4. **Check what came back.** `GET /v1/feeds` shows each feed's `last_status`. Venues that
   fetched nothing are the ones to drop — a pack is only worth committing once its entries
   have been seen to produce events.

## Format

```json
{
  "city": "Lisbon",
  "note": "optional, for whoever maintains this",
  "venues": [
    {"url": "https://example.com/", "venue": "Example Club", "topic": "techno"}
  ]
}
```

`url` is required and must be http(s). `venue` and `topic` are optional — `venue` defaults
to the host, and `topic` feeds interest matching in the weekend digest and discover feed.

## What loading a pack does and does not do

It **subscribes**, exactly as if you had added each venue by hand: the `venue_feed` records
are owner-scoped, and the events they produce are public and system-owned, deduped globally
on `(feed url, item uid)`. Loading the same pack twice is a no-op, and two people loading
the same pack does not double the city.

It does **not** fetch anything unless you ask for `sync`, and it does not remove feeds that
have dropped out of a pack — unsubscribing is a decision, not a side effect of an update.
