create table if not exists public.user_subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    provider text not null default 'mercado_pago',
    provider_subscription_id text not null,
    plan text not null default 'plus',
    status text not null default 'pending',
    current_period_end timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint user_subscriptions_provider_check
        check (provider in ('mercado_pago')),
    constraint user_subscriptions_plan_check
        check (plan in ('plus')),
    constraint user_subscriptions_status_check
        check (status in ('pending', 'active', 'paused', 'cancelled')),
    constraint user_subscriptions_provider_subscription_unique
        unique (provider, provider_subscription_id)
);

create index if not exists user_subscriptions_user_id_idx
    on public.user_subscriptions(user_id);

create index if not exists user_subscriptions_provider_subscription_idx
    on public.user_subscriptions(provider, provider_subscription_id);
