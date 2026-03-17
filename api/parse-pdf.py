import json
import re
import io


def parse_cji3_text(text):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    skip_patterns = [
        r'^display actual cost', r'^layout\b', r'^object\b',
        r'^cost element\b', r'^posting date\b', r'^material description\b',
        r'^\*\*', r'^page\s+\d+', r'^\d{2}\.\d{2}\.\d{4}\s+display',
    ]
    mat_code_re = re.compile(r'\b(2\d{9})\b')
    date_re     = re.compile(r'\b(\d{2})\.(\d{2})\.(\d{4})\b')
    wbs_re      = re.compile(r'\b([A-Z0-9]{5,}(?:-[A-Z0-9]+)+)\b')
    aggregated  = {}

    for line in lines:
        if re.match(r'^\*', line): continue
        if any(re.match(p, line, re.IGNORECASE) for p in skip_patterns): continue
        cm = mat_code_re.search(line)
        if not cm: continue
        sap_code = cm.group(1)
        desc = line[:cm.start()].strip().rstrip(',').strip()
        if not desc or len(desc) < 3: continue
        after = line[cm.end():]
        qm = re.search(r'\s+([\d,]+(?:\.\d+)?)(-)?\s', ' ' + after + ' ')
        if not qm: continue
        qty_val = float(qm.group(1).replace(',', ''))
        signed  = -qty_val if qm.group(2) == '-' else qty_val
        dm = date_re.search(after)
        posting_date = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}" if dm else ''
        wm  = wbs_re.search(after)
        wbs = wm.group(1) if wm else ''
        if sap_code in aggregated:
            aggregated[sap_code]['qty'] += signed
            if len(desc) > len(aggregated[sap_code]['desc']): aggregated[sap_code]['desc'] = desc
            if posting_date: aggregated[sap_code]['date'] = posting_date
        else:
            aggregated[sap_code] = {'desc': desc, 'qty': signed, 'wbs': wbs, 'date': posting_date, 'code': sap_code}

    return [{'description': e['desc'], 'sapCode': e['code'], 'qty': abs(e['qty']),
             'wbs': e['wbs'], 'postingDate': e['date'], 'docText': ''}
            for e in aggregated.values() if abs(e['qty']) > 0.0001]


def handler(request):
    cors = {'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'}

    if request.method == 'OPTIONS':
        return Response('', 200, headers=cors)

    if request.method != 'POST':
        return Response(json.dumps({'error': 'Method not allowed'}), 405,
                        headers={**cors, 'Content-Type': 'application/json'})
    try:
        import pdfplumber
    except ImportError:
        return Response(json.dumps({'error': 'pdfplumber not installed'}), 500,
                        headers={**cors, 'Content-Type': 'application/json'})
    try:
        if 'file' not in request.files:
            return Response(json.dumps({'error': 'No file field in form data'}), 400,
                            headers={**cors, 'Content-Type': 'application/json'})
        pdf_bytes = request.files['file'].read()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = '\n'.join(filter(None, (p.extract_text() for p in pdf.pages)))
        entries = parse_cji3_text(full_text)
        body = json.dumps({'entries': entries})
        return Response(body, 200, headers={**cors, 'Content-Type': 'application/json'})
    except Exception as e:
        body = json.dumps({'error': str(e)})
        return Response(body, 500, headers={**cors, 'Content-Type': 'application/json'})
