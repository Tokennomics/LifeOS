"""The things this deployment cannot do, written down once.

Six endpoints reported hardware that is not here. `/wearables/sync-telemetry` returned an
HRV of 78 and a recovery score of 92 from "Apple Watch Ultra & Whoop 4.0" for any body
posted to it; `/biometrics/circadian-sync` graded a sleep score it had invented into
`HIGH_RECOVERY` and recommended an activity from it; `/wearables/ambient-whispers` had
somebody's friend arriving four metres behind them at the counter;
`/mesh/offline-peer-sync` listed three named peers at three distances over "BLE 5.3 +
Wi-Fi Direct"; `/infra/edge-replication` reported four healthy edge nodes and a 6.8ms
global p95; `/native/app-store-manifest` minted a version, a bundle id and two download
URLs on a host this deployment does not serve.

A wrong venue wastes an evening. A wrong biometric is worse in kind: it is a number about
somebody's body, and the endpoints above did not merely guess it, they had no sensor of any
description to guess from. The nearest thing to a heart rate in this process is the request
body.

`overview.system()` already had to list some of this, because a status page that silently
drops what it cannot do reads as though it can. Having the same facts written twice —
once for the status page and once per endpoint — is how the two drift apart, and the
version people see is whichever one nobody updated. So the entries live here as constants,
`overview.system()` imports them for its `unavailable` list, and each endpoint refuses with
`refusal(...)` built from the same row. There is one place to change the answer.

`needs` is deliberately concrete. "Not supported" tells somebody nothing; naming the native
app, the paired device or the second region tells them what would actually have to exist,
and makes it obvious that none of it is a switch somebody forgot to flip.
"""

import os

#: Capability keys. Endpoints refer to these, never to the prose.
PUSH = "push notifications"
PAYMENTS = "payments"
IDENTITY = "identity verification"
WEARABLES = "wearables and body sensors"
BIOMETRICS = "biometric readings"
MESH = "peer-to-peer mesh between phones"
AUDIO = "live audio rooms"
EDGE = "multi-region edge replication"
NATIVE_BUILD = "native app store builds"

#: Where the real mobile build configuration lives. The manifest endpoint points at these
#: rather than emitting one: a store manifest is an output of a build, and these files are
#: its input. Paths are relative to the repository root.
BUILD_FILES = (
    "surfaces/app/capacitor.config.json",
    "surfaces/app/android/app/src/main/AndroidManifest.xml",
    "surfaces/app/ios/App/App/Info.plist",
    "surfaces/app/www/manifest.webmanifest",
)

#: Every capability this app is asked for and cannot provide, with why not and what would
#: have to be true instead. `why` is one sentence, present tense, about this deployment.
UNAVAILABLE: dict[str, dict] = {
    PUSH: {
        "why": "no VAPID key pair, no APNs certificate and no SMS provider in this repo",
        "needs": ["a VAPID key pair, or an APNs certificate, or an SMS provider account",
                  "a device that has granted notification permission"],
    },
    PAYMENTS: {
        "why": ("no payment processor is connected; the shared tab records what is owed "
                "and moves no money"),
        "needs": ["a connected payment processor and its keys",
                  "an account holder who has completed that processor's onboarding"],
    },
    IDENTITY: {
        "why": "nothing here checks a document; a vouch is one person's word",
        "needs": ["a document-checking provider", "somebody willing to hand it a passport"],
    },
    WEARABLES: {
        "why": ("a web app cannot reach a watch, a ring or a strap, and no device is paired "
                "with this process"),
        "needs": ["a native app on the phone the device is paired with",
                  "the wearer's permission for the platform health store",
                  "a place in the schema to keep a reading, which v0 does not have"],
    },
    BIOMETRICS: {
        "why": ("nothing here reads a heart rate, an HRV or a sleep stage — those come from "
                "a sensor this process cannot reach"),
        "needs": ["a sensor, and a native app that is allowed to read it",
                  "the wearer's permission for the platform health store"],
    },
    MESH: {
        "why": ("a browser cannot open a BLE or Wi-Fi Direct link to another phone, and a "
                "server is not on the mesh two phones would form anyway"),
        "needs": ["a native app on both phones, with Bluetooth permission granted",
                  "the two phones in range of each other, which a server cannot observe"],
    },
    AUDIO: {
        "why": ("there is no audio transport in this deployment: no media server, no call "
                "signalling and no relay"),
        "needs": ["a media server or a peer-to-peer call stack, and a relay for the "
                  "connections that cannot go direct"],
    },
    EDGE: {
        "why": ("this runs as one process against one SQLite file; there is no fleet, no "
                "second region and no replication stream"),
        "needs": ["a second deployment in another region",
                  "a replicating store, which SQLite on a local disk is not"],
    },
    NATIVE_BUILD: {
        "why": ("a store manifest is an output of a build, not of a running server: this "
                "process has no signing identity, no build number and no bundle to describe"),
        "needs": ["a build run against " + BUILD_FILES[0],
                  "a signing identity for each store, which is not in this repo and must "
                  "never be"],
    },
}


class UnknownCapability(KeyError):
    """A capability key that is not one of the constants above."""


def entry(capability: str) -> dict:
    """The row for one capability, or a loud failure.

    A typo'd key must not become a plausible-looking refusal about nothing; that is the
    same class of bug as the props this replaces.
    """
    row = UNAVAILABLE.get(capability)
    if row is None:
        raise UnknownCapability(capability)
    return row


def refusal(capability: str, **extra) -> dict:
    """The body every unbuildable endpoint answers with.

    The same four keys everywhere, so a client can render "we cannot do this, here is why"
    once. `available` is always False: this is not a failure to be retried, and there is no
    partial version of it that would be true.
    """
    row = entry(capability)
    return {"available": False, "capability": capability, "why": row["why"],
            "needs": list(row["needs"]), **extra}


def listing() -> list[dict]:
    """What `overview.system()` puts under `unavailable`.

    Named `name` rather than `capability` because that is the key the status page has
    always used and the PWA reads.
    """
    return [{"name": key, "why": row["why"], "needs": list(row["needs"])}
            for key, row in UNAVAILABLE.items()]


def build_files(root: str = "") -> list[dict]:
    """Where the real mobile build configuration is, and whether it is actually there.

    Checked rather than asserted: the endpoint this serves used to answer with a bundle id
    and a version nobody had built. A path that is present is a fact; a path that is
    missing says so.
    """
    base = root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return [{"path": path, "present": os.path.exists(os.path.join(base, path))}
            for path in BUILD_FILES]
