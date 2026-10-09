-- Run once after migrations.sql. Ties each upload to the signed-in Supabase user
-- and stops match_document_chunks from searching someone else's files.

alter table documents add column if not exists user_id uuid;

create index if not exists documents_user_id_idx on documents (user_id);

-- New argument is last and optional, so older callers still parse.
create or replace function match_document_chunks (
    query_embedding vector(1536),
    match_count int default 5,
    filter_document_id uuid default null,
    filter_user_id uuid default null
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
    where (filter_document_id is null or document_chunks.document_id = filter_document_id)
      and (
        filter_user_id is null
        or exists (
            select 1
            from documents
            where documents.id = document_chunks.document_id
              and documents.user_id = filter_user_id
        )
      )
    order by document_chunks.embedding <=> query_embedding
    limit match_count;
end;
$$;

notify pgrst, 'reload schema';
