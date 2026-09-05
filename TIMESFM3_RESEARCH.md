# TimesFM 3 research sandbox

This is a private, non-commercial, non-production forecasting experiment. It
is intentionally separate from the OctoBot process, profile, decision journal,
and simulated trader.

## Design

The experiment has four layers with one-way data flow:

1. Frozen public Binance futures, spot, and funding inputs are mounted read-only.
2. A causal loader creates one daily 24-hour query with 1,536 hours of context.
3. TimesFM 3 produces a four-asset path and nine quantiles on CPU, offline.
4. A later deterministic evaluator compares forecasts with simple baselines and
   translates them into a separate fee-, slippage-, and funding-aware diagnostic.

The four price targets are BTC, ETH, SOL, and XRP futures log prices. Sixteen
past-only covariates encode notional volume, absolute return, futures/spot basis,
and last-published funding for each asset. Five known-future calendar channels
bring the total to 25 variates, below the checkpoint's limit of 32.

Historical measurements are diagnostic because the local datasets have already
been reused during strategy development. A historical pass can authorize only a
new 180-day orderless forward observer after manual review. It cannot authorize
paper or real orders.

## Isolation

`timesfm3-research` runs with no network, a read-only root filesystem, no Linux
capabilities, no credentials, a read-only model cache, a 24 GiB memory ceiling,
and a 12-CPU ceiling. `timesfm3-fetch` is the only networked component. It mounts
no market dataset and refuses to download until a user-created acceptance record
matches the pinned model repository, revision, and license.

TimesFM source code is Apache-2.0. The TimesFM 3 pretrained weights are governed
by Google's separate `timesfm-non-commercial-license-v1.0`; downloading,
accessing, or using them constitutes acceptance. Review the current terms at:

<https://huggingface.co/google/timesfm-3.0-pytorch/blob/main/LICENSE>

No acceptance file is created automatically. Before an authorized download, the
user must create `octobot-local/timesfm3/model/LICENSE_ACCEPTANCE.json` with:

```json
{
  "schema_version": 1,
  "model_repository": "google/timesfm-3.0-pytorch",
  "model_revision": "43046b85ec22d584a13f8098c2ed39c889e129c2",
  "license_id": "timesfm-non-commercial-license-v1.0",
  "accepted": true,
  "noncommercial_research_only": true,
  "production_use": false,
  "commercial_use": false,
  "accepted_by": "USER NAME",
  "accepted_at": "ISO-8601 UTC TIMESTAMP"
}
```

Only after that explicit action may the pinned checkpoint be fetched with:

```bash
docker-compose -f docker-compose.local.yml -f docker-compose.timesfm3.yml \
  run --rm --no-deps timesfm3-fetch
```

Inference and evaluation must use `timesfm3-research`, which has no network.
