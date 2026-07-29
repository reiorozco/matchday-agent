-- matchday-agent — 001: Enable RLS on all public tables.
--
-- Context: Supabase security advisor (rls_disabled_in_public, CRITICAL) flagged
-- these tables as fully exposed to the anon publishable key. Backend uses
-- DATABASE_URL with the `postgres` role which bypasses RLS by default, so this
-- migration is defense-in-depth for the case where the anon key is ever exposed
-- to a client (there is no frontend using it today — see decisions.md § 8.14).
--
-- Applied live via: .venv/bin/python -m matchday_agent.scripts.apply_migration
--   (fallback because Supabase MCP is read-only — see decisions.md § 8.10).
--
-- LangGraph checkpoint tables (checkpoint_migrations, checkpoints,
-- checkpoint_blobs, checkpoint_writes) are managed by AsyncPostgresSaver.setup()
-- but the RLS toggle is a table-level attribute, safe to alter independently.

-- 1) Enable RLS on all 5 public tables.
ALTER TABLE public.checkpoint_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoints           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_blobs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_writes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents             ENABLE ROW LEVEL SECURITY;

-- 2) Grant service_role full access (defense-in-depth for future Supabase SDK use).
--    Effect: anon and authenticated roles are blocked from ALL operations.
--    The backend (DATABASE_URL → postgres role) continues to work — postgres
--    bypasses RLS entirely, independent of these policies.
CREATE POLICY "service_role_full_access" ON public.checkpoint_migrations
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access" ON public.checkpoints
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access" ON public.checkpoint_blobs
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access" ON public.checkpoint_writes
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access" ON public.documents
  FOR ALL TO service_role USING (true) WITH CHECK (true);
