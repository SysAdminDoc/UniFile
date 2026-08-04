# Blocked Roadmap

Items here need external input, credentials, or packaging decisions before they can move back to `ROADMAP.md`.

## Windows Shell Integration

- **Explorer preview pane** — optional IThumbnailProvider COM shim to show UniFile category badge on folder icons.
  - Blocker: Windows thumbnail providers run as Explorer-loaded shell extensions. Shipping this safely needs a compiled and signed in-process COM DLL plus an installer/registration strategy. This Python/PyQt app currently has no shell-extension host or signing path, and implementing it as a Python process hook would put Explorer stability at risk.

## NAS Packaging

- **Synology/QNAP `.spk`/`.qpkg` packages** — blocked pending a target CPU/DSM-QTS matrix, vendor packaging toolchains, and an operator-approved unsigned installation/update strategy. The portable Docker deployment is implemented; these appliance-specific packages should not be guessed from a desktop-only workspace.

## Community Package Publication

- **Chocolatey / Scoop package** — blocked pending operator-owned Chocolatey/Scoop manifests or repositories, maintainer approval, and release automation credentials. A local manifest without publication ownership would not provide an installable community package or the requested automatic release updates.
- **Homebrew formula** — blocked pending the operator-owned `homebrew-unifile` tap, macOS release/build validation, and tap publication credentials. The required external tap does not exist in this workspace.
- **Snap package** — blocked pending an operator-approved Snapcraft publisher, Ubuntu build matrix, and Snap Store credentials. Local Snap metadata alone cannot publish the requested confined package.
