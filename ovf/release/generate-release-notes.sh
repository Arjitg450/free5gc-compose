#!/bin/bash
# Generate a GitHub release body for a given version from produced assets.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  generate-release-notes.sh --version <vX.Y.Z> [--output <path>]
EOF
}

VERSION=""
OUTPUT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

[ -n "$VERSION" ] || { echo "--version is required" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ASSET_ROOT="$REPO_ROOT/ovf/release/output/${VERSION}"
COMMIT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
OUTPUT="${OUTPUT:-$ASSET_ROOT/release-notes.md}"

mkdir -p "$(dirname "$OUTPUT")"

cat >"$OUTPUT" <<EOF
# free5GC Lab ${VERSION}

Git commit: \`${COMMIT}\`

## Choose the right download

| Student machine | Recommended asset family |
| --- | --- |
| Apple Silicon (ARM host) | \`arm64\` |
| Intel/AMD (x86_64 host) | \`amd64\` |

## Hypervisor compatibility

| Asset | Best for | Notes |
| --- | --- | --- |
| \`.qcow2\` | QEMU | Canonical build artifact |
| \`.vmdk\` | VMware | Can also be used as a disk in some VirtualBox workflows |
| \`.vdi\` | VirtualBox disk attach | Useful when students import by creating a VM manually |
| \`.ovf\` / \`.ova\` | VirtualBox / VMware import | Convenience package; architecture-specific |

## Minimum student VM resources

- RAM: 4 GB minimum, 8 GB recommended
- vCPUs: 2 minimum, 4 recommended
- Disk: 40 GB allocated image
- First boot wait: allow 2-5 minutes for Docker + the 5G stack to settle

## Runtime credentials

- Username: \`ubuntu\`
- Password: \`free5gc\`

## Validation commands after import

\`\`\`bash
free5gc-status
self-test.sh
cat /etc/free5gc-release
\`\`\`

## Branch workflows

- \`bootcamp\`: run the manual lab from \`5G_E2E_free5GC_UERANSIM_Report.md\`
- \`feat/ieee-10175424\`: switch with \`sudo /usr/local/bin/branch-switch.sh ieee-10175424\` and run the IEEE attack workflow from \`attack_poc/README.md\`

## Student guide

Include \`STUDENT_VM_IMPORT.md\` with the release announcement so students pick the correct architecture and hypervisor path.

## Checksums

Download \`SHA256SUMS\` from the matching release asset directory and verify before distribution.
EOF

echo "$OUTPUT"
