"""Minimal client for Buffer's GraphQL API (https://api.buffer.com).

Auth is a personal API key (Bearer) from publish.buffer.com/settings/api.
Video is attached by HOSTED URL — Buffer does not accept file uploads — so the
caller must pass a publicly fetchable video_url (see the /m/<token> media route).

Free-tier rate limits: 100 / 15min, 250 / 24h, 3000 / 30d. Do not loop-test.
"""
import requests

BUFFER_API = "https://api.buffer.com"


class BufferError(Exception):
    pass


def _gql(api_key, query, variables=None):
    try:
        r = requests.post(
            BUFFER_API,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "variables": variables or {}},
            timeout=40,
        )
    except requests.RequestException as e:
        raise BufferError(f"Could not reach Buffer: {e}")

    if r.status_code == 429:
        retry = r.headers.get("Retry-After", "?")
        raise BufferError(
            f"Buffer rate limit hit (retry after {retry}s). Free tier is 100/15min, 250/day."
        )
    try:
        data = r.json()
    except ValueError:
        raise BufferError(f"Buffer returned non-JSON ({r.status_code}): {r.text[:200]}")
    if data.get("errors"):
        raise BufferError("; ".join(e.get("message", "?") for e in data["errors"]))
    return data.get("data") or {}


def list_channels(api_key):
    """[{id, name, service, type}] for the account's first organization."""
    d = _gql(api_key, "query { account { organizations { id } } }")
    orgs = (d.get("account") or {}).get("organizations") or []
    if not orgs:
        return []
    d2 = _gql(
        api_key,
        "query($o:OrganizationId!){ channels(input:{organizationId:$o}){ id name service type } }",
        {"o": orgs[0]["id"]},
    )
    return d2.get("channels") or []


CREATE_POST = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt channelService } }
    ... on MutationError { message }
  }
}
"""


def create_video_post(api_key, channel_id, service, text, video_url,
                      title=None, schedule_iso=None, scheduling="automatic",
                      youtube_category="22"):
    """Queue one video post to a single Buffer channel.

    mode: addToQueue (next free slot) unless schedule_iso is given (customScheduled).
    scheduling: 'automatic' (Buffer publishes) or 'notification' (reminds you).
    Per-service metadata sets Instagram Reels / the YouTube title.
    """
    video = {"url": video_url}
    if title:
        video["metadata"] = {"title": title[:100]}

    metadata = {}
    if service == "instagram":
        metadata["instagram"] = {"type": "reel", "shouldShareToFeed": True}
    elif service == "youtube":
        yt = {"madeForKids": False, "categoryId": youtube_category}  # Buffer requires a category
        if title:
            yt["title"] = title[:100]
        metadata["youtube"] = yt

    inp = {
        "channelId": channel_id,
        "text": text or "",
        "assets": [{"video": video}],
        "schedulingType": scheduling,
        "mode": "customScheduled" if schedule_iso else "addToQueue",
    }
    if schedule_iso:
        inp["dueAt"] = schedule_iso
    if metadata:
        inp["metadata"] = metadata

    d = _gql(api_key, CREATE_POST, {"input": inp})
    result = d.get("createPost") or {}
    if result.get("__typename") != "PostActionSuccess":
        raise BufferError(result.get("message") or "Buffer rejected the post")
    return result.get("post") or {}
