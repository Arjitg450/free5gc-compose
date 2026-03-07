# Release Packaging from QEMU Builds

This directory contains the tooling for publishing student-facing VM artifacts while keeping **QEMU/Packer** as the canonical build system.

## Architecture strategy

- `arm64`: for Apple Silicon students
- `amd64`: for Intel/AMD students

The release process is:

1. Build and validate the `qcow2` with QEMU/Packer.
2. Convert the validated `qcow2` into `vmdk` and `vdi`.
3. Generate an `ovf` descriptor, manifest, and `ova`.
4. Publish checksums and release notes.

## Build inputs

- ARM64 template: [`ovf/packer/ubuntu-22.04.5-free5gc-qemu.pkr.hcl`](../packer/ubuntu-22.04.5-free5gc-qemu.pkr.hcl)
- AMD64 template: [`ovf/packer/ubuntu-22.04.5-free5gc-qemu-amd64.pkr.hcl`](../packer/ubuntu-22.04.5-free5gc-qemu-amd64.pkr.hcl)

## Packaging example

```bash
cd ovf/release

./package-release-assets.sh \
  --arch arm64 \
  --version v1.0.0 \
  --qcow2 ../packer/output-qemu/ubuntu-22.04.5-free5gc.qcow2

./package-release-assets.sh \
  --arch amd64 \
  --version v1.0.0 \
  --qcow2 ../packer/output-qemu-amd64/ubuntu-22.04.5-free5gc-amd64.qcow2
```

The script always creates `qcow2`, `vmdk`, `vdi`, `ovf`, metadata, and `SHA256SUMS`. It can also assemble an `ova` directly from the generated descriptor and disk image.

Make sure the release host has enough free disk space before packaging. A safe rule is to keep at least `4x` the qcow2 actual disk usage plus `2 GiB` free in the output filesystem.

## Release notes example

```bash
./generate-release-notes.sh --version v1.0.0
```

This writes `ovf/release/output/v1.0.0/release-notes.md`.
