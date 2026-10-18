# tuning the embeddings section

rough `batchSize` / `concurrency` starting points for the `embeddings` entry in
`models.json`. both are required keys (`models_config.py` validates them) because
they are per-model/server chemistry — there is no number that is right for
everything.

what bounds them:

- **batchSize** is bounded by the model's context window: batch tokens (chars x ~4
  for english) must fit in one `/v1/embeddings` call, with slack — the client-side
  tokenizer only approximates the server's.
- **concurrency** is bounded by the device locally (a single GPU often serializes
  batches, so 1-2 is plenty for ollama / llama.cpp) and by rate limits remotely.

## starting points

| profile | ctx window | batchSize | concurrency |
|---|---|---|---|
| small local model (all-MiniLM-L6-v2, embeddinggemma, ...) | <= 2k | 16-32 | 2-4 |
| mid local model (nomic-embed-text, snowflake-arctic-embed, ...) | ~8k | 32-64 | 2-4 |
| large-ctx local model (bge-m3, ...), long docs | 8k-32k | 8-16 | 1-2 |
| remote API, generous limits (OpenAI text-embedding-3-*) | 8k tok/doc | 64-256 | 4-16 |
| remote API, strict limits (serverless / free tiers) | varies | 8-32 | 1-2 |

notes:

- long docs: a few big documents fill a call, and the GPU is already saturated
  per call, so extra concurrency just queues.
- remote generous limits: batch toward the per-request token cap and raise
  concurrency until 429s; check the provider's documented MaxBatchSize /
  tokens-per-minute limits.

## procedure

start low, watch server logs (and 429s), scale up. the only numbers that count
are measured ones on the actual server + model + document mix.
