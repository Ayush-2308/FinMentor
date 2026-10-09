-- Run this once in the Supabase SQL editor for the FinMentor project

-- 1. Enable pgvector extension
create extension if not exists vector;

-- 2. Documents table — metadata for each uploaded file
create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    filename text not null,
    doc_type_hint text,              -- bank_statement | insurance_policy | investment_record
    status text default 'processing', -- processing | indexed | failed
    chunks_count integer default 0,
    created_at timestamptz default now()
);

-- 3. Document chunks table — text chunks + embeddings for retrieval
-- NOTE: vector dimension below (1536) matches OpenAI text-embedding-3-small.
-- If you use a different embedding model, change the dimension to match it
-- (e.g. 768 for many Gemini embedding models).
create table if not exists document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references documents(id) on delete cascade,
    chunk_index integer not null,
    chunk_text text not null,
    embedding vector(1536),
    created_at timestamptz default now()
);

-- 4. Index for fast cosine-similarity search
create index if not exists document_chunks_embedding_idx
    on document_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- 5. Query log — optional, useful for debugging/demo-ing retrieval quality
create table if not exists queries_log (
    id uuid primary key default gen_random_uuid(),
    query_text text not null,
    document_id uuid references documents(id),
    answer text,
    retrieved_chunk_ids uuid[],
    created_at timestamptz default now()
);

-- 6. Helper function for similarity search (called from the backend)
create or replace function match_document_chunks (
    query_embedding vector(1536),
    match_count int default 5,
    filter_document_id uuid default null
)
returns table (
    id uuid,
    document_id uuid,
    chunk_text text,
    similarity float
)
language plpgsql
as $$
begin
    return query
    select
        document_chunks.id,
        document_chunks.document_id,
        document_chunks.chunk_text,
        1 - (document_chunks.embedding <=> query_embedding) as similarity
    from document_chunks
    where filter_document_id is null or document_chunks.document_id = filter_document_id
    order by document_chunks.embedding <=> query_embedding
    limit match_count;
end;
$$;
