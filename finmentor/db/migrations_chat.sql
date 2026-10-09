-- Run after migrations.sql and migrations_auth.sql.
-- Chat history: one conversation has many messages, scoped to the signed-in user.

create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    title text not null default 'New chat',
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    user_id uuid not null,
    role text not null,
    content text not null,
    grounded boolean,
    sources jsonb default '[]'::jsonb,
    created_at timestamptz default now()
);

create index if not exists conversations_user_updated_idx
    on conversations (user_id, updated_at desc);

create index if not exists messages_conversation_created_idx
    on messages (conversation_id, created_at);

notify pgrst, 'reload schema';
