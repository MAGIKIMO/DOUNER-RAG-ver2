"""Expand search hits into document bodies before asking the LLM to answer."""
from types import SimpleNamespace
from sqlalchemy import select
from .db import Notice, session_scope


def with_attachments(documents, question, limit=8):
    """Attach relevant pages to parent hits, including graduation/latest routes."""
    import re
    from .db import Attachment, AttachmentPage
    if not documents:
        return []
    ids = {d.source_id for d in documents}
    with session_scope() as session:
        mappings = list(session.execute(select(AttachmentPage, Attachment).join(Attachment, Attachment.id == AttachmentPage.attachment_id)
                                        .where(AttachmentPage.notice_id.in_(ids))))
        matched = {p.notice_id: (p, a) for p, a in mappings}
        # A failed refresh must not silently present old attachment text as current.
        documents = [d for d in documents if d.source_id not in matched or matched[d.source_id][1].status in ('ok', 'partial')]
        parent_ids = {d.source_id for d in documents if d.source_type != 'attachment'}
        parent_ids.update(a.parent_id for p, a in mappings if a.status in ('ok', 'partial'))
        for parent in session.scalars(select(Notice).where(Notice.id.in_(parent_ids - ids))):
            documents.append(as_document(parent)); ids.add(parent.id)
        rows = list(session.execute(select(Notice, AttachmentPage, Attachment)
            .join(AttachmentPage, AttachmentPage.notice_id == Notice.id)
            .join(Attachment, Attachment.id == AttachmentPage.attachment_id)
            .where(Attachment.parent_id.in_(parent_ids), Attachment.status.in_(['ok', 'partial']))))
        terms = set(re.findall(r'[\w]{2,}', question.lower()))
        rows.sort(key=lambda row: (-sum(term in row[0].content.lower() for term in terms), row[1].page_number, row[0].id))
        added = 0
        for row, page, attachment in rows:
            if row.id not in ids and added < limit:
                documents.append(as_document(row)); ids.add(row.id); added += 1
        meta = {row.id: (page, attachment) for row, page, attachment in rows}
        parents = {row.id: row for row in session.scalars(select(Notice).where(Notice.id.in_(parent_ids)))}
        for doc in documents:
            if doc.source_id in meta:
                page, attachment = meta[doc.source_id]
                doc.attachment = {'filename': attachment.filename, 'page': page.page_number,
                                  'parent_url': parents[attachment.parent_id].url,
                                  'checked_at': attachment.checked_at.isoformat()+'Z' if attachment.checked_at else None}
                doc.url = attachment.url + f'#page={page.page_number}'
                if attachment.status == 'partial':
                    doc.chunk_text += '\n[이 파일에는 읽지 못한 페이지가 있습니다. 전체 조건을 확인했다고 단정하지 마세요.]'
    return documents


def body_excerpt(content, matches=(), limit=14000):
    if len(content) <= limit:
        return content
    # Include the beginning, ending notes and the neighborhood of each search hit.
    ranges = [(0, 3500), (len(content)-2000, len(content))]
    for match in matches:
        start = content.find(match)
        if start >= 0:
            ranges.append((max(0, start-1500), min(len(content), start+len(match)+2000)))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    parts = [content[start:end] for start, end in merged]
    result = '\n[중간 본문 생략]\n'.join(parts)
    # Search supplies at most a few short hits, but keep a firm request bound.
    return result[:limit] + '\n[발췌 문서: 제공되지 않은 구간의 조건은 확인되지 않음]'


def as_document(row, matches=()):
    return SimpleNamespace(source_id=row.id, source_type=row.source_type,
        category=row.category, title=row.title, url=row.url, published_at=row.published_at,
        checked_at=row.crawled_at.isoformat()+'Z' if row.crawled_at else None,
        chunk_text=body_excerpt(row.content, matches))


def expand_documents(chunks):
    grouped = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source_id, []).append(chunk)
    if not grouped:
        return []
    with session_scope() as session:
        rows = {row.id: row for row in session.scalars(select(Notice).where(Notice.id.in_(grouped)))}
    documents = []
    for source_id, hits in grouped.items():
        row = rows.get(source_id)
        # Recheck the version so an update between retrieval and expansion cannot
        # turn a stale match into evidence for different content.
        if row is None or any(hit.document_hash != row.content_hash for hit in hits):
            continue
        documents.append(as_document(row, [hit.chunk_text for hit in hits]))
    return documents
