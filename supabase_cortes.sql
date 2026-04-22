create extension if not exists pgcrypto;

create table if not exists public.cortes (
    id uuid primary key default gen_random_uuid(),
    user_email text not null,
    video_url text not null,
    titulo text not null,
    criado_em timestamptz not null default now()
);

create index if not exists idx_cortes_user_email on public.cortes (user_email);
create index if not exists idx_cortes_criado_em on public.cortes (criado_em desc);

alter table public.cortes enable row level security;

do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'cortes' and policyname = 'Usuarios veem os proprios cortes'
    ) then
        create policy "Usuarios veem os proprios cortes"
        on public.cortes
        for select
        to authenticated
        using (auth.email() = user_email);
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public' and tablename = 'cortes' and policyname = 'Usuarios inserem os proprios cortes'
    ) then
        create policy "Usuarios inserem os proprios cortes"
        on public.cortes
        for insert
        to authenticated
        with check (auth.email() = user_email);
    end if;
end $$;
