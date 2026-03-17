from http.server import BaseHTTPRequestHandler
import json, re, io, cgi

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


def parse_cji3_text(text):
    """Parse extracted CJI3 text into structured material entries."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    skip_patterns = [
        r'^display actual cost',
        r'^layout\b',
        r'^object\b',
        r'^cost element\b',
        r'^posting date\b',
        r'^material description\b',
        r'^\*\*',          # grand totals
        r'^\d{2}\.\d{2}\.\d{4}\s+display',
        r'^page\s+\d+',
    ]

    mat_code_re  = re.compile(r'\b(2\d{9})\b')
    date_re      = re.compile(r'\b(\d{2})\.(\d{2})\.(\d{4})\b')
    wbs_re       = re.compile(r'\b([A-Z0-9]{4,}[A-Z0-9\-]{2,}(?:-MAT|-[A-Z]+)?)\b')

    aggregated = {}   # sapCode -> {desc, qty_signed, wbs, postingDate}

    for line in lines:
        # Skip subtotal lines (* prefix)
        if re.match(r'^\*', line):
            continue
        # Skip header/filter lines
        if any(re.match(p, line, re.IGNORECASE) for p in skip_patterns):
            continue

        code_match = mat_code_re.search(line)
        if not code_match:
            continue
        sap_code = code_match.group(1)

        # Description = everything before the SAP code
        desc = line[:code_match.start()].strip().rstrip(',').strip()
        if not desc or len(desc) < 3:
            continue

        # Quantity: number immediately after SAP code, with optional trailing minus
        after_code = line[code_match.end():]
        qty_match = re.search(r'[\s,](\d{1,3}(?:,\d{3})*(?:\.\d+)?)(-)?\s', after_code + ' ')
        if not qty_match:
            continue
        qty_val = float(qty_match.group(1).replace(',', ''))
        is_neg  = qty_match.group(2) == '-'
        signed_qty = -qty_val if is_neg else qty_val

        # Date
        date_match = date_re.search(after_code)
        posting_date = ''
        if date_match:
            posting_date = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"

        # WBS (after SAP code)
        wbs_match = wbs_re.search(after_code)
        wbs = wbs_match.group(1) if wbs_match else ''

        if sap_code in aggregated:
            aggregated[sap_code]['qty_signed'] += signed_qty
            if len(desc) > len(aggregated[sap_code]['desc']):
                aggregated[sap_code]['desc'] = desc
            if posting_date:
                aggregated[sap_code]['postingDate'] = posting_date
        else:
            aggregated[sap_code] = {
                'desc': desc,
                'qty_signed': signed_qty,
                'wbs': wbs,
                'postingDate': posting_date,
                'sapCode': sap_code,
            }

    # Build result — skip zero-net items
    results = []
    for entry in aggregated.values():
        net = entry['qty_signed']
        if abs(net) < 0.0001:
            continue
        results.append({
            'description': entry['desc'],
            'sapCode':     entry['sapCode'],
            'qty':         abs(net),
            'wbs':         entry['wbs'],
            'postingDate': entry['postingDate'],
            'docText':     '',
        })

    return results


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if not PDF_AVAILABLE:
            self._json(500, {'error': 'pdfplumber not installed on server'})
            return

        content_type = self.headers.get('Content-Type', '')
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)

        # Expect multipart/form-data with a 'file' field
        try:
            environ = {
                'REQUEST_METHOD': 'POST',
                'CONTENT_TYPE': content_type,
                'CONTENT_LENGTH': str(length),
            }
            fs = cgi.FieldStorage(
                fp=io.BytesIO(body),
                environ=environ,
                keep_blank_values=True
            )
            file_item = fs['file']
            pdf_bytes = file_item.file.read()
        except Exception as e:
            self._json(400, {'error': f'Could not read uploaded file: {e}'})
            return

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = ''
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        full_text += t + '\n'

            entries = parse_cji3_text(full_text)
            self._json(200, {'entries': entries, 'rawText': full_text[:500]})
        except Exception as e:
            self._json(500, {'error': str(e)})

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass
