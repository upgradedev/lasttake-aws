"""The judge-facing URL, checked the way a judge would hit it.

`tools/uptime_check.py` walks the Lambda page. Until 2026-09-13 nothing checked
the CloudFront URL that the README, the video and the Devpost entry actually
point at, and on that day it served an unmerged branch head published by hand,
with the public acceptance receipt still describing an older release, and a
bundle carrying dollar figures, a database the product does not use, and two
competitor names. Each of those is now a failing check here.

Four things, in order, every one of them a fact a judge can also observe:

1. `/release.json` names a commit and the assets that make up the release, and
   the served HTML carries that same commit (``infra/frontend_smoke.py``).
2. `/acceptance.json` describes that same commit. A release the pipeline did
   not accept is a release nobody proved.
3. The served JavaScript bundle contains none of the sentences this product
   is not allowed to say: no benefit figure, no clearance, no service it does
   not deploy, no competitor, no simulation button.
4. The scene preview the landing renders is present and says it is fictional.

Run: python tools/judge_url_check.py https://d3kf6hquzlli8g.cloudfront.net/
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "infra")
from frontend_smoke import check as smoke  # noqa: E402

TIMEOUT = 45

#: Anything here in the served bundle is the product saying something it cannot
#: back. Kept as plain substrings and matched with `in`, never as a regex.
FORBIDDEN = (
    "$50,000", "$50k", "< 5 Seconds", "Cryptographic S3 Seal", "DynamoDB",
    "Object Lock", "WORM", "Claude 3.5", "Scriptation", "ScriptE",
    "Simulate Live Ingest", "Zero-Downtime", "bulletproof", "Production ROI",
    "clear to shoot", "legally cleared", "all rules verified",
)


class CheckFailed(Exception):
    pass


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: judge_url_check.py <cloudfront-url>", file=sys.stderr)
        return 2
    base = argv[1] if argv[1].endswith("/") else argv[1] + "/"
    lines = [f"## Judge URL check, `{base}`", ""]

    status, body = get(base + "release.json")
    if status != 200:
        raise CheckFailed(f"release.json returned {status}")
    release = json.loads(body)
    commit = release["commit"]
    lines.append(f"- release.json names commit `{commit[:12]}` and {len(release.get('files', {}))} files")

    status, body = get(base + "acceptance.json")
    if status != 200:
        raise CheckFailed(f"acceptance.json returned {status}")
    acceptance = json.loads(body)
    if acceptance.get("frontend_commit") != commit:
        raise CheckFailed(
            f"the served release is {commit[:12]} but the public acceptance receipt describes "
            f"{str(acceptance.get('frontend_commit'))[:12]}: this release was not accepted by the pipeline"
        )
    if acceptance.get("journeys") != "success" or acceptance.get("postflight") != "success":
        raise CheckFailed("the acceptance receipt for this release does not record a passing run")
    lines.append(f"- acceptance.json describes the same commit, journeys `{acceptance['journeys']}`, backend `{str(acceptance.get('backend_commit'))[:12]}`")

    bundles = [name for name in release.get("files", {}) if name.startswith("assets/") and name.endswith(".js")]
    if not bundles:
        raise CheckFailed("release.json lists no JavaScript bundle")
    for name in bundles:
        status, body = get(base + name)
        if status != 200:
            raise CheckFailed(f"bundle {name} returned {status}")
        text = body.decode("utf-8", "replace")
        found = [word for word in FORBIDDEN if word in text]
        if found:
            raise CheckFailed(f"the served bundle {name} contains {found}: the product is saying something it cannot back")
    lines.append(f"- {len(bundles)} bundle(s) contain none of the {len(FORBIDDEN)} forbidden sentences")

    status, body = get(base + "scene-preview.json")
    if status != 200:
        raise CheckFailed(f"scene-preview.json returned {status}")
    preview = json.loads(body)
    if "fictional" not in str(preview.get("synthetic_notice", "")).lower():
        raise CheckFailed("the scene preview does not say on its face that the production is fictional")
    lines.append(f"- scene preview: {preview.get('required_beats')} required beats, {preview.get('supplied_takes')} supplied takes, fictional notice present")

    smoke(base, commit)
    lines.append("- served HTML carries the release commit, CSP and nosniff headers, real assets, honest API errors")
    lines.append("")
    lines.append("All four hold.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except CheckFailed as failure:
        print(f"## Judge URL check FAILED\n\n- {failure}")
        raise SystemExit(1)
