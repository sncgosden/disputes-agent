"""Capture published guidance locally and retrieve verifiable source passages."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / 'corpus'
ALLOWED_HOSTS = {'docs.stripe.com', 'www.visa.ie', 'www.mastercard.com'}


class SourceRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError('Unexpected source redirect; review the source URL before allowing it.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())


CHUNKING_VERSION = '2'
CHUNK_SIZE, CHUNK_STEP = 1200, 1000
HEADING_LEAD = 200  # a heading this close to a passage's start governs the passage
NETWORK_HEADINGS = {'visa': 'visa', 'mastercard': 'mastercard', 'paypal': 'paypal',
                    'american express': 'amex', 'amex': 'amex', 'discover': 'discover'}


def page_texts(raw):
    """Return (pdf_page_number or None, text) pairs exactly as extracted."""
    if raw.startswith(b'%PDF'):
        from pypdf import PdfReader
        return [(i + 1, p.extract_text() or '') for i, p in enumerate(PdfReader(io.BytesIO(raw)).pages)]
    text = raw.decode('utf-8')
    if re.match(r'\s*<!doctype html|\s*<html', text, re.I):
        raise ValueError('Expected markdown, received HTML; source needs an explicit extraction adapter')
    return [(None, text)]


def chunk_source(source, raw, digest):
    """Split one captured source into citable passages with applicability metadata.

    Metadata comes from guidance-sources.json: network (visa, mastercard or null for
    provider-wide guidance), page_label_pattern (printed page number in the footer),
    heading_pattern (reason-code sections such as Visa dispute conditions) and
    section_pattern (chapter headings that end a reason-code section).
    """
    pages = page_texts(raw)
    if not any(text.strip() for _, text in pages):
        raise ValueError('No extractable text')
    label_re = re.compile(source['page_label_pattern']) if source.get('page_label_pattern') else None
    heading_re = re.compile(source['heading_pattern']) if source.get('heading_pattern') else None
    section_re = re.compile(source['section_pattern']) if source.get('section_pattern') else None
    chunks, carried = [], None
    for page, text in pages:
        label = None
        if label_re:
            found = list(label_re.finditer(text))
            label = next((g for g in found[-1].groups() if g), None) if found else None
        if heading_re or section_re:
            marks = [(m.start(), ' '.join(m.group(0).split()), m.groupdict().get('code')) for m in heading_re.finditer(text)] if heading_re else []
            # A new chapter ends the previous reason-code section.
            marks += [(m.start(), ' '.join(m.group(0).split()), None) for m in section_re.finditer(text)] if section_re else []
            marks.sort()
        elif page is None:
            marks = [(m.start(), m.group(1).strip(), None) for m in re.finditer(r'^#{1,4}\s+(.+)$', text, re.M)]
        else:
            marks = []
        for start in range(0, len(text), CHUNK_STEP):
            passage = text[start:start + CHUNK_SIZE]
            if not passage.strip():
                continue
            # Heading in force at the start of the passage, carried across pages.
            current = carried
            for pos, title, code in marks:
                if pos <= start + HEADING_LEAD:
                    current = (title, code)
            heading = current[0] if current else None
            # Provider pages often split by network under plain headings ("Visa", "Paypal").
            # "section": the network applies only within that heading's section.
            # "carry": it stays in force through sub-headings until the next network heading
            # or a configured reset heading (pages laid out as network tabs).
            network = source.get('network') or NETWORK_HEADINGS.get((heading or '').strip().lower())
            if not source.get('network') and source.get('network_heading_mode') == 'carry':
                resets = {h.lower() for h in source.get('network_reset_headings', [])}
                carried_network = None
                for pos, title, _ in marks:
                    if pos > start + HEADING_LEAD:
                        break
                    key = title.strip().lower()
                    if key in NETWORK_HEADINGS:
                        carried_network = NETWORK_HEADINGS[key]
                    elif key in resets:
                        carried_network = None
                network = carried_network
            # Contents and index pages: many dot leaders ending in page numbers.
            navigation = len(re.findall(r'\.{6,}\s*\d+', passage)) >= 3
            chunks.append({'id': f"{source['id']}:{digest[:12]}:{page or 'text'}:{start}",
                'source_id': source['id'], 'source_url': source['url'], 'version_sha256': digest,
                'page': page, 'page_label': label, 'start': start, 'end': start + len(passage),
                'kind': source['kind'], 'network': network, 'navigation': navigation,
                'heading': heading, 'reason_code': current[1] if current else None,
                'text': passage, 'effective_date': None, 'chunking_version': CHUNKING_VERSION})
        if marks:
            carried = (marks[-1][1], marks[-1][2])
    return chunks


def write_corpus(report, chunks, label):
    run = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (CORPUS / f'manifest-{label}-{run}.json').write_text(json.dumps(report, indent=2))
    (CORPUS / f'chunks-{label}-{run}.json').write_text(json.dumps(chunks))
    # Replace the active corpus only after a complete run; older versions are retained.
    if report['complete']:
        (CORPUS / 'manifest.json').write_text(json.dumps(report, indent=2))
        (CORPUS / 'chunks.json').write_text(json.dumps(chunks))
    counts = Counter(c['source_id'] for c in chunks)
    print(json.dumps({'complete': report['complete'], 'sources': len(report['sources']), 'chunks': len(chunks),
                      'chunks_by_source': dict(counts), 'failures': report['failures']}, indent=2))
    if not report['complete']:
        raise SystemExit(1)


def capture():
    sources = json.loads((ROOT / 'guidance-sources.json').read_text())
    CORPUS.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(SourceRedirects())
    manifest, chunks, failures = [], [], []
    for source in sources:
        try:
            parsed = urllib.parse.urlparse(source['url'])
            if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
                raise ValueError('Source outside allowlist')
            request = urllib.request.Request(source['url'], headers={'User-Agent': 'DisputesAgentSourceCapture/1.0', 'Accept': 'text/markdown,application/pdf'})
            with opener.open(request, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                content_type = response.headers.get('Content-Type', '')
                resolved_url = response.url
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError('Source exceeds configured size limit')
            if 'text/html' in content_type:
                raise ValueError('Expected markdown, received HTML; source needs an explicit extraction adapter')
            digest = hashlib.sha256(raw).hexdigest()
            target = CORPUS / (source['id'] + '-' + digest[:12] + ('.pdf' if raw.startswith(b'%PDF') else '.md'))
            target.write_bytes(raw)
            source_chunks = chunk_source(source, raw, digest)
            chunks.extend(source_chunks)
            manifest.append({**source, 'resolved_url': resolved_url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                     'sha256': digest, 'content_type': content_type, 'effective_date': None, 'raw_file': target.name,
                     'text_characters': sum(c['end'] - c['start'] for c in source_chunks),
                     'instruction_trust': 'untrusted_reference_content'})
        except Exception as error:
            failures.append({'source_id': source['id'], 'error_type': type(error).__name__, 'error': str(error)})
    report = {'sources': manifest, 'failures': failures, 'chunking_version': CHUNKING_VERSION,
              'captured_at': datetime.now(timezone.utc).isoformat(),
              'complete': not failures and len(manifest) == len(sources)}
    write_corpus(report, chunks, 'capture')


def rebuild():
    """Re-chunk the already captured bytes with current metadata rules. No download."""
    current = json.loads((CORPUS / 'manifest.json').read_text())
    config = {s['id']: s for s in json.loads((ROOT / 'guidance-sources.json').read_text())}
    manifest, chunks, failures = [], [], []
    for entry in current['sources']:
        try:
            raw = (CORPUS / entry['raw_file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('Captured bytes no longer match their recorded hash')
            # Chunking metadata may change; captured bytes, URL and version may not.
            merged = {**entry, **{k: v for k, v in config.get(entry['id'], {}).items() if k not in ('url',)}}
            chunks.extend(chunk_source(merged, raw, entry['sha256']))
            manifest.append(merged)
        except Exception as error:
            failures.append({'source_id': entry['id'], 'error_type': type(error).__name__, 'error': str(error)})
    report = {**current, 'sources': manifest, 'failures': failures, 'chunking_version': CHUNKING_VERSION,
              'rebuilt_at': datetime.now(timezone.utc).isoformat(),
              'complete': not failures and len(manifest) == len(current['sources'])}
    write_corpus(report, chunks, 'rebuild')


def applicable(chunk, network=None, kind=None, reason_code=None):
    """Applicability filter applied before ranking.

    Contents and index passages are excluded.
    Provider and API guidance (network null) applies to every network. Scheme guidance
    applies only to its own network. A reason-code filter keeps passages for that code
    plus passages with no code (general guidance).
    """
    if chunk.get('navigation'):
        return False  # contents pages match many words but contain no guidance
    if kind and chunk['kind'] not in kind:
        return False
    if network and chunk.get('network') not in (None, network):
        return False
    if reason_code and chunk.get('reason_code') not in (None, reason_code):
        return False
    return True


def search(query, limit=5, network=None, kind=None, reason_code=None):
    chunks = [c for c in json.loads((CORPUS / 'chunks.json').read_text()) if applicable(c, network, kind, reason_code)]
    q = set(tokens(query))
    counters = [Counter(tokens(c['text'])) for c in chunks]
    lengths = [sum(c.values()) for c in counters]
    avg = sum(lengths) / max(1, len(lengths))
    frequencies = {t: sum(t in c for c in counters) for t in q}
    ranked = []
    for chunk, counts, length in zip(chunks, counters, lengths):
        score = 0.0
        for term in q:
            tf = counts[term]
            if tf:
                idf = math.log(1 + (len(chunks) - frequencies[term] + .5) / (frequencies[term] + .5))
                score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / max(avg, 1)))
        if score:
            ranked.append({**chunk, 'score': round(score, 3)})
    return sorted(ranked, key=lambda c: c['score'], reverse=True)[:limit]


def corpus_version(manifest):
    """One identifier for the exact set of source versions an evaluation used."""
    parts = sorted(f"{s['id']}={s['sha256']}" for s in manifest['sources'])
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def complete_captures():
    found = []
    for path in CORPUS.glob('manifest-*.json'):
        report = json.loads(path.read_text())
        if report.get('complete') and 'rebuild' not in path.name:
            found.append((capture_time(report.get('captured_at', '')), path, report))
    return sorted(found, key=lambda item: item[0])


def capture_time(value):
    # Early captures used a compact timestamp; later ones use ISO 8601.
    try:
        return datetime.strptime(value, '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromisoformat(value)


def compare(previous=None, current=None):
    """Compare two complete captures source by source; default is the latest two."""
    captures = complete_captures()
    if len(captures) < 2 and not (previous and current):
        raise SystemExit('Need two complete captures to compare; run fetch again first.')
    old = json.loads(Path(previous).read_text()) if previous else captures[-2][2]
    new = json.loads(Path(current).read_text()) if current else captures[-1][2]
    before = {s['id']: s for s in old['sources']}
    after = {s['id']: s for s in new['sources']}
    rows = []
    for source_id in sorted(set(before) | set(after)):
        a, b = before.get(source_id), after.get(source_id)
        if not a:
            status = 'added'
        elif not b:
            status = 'removed'
        elif a['sha256'] == b['sha256']:
            status = 'unchanged'
        else:
            status = 'changed'
        rows.append({'source_id': source_id, 'status': status,
                     'previous_version': a['sha256'][:12] if a else None, 'current_version': b['sha256'][:12] if b else None,
                     'edition_record_changed': bool(a and b and a.get('edition') != b.get('edition')),
                     'previous_edition': a.get('edition') if a else None, 'current_edition': b.get('edition') if b else None})
    return {'previous_capture': old.get('captured_at'), 'current_capture': new.get('captured_at'),
            'previous_corpus_version': corpus_version(old)[:16], 'current_corpus_version': corpus_version(new)[:16],
            'summary': dict(Counter(r['status'] for r in rows)), 'sources': rows,
            'retained': 'Older raw files and passage sets stay in corpus/ so saved evaluation runs remain reproducible.'}


def summarise(results):
    return [{'rank': i + 1, 'score': r['score'], 'source_id': r['source_id'], 'network': r.get('network'),
             'pdf_page': r['page'], 'printed_page': r.get('page_label'), 'heading': r.get('heading'),
             'reason_code': r.get('reason_code'), 'id': r['id'], 'preview': ' '.join(r['text'].split())[:140]}
            for i, r in enumerate(results)]


def verify(citation):
    manifest = json.loads((CORPUS / 'manifest.json').read_text())
    chunks = json.loads((CORPUS / 'chunks.json').read_text())
    found = next((c for c in chunks if c['id'] == citation), None)
    if not found:
        raise ValueError('Unknown passage ID')
    source = next(s for s in manifest['sources'] if s['id'] == found['source_id'])
    try:
        raw = (CORPUS / source['raw_file']).read_bytes()
    except FileNotFoundError:
        raise ValueError('Source file unavailable') from None
    if hashlib.sha256(raw).hexdigest() != found['version_sha256']:
        raise ValueError('Source bytes changed')
    if raw.startswith(b'%PDF'):
        from pypdf import PdfReader
        text = PdfReader(io.BytesIO(raw)).pages[found['page'] - 1].extract_text() or ''
    else:
        text = raw.decode('utf-8')
    if text[found['start']:found['end']] != found['text']:
        raise ValueError('Passage does not match source')
    return {'citation': citation, 'verified': True, 'source_url': found['source_url'], 'version': found['version_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('fetch')
    subs.add_parser('rebuild')
    query = subs.add_parser('search'); query.add_argument('query'); query.add_argument('--limit', type=int, default=5)
    query.add_argument('--network', choices=['visa', 'mastercard']); query.add_argument('--kind', nargs='+', choices=['provider', 'api', 'scheme'])
    query.add_argument('--reason-code'); query.add_argument('--full', action='store_true', help='Print full passages instead of a summary')
    citation = subs.add_parser('verify'); citation.add_argument('citation')
    show = subs.add_parser('show', help='Print one passage with its source details'); show.add_argument('passage_id')
    diff = subs.add_parser('compare', help='Compare the two most recent complete captures')
    diff.add_argument('--previous'); diff.add_argument('--current')
    args = parser.parse_args()
    if args.command == 'fetch': capture()
    elif args.command == 'rebuild': rebuild()
    elif args.command == 'search':
        results = search(args.query, args.limit, args.network, args.kind, args.reason_code)
        print(json.dumps(results if args.full else summarise(results), indent=2))
    elif args.command == 'compare': print(json.dumps(compare(args.previous, args.current), indent=2))
    elif args.command == 'show':
        found = next((c for c in json.loads((CORPUS / 'chunks.json').read_text()) if c['id'] == args.passage_id), None)
        if not found:
            raise SystemExit('Unknown passage ID')
        print(f"{found['source_id']} | network {found.get('network')} | heading {found.get('heading')} | "
              f"PDF page {found['page']} | printed page {found.get('page_label')}\n{found['source_url']}\n\n{found['text']}")
    else: print(json.dumps(verify(args.citation), indent=2))
