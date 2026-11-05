"""Local, provenance-first extraction candidates for configurable quotation requirements.

The heuristic confidence score describes match strength. It is NOT a calibrated
probability of correctness and never substitutes for an engineer's verification.
No cloud/model API calls are made from this module.
"""
from __future__ import annotations
import io
import re
from decimal import Decimal, InvalidOperation
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
from pypdf import PdfReader

VALUE = r'(?P<value>\d{1,8}(?:[.,]\d{1,4})?)'
UNIT = r'(?P<unit>m\s*/\s*min|mm|millimet(?:er|re)s?|cm|mtr\.?|met(?:er|re)s?|m\b|tonnes?|tons?|t\b|te\b|kgs?|kg\b|kw|hp)'
UNIT_PATTERN = r'(?:m\s*/\s*min|mm|millimet(?:er|re)s?|cm|mtr\.?|met(?:er|re)s?|m\b|tonnes?|tons?|t\b|te\b|kgs?|kg\b|kw|hp)'


def local_document_text(name: str, data: bytes, max_pages: int = 60):
    """Return (pages, kind); .docx has a logical section, not physical page numbers."""
    low = name.lower()
    if low.endswith('.pdf'):
        if not data.startswith(b'%PDF-'):
            raise ValueError('PDF signature missing')
        reader = PdfReader(io.BytesIO(data), strict=False)
        if len(reader.pages) > max_pages:
            raise ValueError('PDF exceeds page limit')
        return [(page.extract_text() or '') for page in reader.pages], 'PDF'
    if low.endswith('.docx'):
        if not data.startswith(b'PK'):
            raise ValueError('DOCX signature missing')
        try:
            with ZipFile(io.BytesIO(data)) as z:
                if 'word/document.xml' not in z.namelist():
                    raise ValueError('Invalid DOCX structure')
                xml = z.read('word/document.xml')
        except BadZipFile as exc:
            raise ValueError('Invalid DOCX archive') from exc
        root = ET.fromstring(xml)
        uri='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        # Keep Word paragraph and table-cell order; no claim of printed page fidelity.
        lines=[]
        for para in root.iter(uri+'p'):
            txt=''.join(t.text or '' for t in para.iter(uri+'t'))
            if txt.strip(): lines.append(txt.strip())
        return ['\n'.join(lines)], 'DOCX'
    raise ValueError('Only text PDFs and DOCX are supported by this parser')


def _unit_code(s):
    s=re.sub(r'\s+','',str(s or '').lower().strip('.'))
    if s in ('mm','millimeter','millimeters','millimetre','millimetres'):return 'mm'
    if s in ('cm',):return 'cm'
    if s in ('m','mtr','meter','meters','metre','metres'):return 'm'
    if s in ('kg','kgs'):return 'kg'
    if s in ('t','te','ton','tons','tonne','tonnes'):return 't'
    if s in ('hp',):return 'hp'
    if s in ('kw',):return 'kW'
    if s in ('m/min',):return 'm/min'
    return s


def normalize(number: str, actual_unit: str, expected_unit: str):
    raw = str(number).replace(',','')
    try: d = Decimal(raw)
    except InvalidOperation:return None
    src=_unit_code(actual_unit)
    dst=_unit_code(expected_unit)
    if dst and src and src!=dst:
        factors={('mm','m'):Decimal('.001'),('cm','m'):Decimal('.01'),('m','mm'):Decimal('1000'),('cm','mm'):Decimal('10'),('t','kg'):Decimal('1000'),('kg','t'):Decimal('.001')}
        if (src,dst) not in factors:return None
        d=d*factors[(src,dst)]
    elif dst and not src:
        # Missing source units: numeric value can be read but unit is ambiguous.
        return raw
    return format(d.normalize(), 'f')


def _evidence(page, start, end):
    # Surrounding text helps a reviewer locate the candidate; never claim page coordinates.
    return re.sub(r'\s+',' ',page[max(0,start-35):min(len(page),end+65)]).strip()[:230]


def _aliases_for(field):
    a=[]
    for x in [field.get('label'),field.get('key','').replace('_',' ')] + list(field.get('aliases',[])):
        x=str(x or '').strip()
        if x and x.lower() not in {y.lower() for y in a}:a.append(x)
    return a


def _expression(alias):
    # Escaped literal words, not arbitrary runtime regex from customer configuration.
    pieces=[re.escape(t) for t in re.split(r'\s+',alias.strip()) if t]
    return r'\s+'.join(pieces)


# Generic visible workflow hints: never interpreted as proved manufacturing hours or BOM.
OPERATION_ALIASES = {
    'cut': ('cutting', 'cut list', 'cut to length', 'saw cut'),
    'weld': ('welding', 'welded', 'full weld', 'weld joints'),
    'paint': ('painting', 'primer', 'enamel paint', 'powder coating'),
    'assemble': ('assembly', 'assembling', 'fabrication assembly'),
    'erect': ('erection', 'installation on site'),
    'commission': ('commissioning',),
    'inspect': ('inspection', 'quality check', 'visual inspection'),
    'repair': ('rewinding', 'repair work', 'repairing'),
    'machine': ('machining', 'lathe machining'),
    'fit': ('refitting', 'refixing'),
    'test': ('load testing', 'test run', 'performance testing'),
}

def extract_candidates(pages, config, catalogue=(), source_kind='PDF'):
    """Config-specific aliases, generic extraction; returns *unverified* candidates.

    Scores are heuristic priorities for review (0 to 99), not probabilities.
    """
    found=[]
    fields=list(config.get('required_fields',[]))
    field_keys={f.get('key') for f in fields}
    for section in config.get('specification_sections',[]):
        for field in section.get('fields',[]):
            if field.get('key') and field['key'] not in field_keys:
                fields.append(field)
                field_keys.add(field['key'])
    for page_idx,page in enumerate(pages):
        if not page.strip(): continue
        for f in fields:
            target=f.get('key')
            u=f.get('unit') or ''
            typ=f.get('extraction_type') or ('number' if u else 'text')
            if typ not in ('number','text'):continue
            if typ=='text':
                # Short, explicit key-value strings. Never infer values from arbitrary prose.
                # A single-space separation may be ambiguous: score lower and require review.
                for alias in _aliases_for(f):
                    a=_expression(alias)
                    for match in re.finditer(rf'(?im)^[ \t]*{a}[ \t]*(?::|=|[ \t]{{2,}})[ \t]*(?P<content>[^\n]{{2,120}})[ \t]*$',page):
                        value=match.group('content').strip()
                        if value:
                            found.append({'kind':'field','key':target,'value':value,'raw_value':value,
                                'raw_unit':'','unit':'','page':page_idx+1,
                                'source_location':f'{source_kind} '+('page' if source_kind=='PDF' else 'logical section')+f' {page_idx+1}',
                                'evidence':_evidence(page,match.start(),match.end()),'method':'LOCAL_RULES',
                                'confidence_score':72,'confidence':72,
                                'confidence_kind':'HEURISTIC_MATCH_STRENGTH_NOT_PROBABILITY',
                                'confidence_basis':'EXPLICIT_TEXT_LABEL_UNVERIFIED',
                                'review_status':'UNVERIFIED','verified':False})
                continue
            for alias in _aliases_for(f):
                # "span 40 m" (and table cells rendered as lines).
                a=_expression(alias)
                direct=rf'(?<!\w){a}(?!\w)[ \t]*[:=\-]?[ \t]*(?:\n[ \t]*)?{VALUE}[ \t]*{UNIT}?'
                reverse=rf'(?<![/\d]){VALUE}[ \t]*{UNIT_PATTERN}[ \t]+(?<!\w){a}(?!\w)'
                for orientation,pat in [('LABEL_THEN_VALUE',direct),('VALUE_THEN_LABEL',reverse)]:
                    for match in re.finditer(pat,page,flags=re.I):
                        # Avoid interpreting the NEXT value as a direct-label value
                        # after an already completed reversed label (e.g. "6 mtr Lift\n8.6 mtr Span").
                        if orientation=='LABEL_THEN_VALUE' and '\n' in match.group(0):
                            line_prefix=page[page.rfind('\n',0,match.start())+1:match.start()].strip()
                            if line_prefix:continue
                        # Literal alias can be embedded in a longer qualified label.
                        # A config may specify disallowed prefixes to keep distinct concepts
                        # such as hoist headroom and *minimum* crane headroom separate.
                        if orientation=='LABEL_THEN_VALUE' and f.get('exclude_prefixes'):
                            prefix=page[page.rfind('\n',0,match.start())+1:match.start()].rstrip().lower()
                            if any(re.sub(r'\s+','',prefix).endswith(re.sub(r'\s+','',str(x).lower())) for x in f['exclude_prefixes']):continue
                        raw_unit=match.groupdict().get('unit') or ''
                        normalized=normalize(match.group('value'),raw_unit,u)
                        if normalized is None:continue
                        score=(96 if raw_unit else 77) if orientation=='LABEL_THEN_VALUE' else 85
                        if u and not raw_unit:score=min(score,74)
                        found.append({
                            'kind':'field','key':target,'value':normalized,'raw_value':match.group('value'),
                            'raw_unit':raw_unit,'unit':u or raw_unit,'page':page_idx+1,
                            'source_location':f'{source_kind} '+('page' if source_kind=='PDF' else 'logical section')+f' {page_idx+1}',
                            'evidence':_evidence(page,match.start(),match.end()),'method':'LOCAL_RULES',
                            'confidence_score':score,'confidence':score,'confidence_kind':'HEURISTIC_MATCH_STRENGTH_NOT_PROBABILITY','confidence_basis':orientation+('_EXPLICIT_UNIT' if raw_unit else '_UNIT_MISSING'),
                            'review_status':'UNVERIFIED', 'verified':False,
                        })
        # Match only explicit source operation words. Suggest operations for review;
        # never auto-assign quantities, labour time, rates or approval.
        for code, aliases in OPERATION_ALIASES.items():
            for alias in aliases:
                match=re.search(r'(?i)(?<!\w)'+re.escape(alias)+r'(?!\w)',page)
                if not match:continue
                found.append({'kind':'operation','code':code,'key':code,
                    'value':alias.title(),'description':alias.title(),
                    'page':page_idx+1,'source_location':source_kind+(' page ' if source_kind=='PDF' else ' logical section ')+str(page_idx+1),
                    'evidence':_evidence(page,match.start(),match.end()),'method':'LOCAL_OPERATION_KEYWORD',
                    'confidence_score':70,'confidence':70,'confidence_kind':'HEURISTIC_MATCH_STRENGTH_NOT_PROBABILITY',
                    'confidence_basis':'EXPLICIT_WORD_ONLY_NO_TIME_OR_RATE','review_status':'UNVERIFIED',
                    'verified':False,'hours':None,'rate':None})
                break
        # Product-independent material text hints from the organization's catalogue.
        for entry in catalogue:
            aliases=entry.get('aliases',[]) or []
            for alias in aliases:
                if not alias or len(alias)>90:continue
                match=re.search(re.escape(alias),page,re.I)
                if match:
                    found.append({'kind':'material','sku':entry['sku'],'value':alias,'page':page_idx+1,
                        'evidence':_evidence(page,match.start(),match.end()),'method':'LOCAL_LITERAL_MATCH',
                        'confidence_score':88,'confidence':88,'confidence_kind':'HEURISTIC_MATCH_STRENGTH_NOT_PROBABILITY','confidence_basis':'MATERIAL_NAME_MATCH_ONLY_QUANTITY_UNKNOWN',
                        'review_status':'UNVERIFIED','verified':False})
                    break
    # Same field and value on different pages matter (we want contradictory source evidence).
    dedup=[];seen=set()
    for f in found:
        identity=(f.get('kind'),f.get('key') or f.get('sku'),f.get('value'),f.get('page'),f.get('evidence'))
        if identity not in seen:
            seen.add(identity);dedup.append(f)
        if len(dedup)>=250:break
    return dedup


def conflicts_from_docs(docs):
    by={}
    for doc in docs:
        for c in doc.get('candidates',[]):
            if c.get('kind')!='field':continue
            key=c.get('key')
            if not key:continue
            by.setdefault(key,{}).setdefault(str(c.get('value','')).strip().lower(),[]).append({
                'value':c['value'],'document_id':doc['id'],'document':doc['original_name'],
                'page':c.get('page'),'confidence_score':c.get('confidence_score'),
                'evidence':c.get('evidence')})
    return [{'key':key,'values':[{ 'value':v,'sources':src} for v,src in grouped.items()],
             'severity':'BLOCKING','status':'UNRESOLVED','message':'Different source values require explicit engineer resolution'}
            for key,grouped in by.items() if len(grouped)>1]
