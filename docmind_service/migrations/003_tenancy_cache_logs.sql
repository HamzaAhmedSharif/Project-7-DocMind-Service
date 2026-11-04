CREATE TABLE tenants (
  tenant_id      text PRIMARY KEY,
  corpus_version text NOT NULL DEFAULT '0',
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE api_keys (
  key_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      text NOT NULL,
  prefix         text NOT NULL UNIQUE,
  key_hash       char(64) NOT NULL,
  label          text NOT NULL DEFAULT '',
  scopes         text[] NOT NULL DEFAULT '{read}',
  rpm            int,
  daily_queries  int,
  max_documents  int,
  max_pages      int,
  created_at     timestamptz NOT NULL DEFAULT now(),
  revoked_at     timestamptz,
  last_used_at   timestamptz
);
CREATE INDEX api_keys_tenant_idx ON api_keys (tenant_id);
CREATE TABLE query_log (
  id                bigserial PRIMARY KEY,
  ts                timestamptz NOT NULL DEFAULT now(),
  tenant_id         text NOT NULL,
  request_id        text NOT NULL,
  question_redacted text NOT NULL,
  n_chunks          int  NOT NULL,
  refused           bool NOT NULL,
  refusal_reason    text,
  prompt_tokens     int  NOT NULL DEFAULT 0,
  completion_tokens int  NOT NULL DEFAULT 0,
  cache             text NOT NULL
);
CREATE INDEX query_log_ts_idx ON query_log (ts);
CREATE TABLE semantic_cache (
  id                 bigserial PRIMARY KEY,
  tenant_id          text NOT NULL,
  corpus_version     text NOT NULL,
  scope_hash         char(64) NOT NULL,
  question_embedding vector(384) NOT NULL,
  answer_json        jsonb NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  hits               int NOT NULL DEFAULT 0
);
CREATE INDEX semantic_cache_scope_idx ON semantic_cache (tenant_id, corpus_version, scope_hash);
