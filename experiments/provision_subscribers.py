#!/usr/bin/env python3
"""
Provision multiple UE subscribers in free5GC via the webconsole REST API.

Supports both bulk creation (single API call) and loop-based creation
with per-subscriber customization.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Dict, List
from urllib import request, error


DEFAULT_WEBCONSOLE = "http://localhost:5000"
DEFAULT_BASE_IMSI = 208930000000001
DEFAULT_PLMN = "20893"

SUBSCRIBER_TEMPLATE: Dict = {
    "plmnID": DEFAULT_PLMN,
    "ueId": "",
    "AuthenticationSubscription": {
        "authenticationManagementField": "8000",
        "authenticationMethod": "5G_AKA",
        "milenage": {
            "op": {
                "encryptionAlgorithm": 0,
                "encryptionKey": 0,
                "opValue": "8e27b6af0e692e750f32667a3b14605d",
            }
        },
        "opc": {
            "encryptionAlgorithm": 0,
            "encryptionKey": 0,
            "opcValue": "",
        },
        "permanentKey": {
            "encryptionAlgorithm": 0,
            "encryptionKey": 0,
            "permanentKeyValue": "8baf473f2f8fd09487cccbd7097c6862",
        },
        "sequenceNumber": "16f3b3f70fc2",
    },
    "AccessAndMobilitySubscriptionData": {
        "gpsis": ["msisdn-0900000000"],
        "nssai": {
            "defaultSingleNssais": [
                {"sst": 1, "sd": "010203", "isDefault": True}
            ],
            "singleNssais": [],
        },
        "subscribedUeAmbr": {"downlink": "2 Gbps", "uplink": "1 Gbps"},
    },
    "SessionManagementSubscriptionData": [
        {
            "singleNssai": {"sst": 1, "sd": "010203"},
            "dnnConfigurations": {
                "internet": {
                    "sscModes": {
                        "defaultSscMode": "SSC_MODE_1",
                        "allowedSscModes": ["SSC_MODE_2", "SSC_MODE_3"],
                    },
                    "pduSessionTypes": {
                        "defaultSessionType": "IPV4",
                        "allowedSessionTypes": ["IPV4"],
                    },
                    "sessionAmbr": {
                        "uplink": "200 Mbps",
                        "downlink": "100 Mbps",
                    },
                    "5gQosProfile": {
                        "5qi": 9,
                        "arp": {"priorityLevel": 8},
                        "priorityLevel": 8,
                    },
                }
            },
        }
    ],
    "SmfSelectionSubscriptionData": {
        "subscribedSnssaiInfos": {
            "01010203": {"dnnInfos": [{"dnn": "internet"}]}
        }
    },
    "AmPolicyData": {"subscCats": ["free5gc"]},
    "SmPolicyData": {
        "smPolicySnssaiData": {
            "01010203": {
                "snssai": {"sst": 1, "sd": "010203"},
                "smPolicyDnnData": {"internet": {"dnn": "internet"}},
            }
        }
    },
    "FlowRules": [],
    "QosFlows": [],
}


def api_login(webconsole: str, username: str = "admin", password: str = "free5gc") -> str:
    """Log in to the webconsole and return a JWT token."""
    url = f"{webconsole}/api/login"
    payload = json.dumps({"username": username, "password": password}).encode()
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            token = body.get("access_token") or body.get("token", "")
            if not token:
                raise RuntimeError(f"Login succeeded but no token in response: {body}")
            return token
    except error.URLError as exc:
        raise RuntimeError(f"Cannot reach webconsole at {url}: {exc}") from exc


def api_post(url: str, token: str, payload: Dict) -> int:
    """POST JSON to webconsole. Returns HTTP status code."""
    data = json.dumps(payload).encode()
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Token": token},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            return resp.status
    except error.HTTPError as exc:
        return exc.code


def api_get(url: str, token: str) -> tuple:
    """GET from webconsole. Returns (status_code, body_dict)."""
    req = request.Request(url, headers={"Token": token}, method="GET")
    try:
        with request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except error.HTTPError as exc:
        return exc.code, {}


def build_subscriber_body(imsi: int, plmn: str) -> Dict:
    """Build a subscriber creation payload for the given IMSI."""
    body = json.loads(json.dumps(SUBSCRIBER_TEMPLATE))
    body["ueId"] = f"imsi-{imsi}"
    body["plmnID"] = plmn
    return body


def provision_bulk(webconsole: str, token: str, base_imsi: int, count: int, plmn: str) -> List[str]:
    """
    Use the webconsole bulk creation endpoint to provision N subscribers
    in a single API call. All share the same K/OP/slice config.
    """
    ue_id = f"imsi-{base_imsi}"
    url = f"{webconsole}/api/subscriber/{ue_id}/{plmn}/{count}"
    body = build_subscriber_body(base_imsi, plmn)
    status = api_post(url, token, body)
    if status in (200, 201):
        created = [f"imsi-{base_imsi + i}" for i in range(count)]
        print(f"[bulk] Created {count} subscribers starting at {ue_id} (HTTP {status})")
        return created
    print(f"[bulk] Bulk creation returned HTTP {status}, falling back to loop mode")
    return provision_loop(webconsole, token, base_imsi, count, plmn)


def provision_loop(webconsole: str, token: str, base_imsi: int, count: int, plmn: str) -> List[str]:
    """Provision subscribers one at a time with 10ms delay between calls."""
    created: List[str] = []
    for i in range(count):
        imsi = base_imsi + i
        ue_id = f"imsi-{imsi}"
        url = f"{webconsole}/api/subscriber/{ue_id}/{plmn}"
        body = build_subscriber_body(imsi, plmn)
        status = api_post(url, token, body)
        if status in (200, 201):
            created.append(ue_id)
            print(f"  [{i + 1}/{count}] Created {ue_id}")
        else:
            print(f"  [{i + 1}/{count}] FAILED {ue_id} (HTTP {status})")
        time.sleep(0.01)
    return created


def verify_subscribers(webconsole: str, token: str, expected: List[str], plmn: str) -> Dict:
    """Spot-check that subscribers exist in the webconsole."""
    verified = 0
    failed = 0
    for ue_id in expected[:5]:
        url = f"{webconsole}/api/subscriber/{ue_id}/{plmn}"
        status, _ = api_get(url, token)
        if status == 200:
            verified += 1
        else:
            failed += 1
    return {
        "checked": min(5, len(expected)),
        "verified": verified,
        "failed": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision UE subscribers in free5GC webconsole.")
    parser.add_argument("--count", type=int, required=True, help="Number of subscribers to create.")
    parser.add_argument("--base-imsi", type=int, default=DEFAULT_BASE_IMSI, help="Starting IMSI (numeric).")
    parser.add_argument("--plmn", default=DEFAULT_PLMN, help="Serving PLMN ID.")
    parser.add_argument("--webconsole", default=DEFAULT_WEBCONSOLE, help="Webconsole base URL.")
    parser.add_argument("--mode", choices=["bulk", "loop"], default="bulk", help="Creation mode.")
    parser.add_argument("--output", default="experiments/subscribers.json", help="Output manifest path.")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls, write dummy manifest.")
    args = parser.parse_args()

    output_path = pathlib.Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        created = [f"imsi-{args.base_imsi + i}" for i in range(args.count)]
        manifest = {
            "base_imsi": args.base_imsi,
            "count": args.count,
            "plmn": args.plmn,
            "subscribers": created,
            "mode": "dry_run",
            "verification": {"checked": 0, "verified": 0, "failed": 0},
        }
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[dry-run] Wrote manifest for {args.count} subscribers to {output_path}")
        return 0

    print(f"Logging into webconsole at {args.webconsole} ...")
    token = api_login(args.webconsole)
    print("Login successful.")

    if args.mode == "bulk":
        created = provision_bulk(args.webconsole, token, args.base_imsi, args.count, args.plmn)
    else:
        created = provision_loop(args.webconsole, token, args.base_imsi, args.count, args.plmn)

    verification = verify_subscribers(args.webconsole, token, created, args.plmn)

    manifest = {
        "base_imsi": args.base_imsi,
        "count": len(created),
        "plmn": args.plmn,
        "subscribers": created,
        "mode": args.mode,
        "verification": verification,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest ({len(created)} subscribers) to {output_path}")
    print(f"Verification: {verification}")
    return 0 if verification.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
