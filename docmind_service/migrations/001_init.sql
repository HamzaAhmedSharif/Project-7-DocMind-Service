CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE documents (
  document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   text NOT NULL DEFAULT 'public',
  sha256      char(64) NOT NULL,
  filename    text NOT NULL,
  pages       int  NOT NULL CHECK (pages >= 1),
  chunk_count int  NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)
);
CREATE TABLE chunks (
  chunk_id    text PRIMARY KEY,
  document_id uuid NOT NULL REFERENCES documents ON DELETE CASCADE,
  tenant_id   text NOT NULL,
  ordinal     int  NOT NULL,
  page        int  NOT NULL CHECK (page >= 1),
  text        text NOT NULL,
  embedding   vector(384) NOT NULL,
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
CREATE INDEX chunks_doc_idx ON chunks (document_id, ordinal);
CREATE INDEX chunks_tenant_idx ON chunks (tenant_id);
