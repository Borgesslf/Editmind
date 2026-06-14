-- EditMind v5.2 - SQL consolidado para auditoria/deploy
-- Seguro para reexecução (idempotente)

create extension if not exists pgcrypto;

-- =========================
-- Tabela public.cortes
-- =========================
create table if not exists public.cortes (
  id uuid primary key default gen_random_uuid(),
  user_email text not null,
  video_url text not null,
  titulo text not null,
  inicio_segundos numeric,
  fim_segundos numeric,
  foco text,
  duracao_tipo text,
  formato_vertical boolean not null default false,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.cortes add column if not exists inicio_segundos numeric;
alter table public.cortes add column if not exists fim_segundos numeric;
alter table public.cortes add column if not exists foco text;
alter table public.cortes add column if not exists duracao_tipo text;
alter table public.cortes add column if not exists formato_vertical boolean not null default false;
alter table public.cortes add column if not exists atualizado_em timestamptz not null default now();

create index if not exists idx_cortes_user_email on public.cortes (user_email);
create index if not exists idx_cortes_criado_em on public.cortes (criado_em desc);
create index if not exists idx_cortes_foco on public.cortes (foco);
create index if not exists idx_cortes_user_criado on public.cortes (user_email, criado_em desc);

create or replace function public.set_cortes_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

drop trigger if exists trg_cortes_updated_at on public.cortes;
create trigger trg_cortes_updated_at
before update on public.cortes
for each row execute function public.set_cortes_updated_at();

alter table public.cortes enable row level security;

drop policy if exists "cortes_select_own" on public.cortes;
create policy "cortes_select_own"
on public.cortes
for select
to authenticated
using (auth.email() = user_email);

drop policy if exists "cortes_insert_own" on public.cortes;
create policy "cortes_insert_own"
on public.cortes
for insert
to authenticated
with check (auth.email() = user_email);

drop policy if exists "cortes_update_own" on public.cortes;
create policy "cortes_update_own"
on public.cortes
for update
to authenticated
using (auth.email() = user_email)
with check (auth.email() = user_email);

drop policy if exists "cortes_delete_own" on public.cortes;
create policy "cortes_delete_own"
on public.cortes
for delete
to authenticated
using (auth.email() = user_email);

-- =========================
-- Tabela public.profiles
-- =========================
create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique,
  email text,
  nome text,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists nome text;
alter table public.profiles add column if not exists atualizado_em timestamptz not null default now();

create index if not exists idx_profiles_user_id on public.profiles (user_id);
create index if not exists idx_profiles_email on public.profiles (email);

create or replace function public.set_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

drop trigger if exists trg_profiles_updated_at on public.profiles;
create trigger trg_profiles_updated_at
before update on public.profiles
for each row execute function public.set_profiles_updated_at();

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
on public.profiles
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
on public.profiles
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
on public.profiles
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_delete_own"
on public.profiles
for delete
to authenticated
using (auth.uid() = user_id);

-- =========================
-- Storage bucket/policies
-- =========================
insert into storage.buckets (id, name, public)
values ('cortes', 'cortes', true)
on conflict (id) do update set public = excluded.public;

drop policy if exists "storage_cortes_select_public" on storage.objects;
create policy "storage_cortes_select_public"
on storage.objects
for select
to public
using (bucket_id = 'cortes');

drop policy if exists "storage_cortes_service_role_all" on storage.objects;
create policy "storage_cortes_service_role_all"
on storage.objects
for all
to service_role
using (bucket_id = 'cortes')
with check (bucket_id = 'cortes');
