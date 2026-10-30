"""Heading-aware child chunks and bounded parent-section context, without new tables."""
import re
from rag_app.store import split_text

SECTION=re.compile(r'(?:^|; )section (\d+):')


def search_rows(rows):
    result=[]
    for row in rows:
        match=re.search(r'section \d+: ([^;]+);',row['location'])
        result.append(dict(row,title=row['title']+' '+match.group(1)) if match else row)
    return result


def split_sections(text,max_chars=500):
    lines=text.splitlines()
    headings=[i for i,line in enumerate(lines) if re.match(r'^#{1,6}\s+\S',line)]
    if not headings:
        return split_text(text,max_chars)
    blocks=[];start=0;title='正文';number=0
    for i,line in enumerate(lines):
        if re.match(r'^#{1,6}\s+\S',line):
            if i>start and '\n'.join(lines[start:i]).strip():
                blocks.append((number,title,start,lines[start:i]))
            number+=1;title=re.sub(r'^#{1,6}\s+','',line).strip().replace(';',',')[:120]
            start=i
    if start<len(lines):blocks.append((number,title,start,lines[start:]))
    chunks=[]
    for index,heading,offset,block in blocks:
        for location,part in split_text('\n'.join(block),max_chars):
            match=re.fullmatch(r'lines (\d+)-(\d+)',location)
            first,last=(int(x)+offset for x in match.groups())
            chunks.append((f'section {index}: {heading}; lines {first}-{last}',part))
    return chunks


def section_identity(row):
    match=SECTION.search(row['location'])
    if match:
        page=re.search(r'page (\d+)',row['location'])
        return (row['document_id'],row['version'],page.group(1) if page else '',match.group(1))
    return None


def expand_sections(store,actor,hits,max_chunks=8,max_chars=2400):
    """Keep hits first; add only accessible siblings from their same version/section."""
    identities={section_identity(row) for row in hits}-{None}
    if not identities:
        return hits,[]
    candidates=[c for c in store.authorized_chunks(actor) if section_identity(c) in identities]
    def line_order(row):
        match=re.search(r'lines (\d+)',row['location'])
        return row['document_id'],row['version'],int(match.group(1)) if match else 0
    candidates.sort(key=line_order)
    selected=list(hits);seen={c['chunk_id'] for c in hits};size=sum(len(c['text']) for c in hits);added=[]
    for row in candidates:
        if row['chunk_id'] in seen:continue
        if len(selected)>=max(max_chunks,len(hits)) or size+len(row['text'])>max_chars:continue
        fresh=store.citation(row['chunk_id'],actor)
        selected.append(fresh);seen.add(row['chunk_id']);size+=len(row['text']);added.append(row['chunk_id'])
    return selected,added
