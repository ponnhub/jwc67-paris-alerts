#!/usr/bin/env python3
"""jwc67-paris live alerts builder.

Collects REAL Paris items (protests, strikes, station/line closures, road closures,
sight closures, politics, safety) from public RSS feeds, writes alerts.json.
Never invents anything: every item is a real headline with its real source link.
Thai text is a deterministic keyword-based label (no LLM) + the original headline.

Usage:
  python3 build_alerts.py                 # build -> ./alerts.json (next to this script)
  python3 build_alerts.py --out X.json    # build to a path
  python3 build_alerts.py --push          # build + push alerts.json to GitHub if changed
  python3 build_alerts.py --push --all    # also push this script + README.md
Env:
  GITHUB_ALERTS_TOKEN  fine-grained token (Contents RW on the repo) - needed for --push
  ALERTS_REPO          default ponnhub/jwc67-paris-alerts
  PRIM_API_KEY         optional, IDFM PRIM line_reports (adds official transit disruptions)
"""
import base64, datetime as dt, email.utils, hashlib, json, os, re, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

PARIS, BKK, UTC = ZoneInfo('Europe/Paris'), ZoneInfo('Asia/Bangkok'), dt.timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get('ALERTS_REPO', 'ponnhub/jwc67-paris-alerts')
UA = {'User-Agent': 'Mozilla/5.0 (jwc67-paris-alerts; +https://github.com/%s)' % REPO}
NOW = dt.datetime.now(UTC)
MAX_AGE_H = 72          # normal window
UPCOMING_AGE_H = 24*7   # older items allowed if they announce a future date
MAX_ITEMS = 15

def get(url, headers=None, data=None, method=None, timeout=20):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})}, data=data, method=method)
    return urllib.request.urlopen(req, timeout=timeout).read()

def gnews(q, lang='fr'):
    loc = 'hl=fr&gl=FR&ceid=FR:fr' if lang == 'fr' else 'hl=en-US&gl=US&ceid=US:en'
    return 'https://news.google.com/rss/search?q=%s&%s' % (urllib.parse.quote(q), loc)

# (name, url, lang, max items taken from this feed, require-Paris filter)
FEEDS = [
    ('gn', gnews('Paris manifestation OR mobilisation OR rassemblement when:2d'), 'fr', 10, True),
    ('gn', gnews('stations fermées métro RER Paris when:2d'), 'fr', 6, True),
    ('gn', gnews('grève RATP OR SNCF OR RER OR métro OR Transilien when:7d'), 'fr', 8, False),
    ('gn', gnews('Paris circulation OR "route fermée" OR bouclage OR blocage when:2d'), 'fr', 6, True),
    ('gn', gnews('Louvre OR "tour Eiffel" OR Orsay OR Versailles OR "Sacré-Cœur" fermé OR fermeture OR grève when:3d'), 'fr', 6, False),
    ('gn', gnews('Paris préfecture de police interdiction OR sécurité OR alerte when:2d'), 'fr', 5, True),
    ('gn', gnews('Paris protest OR strike OR closure when:2d', 'en'), 'en', 6, True),
    ('gn', gnews('France government Macron when:1d', 'en'), 'en', 3, False),
    ('BFM Paris', 'https://www.bfmtv.com/rss/paris/', 'fr', 8, True),
    ('France 24', 'https://www.france24.com/fr/france/rss', 'fr', 5, True),
    ('franceinfo', 'https://www.francetvinfo.fr/titres.rss', 'fr', 5, True),
]

PARIS_RE = re.compile(r"paris|île-de-france|ile-de-france|idf\b|ratp|rer\b|métro|metro|transilien|république|bastille|châtelet|gare du nord|gare de lyon|montparnasse|saint-lazare|austerlitz|champs|concorde|louvre|eiffel|orsay|château de versailles|montmartre|roissy|cdg|orly|hauts-de-seine|seine-saint-denis|val-de-marne|essonne|yvelines", re.I)
RELEVANT_RE = re.compile(r"grève|greve|strike|préavis|manifest|mobilisation|rassemblement|cortège|protest|rally|gilets? jaunes|yellow vest|fermé|fermée|fermés|fermeture|ferme ses|fermer|closed|closure|interdi|bouclage|blocage|bloqu|circulation|perturb|disrupt|trafic|travaux|incendie|fire|attentat|attack|alerte|évacu|evacu|sécurité|police|lacrymo|tear gas|clash|heurts|tension|interpell|arrest|detain|gouvernement|government|macron|premier ministre|prime minister|assemblée|motion de censure", re.I)
JUNK_RE = re.compile(r"sortie|sorties|exposition|expositions|halloween|découvrez|agenda|bons plans|recette|horoscope|salaire|concert|que faire|week-end en|idées|nos \d+|notre sélection|guide|shopping|soldes|why is|opinion|tribune|réputés|insolite|roman |devra\W+fermer|pourrait\W+fermer|va-t-il|va-t-elle|terrasse", re.I)
BLOCK_SRC_RE = re.compile(r"horticulture-abadie|^https?://", re.I)  # content farms / unnamed sites
STRIKE_FUTURE_RE = re.compile(r"appel|préavis|appellent|appelés|grève (du|le|de|des)|strike (on|call)|\d{1,2} (octobre|novembre|décembre)", re.I)

CATS = {  # key: (Thai label, order, cap, advice)
    'transit':  ('🚇 ขนส่งสาธารณะ', 0, 4, 'เช็กสถานะสายใน RATP/IDFM ก่อนออก และเผื่อเวลาเดินทาง'),
    'protest':  ('📣 ชุมนุม/ประท้วง', 1, 5, 'เลี่ยงบริเวณชุมนุม ถ้าเจอฝูงชนหรือตำรวจปิดทาง ให้ถอยออกทันที'),
    'strike':   ('🛑 นัดหยุดงาน', 2, 3, 'วันนัดหยุดงาน รถอาจน้อยหรืองดวิ่ง เช็กก่อนเดินทาง'),
    'road':     ('🚧 ปิดถนน/จราจร', 3, 3, 'Uber/แท็กซี่อาจอ้อมไกล ใช้เมโทรสายที่ยังวิ่งจะเร็วกว่า'),
    'sight':    ('🏛️ สถานที่ท่องเที่ยว', 4, 3, 'เช็กเว็บทางการของสถานที่ก่อนไป'),
    'safety':   ('⚠️ ความปลอดภัย', 5, 3, 'ทำตามคำสั่งตำรวจ เก็บกระเป๋าไว้ด้านหน้า ฉุกเฉินโทร 112'),
    'politics': ('🏛 การเมือง', 6, 2, 'ข่าวการเมือง อาจมีการชุมนุมตามมา ติดตามแจ้งเตือนต่อ'),
}

def categorize(t):
    if re.search(r"(station|métro|metro|rer)s?\b.{0,40}ferm|ferm.{0,30}(station|métro|metro|rer)|ligne \d+|rer [a-e]\b|trafic|perturbation|transilien|disruption", t, re.I): return 'transit'
    if re.search(r"grève|greve|strike|préavis|cheminots", t, re.I): return 'strike'
    if re.search(r"manifest|mobilisation|rassemblement|cortège|protest|rally|gilets? jaunes|yellow vest", t, re.I): return 'protest'
    if re.search(r"louvre|eiffel|orsay|château de versailles|sacré-c|musée|museum|monument|notre-dame", t, re.I): return 'sight'
    if re.search(r"circulation|route|autoroute|bouclage|blocage|périphérique|bouchon|travaux", t, re.I): return 'road'
    if re.search(r"incendie|fire|attentat|attack|évacu|evacu|alerte|police|sécurité|agress|vol |pickpocket|blessé", t, re.I): return 'safety'
    if re.search(r"gouvernement|government|macron|ministre|minister|assemblée|censure|élection|election", t, re.I): return 'politics'
    return None

PHRASES = [  # (regex, Thai) – plain keyword glossary, not a translation
    (r"(station|métro|metro|rer)s?\b.{0,40}ferm|ferm.{0,30}(station|métro|metro)", 'สถานีเมโทร/RER บางแห่งปิด'),
    (r"cost-of-living|high prices|vie chère|prix", 'ประท้วงค่าครองชีพ'),
    (r"gilets? jaunes|yellow vest", 'กลุ่มเสื้อกั๊กเหลือง'),
    (r"lycéens|students|étudiants", 'นักเรียน/นักศึกษาร่วม'),
    (r"manifest|mobilisation|rassemblement|cortège|protest|rally", 'มีการชุมนุม'),
    (r"grève|greve|strike", 'นัดหยุดงาน'),
    (r"sncf|cheminots|tgv", 'รถไฟ SNCF'),
    (r"ratp", 'RATP'),
    (r"interdi|banned", 'ห้ามชุมนุมบางเขต'),
    (r"lacrymo|tear gas|canons? à eau|water cannon|heurts|clash|tension", 'มีการปะทะ/แก๊สน้ำตา'),
    (r"interpell|arrest|detain|garde à vue", 'มีการจับกุม'),
    (r"circulation|trafic routier|bouchon|route|autoroute", 'การจราจร/ปิดถนน'),
    (r"incendie|fire", 'เหตุไฟไหม้'),
    (r"travaux|works", 'งานซ่อมบำรุง'),
    (r"louvre", 'พิพิธภัณฑ์ลูฟวร์'), (r"eiffel", 'หอไอเฟล'), (r"orsay", 'พิพิธภัณฑ์ออร์แซ'), (r"château de versailles", 'พระราชวังแวร์ซาย'),
    (r"toussaint", 'ช่วงหยุด Toussaint (ปลาย ต.ค.–ต้น พ.ย.)'),
    (r"ferm|closed|closure", 'ปิด'),
    (r"macron", 'ประธานาธิบดีมาครง'), (r"gouvernement|government|premier ministre|prime minister", 'รัฐบาล'),
]
PLACES = [(r"république", 'จัตุรัส République'), (r"gare du nord", 'Gare du Nord'), (r"gare de lyon", 'Gare de Lyon'),
          (r"bastille", 'Bastille'), (r"\bnation\b", 'Nation'), (r"châtelet", 'Châtelet'), (r"champs", 'ช็องเซลีเซ'),
          (r"concorde", 'Concorde'), (r"austerlitz", 'Austerlitz'), (r"montparnasse", 'Montparnasse'),
          (r"saint-lazare", 'Saint-Lazare'), (r"opéra|opera", 'Opéra'), (r"montmartre", 'Montmartre'),
          (r"roissy|cdg|charles-de-gaulle", 'สนามบิน CDG'), (r"orly", 'สนามบิน Orly')]
MONTHS_FR = {'janvier':1,'février':2,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'aout':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12,'decembre':12}
MONTHS_EN = {m:i+1 for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'])}
TH_MON = ['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.']

def event_date(t, pub):
    m = re.search(r"\b(\d{1,2})(?:er)? (%s)\b" % '|'.join(MONTHS_FR), t, re.I)
    if m: d, mo = int(m.group(1)), MONTHS_FR[m.group(2).lower()]
    else:
        m = re.search(r"\b(%s) (\d{1,2})\b" % '|'.join(MONTHS_EN), t, re.I)
        if not m: return None
        mo, d = MONTHS_EN[m.group(1).lower()], int(m.group(2))
    y = pub.astimezone(PARIS).year
    try:
        x = dt.date(y, mo, d)
        if (pub.date() - x).days > 180: x = dt.date(y+1, mo, d)
        return x
    except ValueError: return None

def thai(t, cat, src, edate):
    ph = []
    for p, th in PHRASES:
        if re.search(p, t, re.I) and th not in ph:
            if th == 'ปิด' and any('ปิด' in x for x in ph): continue
            ph.append(th)
    for m in re.finditer(r"\bligne (\d{1,2})\b|\bRER ([A-E])\b", t, re.I):
        x = 'เมโทรสาย ' + m.group(1) if m.group(1) else 'RER ' + m.group(2).upper()
        if x not in ph: ph.insert(0, x)
    pl = [th for p, th in PLACES if re.search(p, t, re.I)]
    head = ' · '.join(ph[:3]) or 'ข่าวในปารีส'
    rg = re.search(r"\b(\d{1,2})(?:er)?\s*(?:au|to|-|–)\s*(\d{1,2})\b", t)
    if edate and rg and int(rg.group(1)) == edate.day: head += ' (%s–%s %s)' % (rg.group(1), rg.group(2), TH_MON[edate.month])
    elif edate: head += ' (%d %s)' % (edate.day, TH_MON[edate.month])
    summ = ('ย่าน: ' + ', '.join(pl[:3]) + ' · ' if pl else '') + CATS[cat][3]
    return head, summ

def severity(t, cat, upcoming):
    if re.search(r"ferm|closed|interdi|bloqu|lacrymo|tear gas|canon|heurts|clash|attentat|attack|évacu|evacu|interpell|arrest", t, re.I): return 'high'
    if cat in ('protest', 'strike', 'transit') and not upcoming: return 'high' if cat == 'transit' else 'medium'
    return 'medium' if cat != 'politics' else 'low'

def norm(t): return set(w for w in re.findall(r"\w{4,}", t.lower()))

items, errors, seen_urls = [], [], set()

def add(title, url, src, src_url, pub, lang, need_paris, origin):
    title = re.sub(r"\s+", ' ', title).strip()
    if src and title.endswith(' - ' + src): title = title[:-len(src)-3].strip()
    if not url.startswith(('https://', 'http://')) or not title: return False
    if url in seen_urls or BLOCK_SRC_RE.search(src or ''): return False
    if not RELEVANT_RE.search(title) or JUNK_RE.search(title): return False
    cat = categorize(title)
    if not cat: return False
    if need_paris and not PARIS_RE.search(title): return False
    if cat == 'strike' and not (PARIS_RE.search(title) or re.search(r"sncf|national|nationale|france", title, re.I)): return False
    if cat == 'strike' and not STRIKE_FUTURE_RE.search(title): return False
    if cat in ('safety', 'road', 'sight') and not PARIS_RE.search(title): return False
    age_h = (NOW - pub).total_seconds() / 3600
    ed = event_date(title, pub)
    today = NOW.astimezone(PARIS).date()
    upcoming = bool(ed and ed > today)
    if age_h > MAX_AGE_H and not (upcoming and age_h <= UPCOMING_AGE_H): return False
    if ed and ed < today and age_h > 30: return False   # past event, stale
    toks = norm(title)
    for it in items:
        a = it['_tok']; j = len(a & toks) / max(1, len(a | toks))
        if j >= 0.5 or (ed and it.get('event_date') == ed.isoformat() and it['cat'] == cat and j >= 0.3): return False
    th_title, th_sum = thai(title, cat, src, ed)
    if any(it['cat'] == cat and it['title_th'] == th_title and 'ข่าวในปารีส' not in th_title for it in items): return False
    seen_urls.add(url)
    items.append({
        'id': hashlib.sha1(url.encode()).hexdigest()[:12],
        'cat': cat, 'cat_th': CATS[cat][0], 'severity': severity(title, cat, upcoming),
        'title_th': th_title, 'summary_th': th_sum,
        'title': title, 'lang': lang,
        'src': src or origin, 'src_home': src_url or '', 'url': url,
        'time': pub.astimezone(PARIS).isoformat(timespec='minutes'),
        'time_th': pub.astimezone(BKK).isoformat(timespec='minutes'),
        'event_date': ed.isoformat() if ed else None, 'upcoming': upcoming,
        'via': origin, '_tok': toks,
    })
    return True

def parse_date(s):
    try: d = email.utils.parsedate_to_datetime(s)
    except Exception: return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)

for name, url, lang, cap, need_paris in FEEDS:
    try:
        root = ET.fromstring(get(url))
        n = 0
        for it in root.iter('item'):
            pub = parse_date(it.findtext('pubDate') or '')
            if not pub: continue
            s = it.find('source')
            src = (s.text or '').strip() if s is not None else name
            src_url = s.get('url') if s is not None else ''
            origin = 'Google News' if name == 'gn' else name
            if add(it.findtext('title') or '', (it.findtext('link') or '').strip(), src if name == 'gn' else name,
                   src_url, pub, lang, need_paris, origin):
                n += 1
                if n >= cap: break
    except Exception as e:
        errors.append('%s: %s' % (name if name != 'gn' else 'Google News', type(e).__name__))

k = os.environ.get('PRIM_API_KEY')
if k:
    try:
        j = json.loads(get('https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/line_reports/line_reports?count=50', {'apikey': k}))
        for d in j.get('disruptions', [])[:40]:
            if d.get('status') != 'active': continue
            msgs = d.get('messages') or []
            m = next((x.get('text') for x in msgs if (x.get('channel') or {}).get('name') in ('titre', 'title')), None) or (msgs[0].get('text', '') if msgs else '')
            t = re.sub('<[^>]+>', '', m or '').strip()[:220]
            if not t: continue
            up = d.get('updated_at', '')
            try: pub = dt.datetime.strptime(up, '%Y%m%dT%H%M%S').replace(tzinfo=PARIS)
            except Exception: pub = NOW
            items.append({'id': 'prim-' + str(d.get('id', ''))[:20], 'cat': 'transit', 'cat_th': CATS['transit'][0],
                          'severity': 'high' if d.get('severity', {}).get('effect') in ('NO_SERVICE', 'REDUCED_SERVICE') else 'medium',
                          'title_th': 'ประกาศทางการ IDFM', 'summary_th': CATS['transit'][3], 'title': t, 'lang': 'fr',
                          'src': 'Île-de-France Mobilités (PRIM)', 'src_home': 'https://prim.iledefrance-mobilites.fr',
                          'url': 'https://www.bonjour-ratp.fr/infos-trafic/', 'time': pub.astimezone(PARIS).isoformat(timespec='minutes'),
                          'time_th': pub.astimezone(BKK).isoformat(timespec='minutes'), 'event_date': None, 'upcoming': False,
                          'via': 'PRIM', '_tok': norm(t)})
    except Exception as e: errors.append('PRIM: %s' % type(e).__name__)

# per-category caps, then order: severity, category, newest first
SEV = {'high': 0, 'medium': 1, 'low': 2}
items.sort(key=lambda i: i['time'], reverse=True)
kept, cnt = [], {}
for i in items:
    c = i['cat']
    if c != 'transit' or i['via'] != 'PRIM':
        if cnt.get(c, 0) >= CATS[c][2]: continue
    cnt[c] = cnt.get(c, 0) + 1; kept.append(i)
kept.sort(key=lambda i: (SEV[i['severity']], CATS[i['cat']][1], -dt.datetime.fromisoformat(i['time']).timestamp()))
kept = kept[:MAX_ITEMS]
for i in kept: i.pop('_tok', None)

out = {
    'schema': 2,
    'updated_at': NOW.astimezone(PARIS).isoformat(timespec='seconds'),
    'updated_at_th': NOW.astimezone(BKK).isoformat(timespec='seconds'),
    'updated': NOW.isoformat(timespec='seconds'),
    'time_note': 'time = เวลาปารีส (Europe/Paris), time_th = เวลาไทย (Asia/Bangkok, เร็วกว่าปารีส 5 ชม. ช่วงหน้าหนาว / 6 ชม. ช่วงหน้าร้อน)',
    'note': 'รวบรวมอัตโนมัติจากหัวข่าวจริงพร้อมลิงก์ต้นทาง ข้อความไทยเป็นป้ายสรุปตามคำสำคัญ ไม่ใช่คำแปล โปรดกดอ่านต้นทาง',
    'sources': ['Google News RSS (FR/EN)', 'BFM Paris RSS', 'France 24 RSS', 'franceinfo RSS'] + (['IDFM PRIM'] if k else []),
    'count': len(kept), 'items': kept, 'errors': errors,
}
def content_key(o): return json.dumps([(i['url'], i['title_th'], i['summary_th']) for i in o.get('items', [])], ensure_ascii=False)

args = sys.argv[1:]
path = args[args.index('--out')+1] if '--out' in args else os.path.join(HERE, 'alerts.json')
body = json.dumps(out, ensure_ascii=False, indent=1) + '\n'
open(path, 'w').write(body)
print('built %d items -> %s%s' % (len(kept), path, (' | warnings: ' + '; '.join(errors)) if errors else ''))

def gh_put(rel, data, msg):
    tok = os.environ.get('GITHUB_ALERTS_TOKEN')
    if not tok: sys.exit('GITHUB_ALERTS_TOKEN not set')
    h = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    api = 'https://api.github.com/repos/%s/contents/%s' % (REPO, rel)
    sha, old = None, None
    try:
        cur = json.loads(get(api + '?ref=main', h)); sha = cur['sha']; old = base64.b64decode(cur['content'])
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
    return h, api, sha, old

def push(rel, data, msg, force=False, alerts=False):
    h, api, sha, old = gh_put(rel, data, msg)
    if old is not None and not force:
        if old == data: print('unchanged:', rel); return
        if alerts:
            try:
                o = json.loads(old)
                age = (NOW - dt.datetime.fromisoformat(o.get('updated_at') or o.get('updated'))).total_seconds() / 3600
                if content_key(o) == content_key(out) and age < 2:
                    print('items unchanged (remote %.1fh old) - skip push' % age); return
            except Exception: pass
    payload = {'message': msg, 'content': base64.b64encode(data).decode(), 'branch': 'main'}
    if sha: payload['sha'] = sha
    get(api, {**h, 'Content-Type': 'application/json'}, json.dumps(payload).encode(), 'PUT')
    print('pushed:', rel)

if '--push' in args:
    stamp = NOW.astimezone(PARIS).strftime('%Y-%m-%d %H:%M Paris')
    if '--all' in args:
        push('build_alerts.py', open(os.path.abspath(__file__), 'rb').read(), 'Update builder script')
        rd = os.path.join(HERE, 'README.md')
        if os.path.exists(rd): push('README.md', open(rd, 'rb').read(), 'Update README')
    push('alerts.json', body.encode(), 'alerts: %d items @ %s' % (len(kept), stamp), alerts=True)
