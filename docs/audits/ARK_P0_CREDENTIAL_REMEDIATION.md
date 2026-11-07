# ARK P0 — Git Credential Remediation

**Status:** local remediation COMPLETE; provider-side revocation OUTSTANDING (human action)
**Date:** 2026-11-06
**Scope:** credential embedded in the `origin` remote URL of this working copy

> This record deliberately contains **no token material**. Only the token
> *class* and *length* are stated, because those are required to choose the
> correct revocation path. The value itself was never printed, logged, or
> written to any file.

## 1. What the credential is

| Property | Value |
| --- | --- |
| Transport | HTTPS userinfo in the remote URL |
| Token prefix class | `ghu_` |
| Token length | 40 characters |
| Host | `github.com` |
| Repository | `UncleT-cyber/Ark-Geo` |

`ghu_` is the prefix for a **GitHub App user-to-server (OAuth) access token**.
It is *not* a classic personal access token and *not* a fine-grained personal
access token (those use different prefixes). Consequence: such tokens are
**short-lived and minted by a GitHub App installation**, so they are
**revoked/rotated from the App side**, not from the personal-settings token
page.

### Where it most likely came from

The token was present in `.git/config` only. There is **no `credential.helper`
configured** and **no `~/.git-credentials` file**, so it was not written by a
credential helper. The most probable origin is a tool or script that ran
`git remote set-url`/`git clone` with a `x-access-token:ghu_…@github.com` URL
during environment provisioning (the pattern used by GitHub App installation
tokens in automated sandboxes). It was **not** committed by any ARK code.

## 2. Actions taken (this pass)

1. Classified the credential without printing it (prefix + length only).
2. Rewrote the remote to a credential-free URL:
   `git remote set-url origin https://github.com/UncleT-cyber/Ark-Geo.git`
3. Verified no credential remains:

   | Location | Result |
   | --- | --- |
   | `.git/config` | clean (0 matches) |
   | tracked working tree | clean |
   | `git log --all -S` (history) | clean |
   | `.git/logs/HEAD` (reflog) | clean |
   | `.git` object store (packed + loose) | clean |
   | runtime logs (`/tmp/arkgeo-*.log`) | clean |
   | shell history | clean |
   | audit reports | clean (the earlier `ghu_…` prefix mention was removed) |

   Final whole-repo scan for the `ghu_` prefix: **no matches**.

## 3. Actions still required (provider side — human)

1. **Revoke / rotate the GitHub App installation token** through the issuing
   integration (the GitHub App that minted it). Because `ghu_` tokens expire,
   rotation is typically immediate; confirm the App's token cache is cleared.
2. If the same credential was ever exported into a CI secret store, rotate
   there too.
3. Going forward, prefer a **credential-free remote** plus an ephemeral,
   short-lived credential injected by the environment at push time.

## 4. Gate statement

- **Local gate:** PASS — the working copy no longer carries a credential
  anywhere on disk or in history.
- **Commit/push gate:** still gated on §3 (provider-side revocation) per the
  advisor's directive. No commit or push has been performed.

*This document was produced by an AI agent (OpenHands) on behalf of the ARK
maintainer.*
