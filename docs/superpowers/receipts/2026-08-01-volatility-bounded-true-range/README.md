# VolatilitySystem Bounded True-Range Research Receipt

**Status:** sealed, credential-free, non-executable pre-performance evidence

This directory preserves the exact temporary source and deterministic tool/test bytes
required by the
[bounded true-range episode screen](../../plans/2026-08-01-volatility-bounded-true-range-episode-screen.md).
It does not install a strategy, expose an import path, create a BotRelease, or authorize
Runtime, Paper, Live, Hyperopt, Lookahead, Recursive, or any second performance run.

The canonical [runtime receipt](runtime-receipt.json) is 1,509 bytes with SHA-256
`3c5bffdc81d9f59c641ed2401ccb9f35379575081ac309168f030fca19191056`.
Its independent caller-supplied hash is the authority checked before the one-shot
controller parses the receipt. It binds exactly 13 logical inputs and immutable image
`sha256:fb7bc20017bae79af1f7533c8b2018098bb627306d9c2286fb9b1501551fe03c`.

All files under `bytes/` are byte-for-byte evidence copies with deliberately
non-executable suffixes. They must not be renamed into an importable strategy or tool
tree. The two accepted baseline paths are byte-identical and are deduplicated into one
stored blob; the runtime receipt still binds both logical inputs separately.

The restart tool and several test copies preserve non-secret absolute path constants from
the machine on which their frozen bytes were verified. Those exact evidence blobs are
therefore host-specific, not portable source distributions. They remain here because
redacting or parameterizing them after verification would create different, unverified
bytes; the active runtime controller does not derive its input paths from those constants.

## Durable byte inventory

| Stored evidence | Bytes | SHA-256 | Meaning |
|---|---:|---|---|
| `bytes/baseline-VolatilitySystem.py.txt` | 6,618 | `fed33eceed8bec65f5c47d1727aa4a18b70f15d064b20000eb653622bb16fe85` | Both unchanged tracked B mirrors |
| `bytes/candidate-VolatilitySystem.py.txt` | 14,447 | `41e9aad2be1dd262bbc715cefa414c23293d4abea66e17a2cef3ac8559db3923` | Temporary candidate C |
| `bytes/test_bounded_true_range_episode.py.txt` | 29,906 | `a610b5182d393e697633ca33841e7387aaa4d118e79331d6fdcc3c38c2fa6941` | Candidate mechanism tests |
| `bytes/restart_matrix.py.txt` | 121,426 | `08383a8ecacc1cdb97ad5f2f37e83e954d0e0862dea9256326d2391ff3e2b7e4` | Admission and exhaustive restart tool |
| `bytes/test_restart_matrix.py.txt` | 76,962 | `6c34ef349338b42f5913127142312ed64339c9d3c8d2f4f9d6d69e2b056fad31` | Admission/restart tests |
| `bytes/contract.py.txt` | 15,035 | `c05ef3a3987eec55994b9a7d007da1e183ac2213f4ae58416032eb1afc8d8790` | Shared B/C request contract |
| `bytes/test_contract.py.txt` | 20,021 | `6684da1b4befa1df8119841973bdd16780e1a5f563208a83f3b2865d36f8d1a9` | Shared-contract tests |
| `bytes/controller.py.txt` | 63,152 | `09f40adabf89facdf162afdd1294d776b77a158dc0a5d8fc233d6e0687bca960` | One-shot host controller |
| `bytes/test_controller.py.txt` | 39,283 | `e1406cbcb664ab5f90a14d816bd694a667fd94bf29ef4887d5810a3f94e13f09` | Controller tests |
| `bytes/validator.py.txt` | 92,592 | `540c04d25fbd6aedd64c5036607f06ced66c7922fe75618d0b5e2915a7d1f72c` | Fail-closed native-artifact validator |
| `bytes/test_validator.py.txt` | 53,799 | `ebf52376b175885636e1f4fe9ef0b1673a7ea1629f57bb85f497cb0753889609` | Validator tests |
| `bytes/generate_identity.py.txt` | 38,736 | `0ae68b3b98a5fa55847dcea7893d0337ff3f022aca8b7fa4ae302ce74f181023` | Immutable-image identity generator |
| `bytes/test_image_identity.py.txt` | 16,803 | `1fca0168b0cfa7ba2979bcf32354c82cc014a99a5e57f147702bd2582f6a9170` | Image-identity tests |
| `bytes/effective-config.json.txt` | 1,794 | `0685d9f364b9fd208c437b1c5511c20b4ee9d28780a220f24059225cb5a5b37e` | Exact effective configuration |
| `bytes/b-request.json.txt` | 379 | `48f9256adec70f0afc666a7acd7e6eadc05306eaeae58669d999f0af620b87fc` | B request with retained snapshot |
| `bytes/c-request-template.json.txt` | 437 | `fd5e4cf0027e89db1d839eb80e61b9dca8f1e4df9d7a0859719fbd81ace54868` | C replay template without retention |
| `bytes/image-identity.json.txt` | 4,764 | `69bcc0b555a4dbc530ec94928b846e8348463b4d1b54eef6777279783a513982` | Portable immutable-image identity |
| `bytes/backend-source-manifest.json.txt` | 62,850 | `89fbada1b25a3cc707e34103642c05557bb8d56d3170e4c139bf794a3c2a773d` | Backend source inventory bound by image identity |
| `bytes/package-inventory.json.txt` | 4,080 | `84d559d661cb91638c2a96db107608568d655a2f6fb3a278205ad668010a2c20` | Exact installed package inventory |
| `bytes/entrypoint-evidence.json.txt` | 440 | `06e5861082039f536ca7112eeba16195b0441fdeb120b336fff0de47d09773d0` | Entrypoint, UID/GID, and workdir evidence |

## Deliberately external evidence

The development admission receipt (5,568 bytes,
`9bf627200e26944bbfa6ba764ca809566a64f28797fa6a9b96862ce69c03ea25`)
and restart verification receipt (5,622 bytes,
`5f67db599c52a68a50aff1f4bd2acd06b78ed13c3bb0306105f349493cf1ec4f`)
contain local absolute paths. Their exact hashes and portable findings are recorded in
the [research receipt report](../../reports/2026-08-01-volatility-bounded-true-range-research-receipt.md),
but their raw bytes are not tracked.

Raw market files, the 274 MB restart record stream and eight shards, Docker
inspect/history/build/probe/UI records, raw OCI/image objects, the immutable image itself,
logs, caches, spent leases, state/work directories, secrets, and eventual result
artifacts are also excluded. The exact immutable image must remain available outside Git;
the tracked identity authenticates the required image but does not guarantee its future
availability.
