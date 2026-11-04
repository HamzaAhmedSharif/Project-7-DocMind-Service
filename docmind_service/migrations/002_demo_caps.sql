CREATE TABLE IF NOT EXISTS usage_daily (
    day date NOT NULL,
    scope text NOT NULL,
    count integer NOT NULL DEFAULT 0,
    PRIMARY KEY (day, scope)
);
