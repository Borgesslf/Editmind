-- EditMind v5.2 - Profiles
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique,
  email text,
  nome text,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

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

-- leitura/escrita do próprio usuário em cenários sem service role
create policy if not exists "profiles_select_own"
on public.profiles
for select
using (auth.uid() = user_id);

create policy if not exists "profiles_insert_own"
on public.profiles
for insert
with check (auth.uid() = user_id);

create policy if not exists "profiles_update_own"
on public.profiles
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
