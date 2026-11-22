"""Identity discovery in the visible text of PDF drawings (title blocks, notices, contact lines).

Deterministic and offline. Input: an open pymupdf document. Output: (kind, value) candidates in the same format the other
harvesters produce; ident.register_candidates applies the final guards. Everything here is a precision-first heuristic:

  * labelled title-block fields (DRAWN / CHECKED / APPROVED / PROJECT / COMPANY ... and German / French / Spanish / Italian /
    Dutch / Catalan equivalents): the value is found by geometry (same row to the right, or directly below / above the label);
  * organisation names (a run of capitalised words ending in Inc / Ltd / GmbH / University / Institute ...);
  * "property of / confidential to / prepared by" holders;
  * e-mail, bare domains, international phone numbers, street addresses.

Initials, dates, numbers, dimensions, standards, materials, software names and dictionary words are never returned as names.
"""
from __future__ import annotations
import re
from . import detect

MAX_PAGES = 3
DENSE_WORDS = 700        # pages with more words are running text: label geometry is skipped there

# ------------------------------------------------------------------------------------------------ vocabulary
_PERSON_LABELS = """drawn|drawn by|drawn/design by|drawn / design by|drawn by/date|drwn|drwn by|dwn|dwn by|drn|drn by|drn/appvd by|drawn:|made by|checked|checked by|checked by/date|
chkd|chkd by|chk'd|chk|checker|approved|approved by|approval|approvals|appd|appd by|appv'd|appvd|apprvd|appr|appr by|designed|designed by|designer|engineer|engr|engr appr|
eng appr|eng|engineered by|mfg appr|author|created by|creator|prepared by|issued by|detailed by|detailed  by|modified by|reviewed by|reviewer|revised by|
responsible|draftsman|drafter|drafted by|originator|checked/approved|gezeichnet|gez|gezeichn|bear|gepr|geprueft|geprüft|bearb|bearbeiter|bearbeitet|bearbeitet von|erstellt von|
erstellt durch|ersteller|erst|freigegeben|genehmigt|konstrukteur|konstrukteur/in|dibujado|dibujado por|revisado|aprobado|comprobado|diseñado|diseñado por|dissenyat|dibuixat|
comprovat|aprovat|dessiné|dessiné par|dessinateur|dessin|vérifié|verifie|vérifié par|approuvé|conçu par|disegnato|disegnatore|disegnato da|controllato|verificato|approvato|
progettista|tekenaar|getekend|gecontroleerd|goedgekeurd|ontworpen door|ritat|granskad|godkänd|rysował|sprawdził|zatwierdził|kreslil|kontroloval|schválil|
设计|审核|校对|批准|制图|绘图|工艺审查|标准化|designed by:|drawn by:|checked by:|approved by:|created by:|author:|name of draftsman|zeichner|zeichner/in|prüfer|prufer""".replace("\n", "|").split("|")
_COMPANY_LABELS = """company|company name|firma|organization|organisation|organisation name|customer|client|client name|kunde|kunde/customer|cliente|société|societe|entreprise|
manufacturer|supplier|vendor|supplied by|owner|owner/company|copyright holder|institution|university|laboratory|lab|department|auftraggeber|hersteller|empresa|ditta|bedrijf|klant""".replace("\n", "").split("|")
_PROJECT_LABELS = """project|project name|project title|project/title|projekt|projektname|proyecto|projet|projecte|progetto|proj|job|job name|job no|program|programme|programm""".split("|")

_NAMELESS = {"job no", "program", "programme", "programm", "job", "department", "lab", "owner", "eng", "dessin"}  # too ambiguous for a bare-value pick


def _nl(s: str) -> str:
    s = s.strip().lower().replace("：", ":")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" :.;,")


PERSON_L = {_nl(x) for x in _PERSON_LABELS if x.strip()}
COMPANY_L = {_nl(x) for x in _COMPANY_LABELS if x.strip()}
PROJECT_L = {_nl(x) for x in _PROJECT_LABELS if x.strip()}
ALL_LABELS = PERSON_L | COMPANY_L | PROJECT_L
_LABEL_KIND = {**{l: "person" for l in PERSON_L}, **{l: "company" for l in COMPANY_L}, **{l: "project" for l in PROJECT_L}}

# words that describe drawings, not people / organisations (multi-lingual title-block vocabulary, materials, units, standards)
STOP = set("""date datum fecha data name nom nombre nome naam scale maßstab massstab escala echelle schaal sheet blatt hoja page seite weight gewicht peso poids mass masse
material werkstoff werkst materiale matériau materiaal title titel titre titulo benennung bezeichnung designation description rev revision revisión index änderung aenderung
drawing zeichnung dibujo dessin disegno tekening part teil teilename pieza piece pezzo assembly baugruppe conjunto ensemble finish surface oberfläche treatment tolerance
tolerances toleranz tolerancias toleranzen general allgemein unit units unless otherwise specified size format papier projection projektion method first third angle
section schnitt detail view ansicht quantity qty menge stk pos item no number nr nummer code drawn checked approved designed engineer issued released status zone sign
signature signatur datum approved approval project projekt proyecto company firma customer client kunde dimensions dimension mm inch inches metric ansi iso din asme
aluminum aluminium steel stainless brass bronze copper plastic nylon delrin acetal pvc abs titanium iron cast alloy anodized anodised black white zinc plated
nickel chrome carbon fiber rubber wood plywood acrylic polycarbonate none unknown tbd n/a na yes no not for use only information confidential proprietary property
solidworks inventor autocad catia creo fusion freecad onshape solidedge nx autodesk dassault siemens ptc sheet1 blatt1 bl pdf dwg dxf step stp edu com org net www http https
free tree sample example test prototype default student user admin owner untitled new notes note see ref refer below above left right front back top bottom side end
mirror support illumination oberflächengüte qualität produktion genehmigt gepr gezeichnet geprüft bearb gez norm freigabe stand version versión estado made
masstab kontrolliert kontroll kontrolle comments comment aprovado aprobado conjunt vistes vistas vista angolare fatto qualita qualità grupa kurbelwelle controllato verificato
revisado revisat comprovat dibuixat dissenyat disegnato getekend gecontroleerd goedgekeurd freigegeben genehmigt gezeichn bearbeitet erstellt geändert angle quality surface
cantidad quantità aantal materiaal materiale tratamiento trattamento acabado finitura toleranz allgemeintoleranz masse massa gewichte peso tolleranze tolerancias
impressió impressio document format full versió versio plànol conjunt part extrusor hotend
revisions release released initial changes change history list bom parts material finish quantity per unit""".split())
STOP |= set(w for w in detect.SOFTWARE_WORDS if " " not in w)

ORG_SUFFIX = {"inc", "incorporated", "ltd", "limited", "llc", "gmbh", "corp", "corporation", "co", "company", "ag", "bv", "sarl", "srl", "spa", "pty", "plc",
              "s.a", "s.a.", "s.l", "s.l.", "s.r.l", "s.p.a", "b.v", "b.v.", "e.v", "e.v.", "ohg", "gbr", "sas", "kft", "ltda", "ulc", "pllc", "llp"}
_CASE_SENSITIVE_SUFFIX = {"co", "ag", "sas", "bv", "spa", "srl", "gbr", "ohg", "plc", "pty"}   # only as spelled in capitals / with a dot (Co. / AG)
ORG_KW_AFTER = {"university", "universität", "universitat", "universidad", "université", "universite", "università", "universiteit", "institute", "institut", "instituto", "istituto",
                "laboratory", "laboratories", "laboratorium", "laboratoire", "labs", "college", "polytechnic", "hochschule", "fachhochschule", "foundation", "technologies",
                "industries", "robotics", "consortium", "aerospace"}
ORG_KW_BEFORE = {"university", "universität", "universidad", "université", "università", "institute", "institut", "college", "school", "laboratory", "hochschule",
                 "fachhochschule", "ecole", "école", "politecnico", "polytechnic", "technische", "foundation", "lab"}   # "<kw> of X" / "<kw> X"
_CONNECT = {"of", "de", "der", "den", "des", "du", "di", "da", "del", "della", "für", "fur", "and", "und", "et", "e", "y", "&", "für"}
_AMP_LOW = {"and", "&", "und", "et", "of", "de", "der", "für", "fur", "di", "del", "van", "von", "la", "le", "the", "for"}

FUNC = {"or", "and", "the", "such", "any", "by", "in", "on", "at", "for", "to", "with", "is", "are", "as", "not", "all", "this", "that", "from", "an", "a", "no", "be", "it",
        "copyright", "property", "confidential", "proprietary", "written", "writing", "reproduction", "permission", "consent", "without", "other", "than", "see", "where", "when",
        "unless", "if", "dyes", "estimated", "modified", "holes", "details", "below", "another", "vendor", "und", "oder", "der", "die", "das", "von", "ohne", "bei", "wird", "ist"}

_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ0-9'’&.-]*|&")

_DATE = re.compile(r"^\W*(?:\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4}|\d{1,2}[ -]?[A-Za-z]{3,9}[ -,]*\d{2,4}|[A-Za-z]{3,9}[ -]\d{1,2}[, -]+\d{2,4}|\d{1,2}[./]\d{1,2}|\d{4})\W*$")
_NUMLIKE = re.compile(r"^[\W\d_]*$")


def _is_dictionary(tok: str) -> bool:
    from .ident import english_words
    return tok.lower() in english_words()


def _first_names():
    global _FN
    try:
        return _FN
    except NameError:
        from .words import FIRST
        _FN = {w.lower() for w in FIRST}
        return _FN


def _tokens(v: str):
    return [t for t in re.split(r"[\s.,]+", v.strip()) if t]


_NOUNISH = re.compile(r"(?:ung|ungen|keit|heit|schaft|welle|platte|flansch|halter|deckel|stift|lager|zahnrad|zahnkranz|achse|gehäuse|gehause|stück|stuck|ado|ido|ción|cion|sión|ment|ités?|ità|iert|ierte|ierung|tion|tions|zione|mento|ació|aire|eur|issima|ica|ico|ica|ismo|abel|ular|atge|ents?|lik|ski)$")


def person_like(v: str) -> bool:
    """True for a plausible full person name / user name (not initials, not a title-block word)."""
    v = v.strip().strip(".,;:/\\()[]'\"")
    if not (5 <= len(v) <= 40) or re.search(r"\d", v) or "@" in v:
        return False
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ.' ’-]+", v):
        return False
    toks = [t for t in re.split(r"[\s.]+", v) if t]
    words = [t for t in toks if len(t) > 1]
    if not words or len(toks) > 4:
        return False
    low = [t.lower().strip("-'’") for t in toks]
    if any(t in STOP for t in low):
        return False
    if any(len(w) >= 2 and w.isupper() for w in words) and not v.isupper():
        return False
    if detect.is_generic_person(v):
        return False
    if len(words) == 1:
        w = words[0]
        if len(w) < 5 or _is_dictionary(w) or _NOUNISH.search(w.lower()):
            return False
        return True
    # several words: each word must look like a name part
    for w in words:
        if not (w[0].isupper() or w.islower() and len(toks) == len(words) and False):
            if not (w.lower() in ("van", "von", "de", "der", "den", "del", "da", "di", "le", "la", "dos", "da", "bin", "al", "el", "ter", "ten", "mc")):
                return False
    nondict = [w for w in words if not _is_dictionary(w)]
    if nondict or low[0] in _first_names():
        return True
    return False


def _clean_value(v: str) -> str:
    v = v.strip()
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"\s*[/|]\s*\d.*$", "", v)             # "Name / 12.03.2015"
    v = re.sub(r"\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}.*$", "", v)
    return v.strip(" ,;:|/")


# ------------------------------------------------------------------------------------------------ geometry
def _spans(page):
    """{direction: [(x0, y0, x1, y1, text)]} with boxes expressed in each line's own reading frame (rotated sheets work)."""
    groups: dict = {}
    try:
        d = page.get_text("dict", flags=0)
    except Exception:
        return groups
    for b in d.get("blocks", ()):
        for ln in b.get("lines", ()):
            t = "".join(s.get("text", "") for s in ln.get("spans", ())).strip()
            if not t:
                continue
            dx, dy = ln.get("dir", (1.0, 0.0))
            key = (round(dx), round(dy))
            if abs(dx) < 0.9 and abs(dy) < 0.9:
                continue         # slanted text
            x0, y0, x1, y1 = ln["bbox"]
            pts = [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
            tx = [x * key[0] + y * key[1] for x, y in pts]
            ty = [-x * key[1] + y * key[0] for x, y in pts]
            groups.setdefault(key, []).append((min(tx), min(ty), max(tx), max(ty), t))
    return groups


def _label_of(text: str):
    """(kind, inline_value) when the text is a label (optionally 'Label: value'), else None."""
    n = _nl(text)
    if n in ALL_LABELS:
        return _LABEL_KIND[n], ""
    m = re.match(r"^([A-Za-zÀ-ÿ'’./ ]{3,24}?)\s*[:：]\s*(\S.{2,60})$", text.strip())
    if m:
        l = _nl(m.group(1))
        if l in ALL_LABELS and l not in _NAMELESS:
            return _LABEL_KIND[l], m.group(2).strip()
    return None


def _value_spans(label, spans):
    """Spans that may hold the value of `label`: same row to the right (dates skipped), directly below, directly above."""
    lx0, ly0, lx1, ly1, _ = label
    h = max(ly1 - ly0, 3.0)
    cy = (ly0 + ly1) / 2
    right, below, above = [], [], []
    for s in spans:
        if s is label:
            continue
        x0, y0, x1, y1, t = s
        sh = max(y1 - y0, 3.0)
        scy = (y0 + y1) / 2
        if abs(scy - cy) <= 0.6 * max(h, sh) and x0 >= lx1 - 2 and x0 - lx1 <= 160:
            right.append((x0 - lx1, s))
        elif y0 >= ly1 - 1.5 and y0 - ly1 <= 2.2 * h + 8 and x0 < lx1 + 12 and x1 > lx0 - 12:
            below.append((y0 - ly1, s))
        elif y1 <= ly0 + 1.5 and ly0 - y1 <= 2.2 * h + 8 and x0 < lx1 + 12 and x1 > lx0 - 12:
            above.append((ly0 - y1, s))
    return [s for _, s in sorted(right, key=lambda z: z[0])], [s for _, s in sorted(below, key=lambda z: z[0])], [s for _, s in sorted(above, key=lambda z: z[0])]


def _pick(kind: str, cands):
    for s in cands[:3]:
        t = _clean_value(s[4])
        if not t or _NUMLIKE.match(t) or _DATE.match(t) or _label_of(t) or _nl(t) in ALL_LABELS:
            continue
        if kind == "person":
            if person_like(t):
                return t
            if len(t) <= 4 or re.search(r"\d", t):
                continue        # initials / dates / codes: keep looking at the next span on the row
            return None
        if kind == "company":
            if org_like(t):
                return t
        if kind == "project":
            if project_like(t):
                return t
    return None


def org_like(v: str) -> bool:
    v = v.strip()
    if not (4 <= len(v) <= 60) or re.search(r"\d{3,}|@|://", v) or not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9.,'’&() /-]+", v):
        return False
    toks = [t for t in re.split(r"[\s]+", v) if t]
    low = [t.lower().strip(".,()") for t in toks]
    if len(toks) > 7 or low[0] in STOP or detect.is_generic_person(v):
        return False
    if all(t in STOP or _is_dictionary(t) for t in low) and not any(t in ORG_SUFFIX for t in low) and len(toks) < 2:
        return False
    if len(toks) == 1 and (low[0] in STOP or _is_dictionary(low[0])):
        return False
    if not any(t[0].isupper() for t in toks):
        return False
    return True


def project_like(v: str) -> bool:
    v = v.strip()
    if not (6 <= len(v) <= 50) or re.search(r"@|://|\.(?:dft|sldprt|sldasm|slddrw|dwg|dxf|ipt|iam|idw|step|stp)\b", v, re.I):
        return False
    if not re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9 ._&'’+/-]+", v) or sum(c.isalpha() for c in v) < 5:
        return False
    toks = [t.lower() for t in re.split(r"[\s._/-]+", v) if t]
    if all(t in STOP or t in FUNC or t in _AMP_LOW or t in _CONNECT or _is_dictionary(t) or t.isdigit() for t in toks):
        return False          # only generic words: not an identifying name
    raw = [t for t in re.split(r"[\s]+", v) if t]
    if sum(1 for t in raw if t.islower()) >= 3 or "XXX" in v.upper() or toks[0] in ("data", "name", "nom", "nombre"):
        return False
    if len(raw) == 1 and not (re.search(r"\d", v) or re.search(r"[a-z][A-Z]", v) or v.isupper()):
        return False
    if re.search(r"(?i)yyyy|mm/dd|\bdd/|^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", v) or len(toks) > 5:
        return False
    return not re.fullmatch(r"[\d\W_]+", v)


def labelled_fields(spans, out: list):
    for sp in spans:
        lab = _label_of(sp[4])
        if not lab:
            continue
        kind, inline = lab
        vals = []
        if inline:
            iv = _clean_value(inline)
            if (kind == "person" and person_like(iv)) or (kind == "company" and org_like(iv)) or (kind == "project" and project_like(iv)):
                vals.append(iv)
        else:
            if _nl(sp[4]) in _NAMELESS:
                continue
            right, below, above = _value_spans(sp, spans)
            v = _pick(kind, right)
            if v:
                vals.append(v)
            else:
                # a column of values under the header (revision tables): every plausible entry, bounded
                col = [s for s in below[:8]]
                for s in col:
                    t = _clean_value(s[4])
                    if t and not _label_of(t) and kind == "person" and person_like(t):
                        vals.append(t)
                    elif t and not _label_of(t) and kind != "person" and not vals:
                        v = _pick(kind, [s])
                        if v:
                            vals.append(v)
                if not vals:
                    v = _pick(kind, above)
                    if v:
                        vals.append(v)
        for val in vals:
            k = kind
            if k == "person":
                if val.isupper():
                    val = val.title()
                if re.search(r"(?i)\b(?:university|institute|institut|laboratory|college|inc|ltd|gmbh|llc|corp)\b", val):
                    k = "company"
                m = re.fullmatch(r"[A-Z]\.\s?([A-Z][a-zà-ÿ]{5,})", val)
                if m:
                    out.append(("person", m.group(1)))
            out.append((k, val))


# ------------------------------------------------------------------------------------------------ text patterns
def _caps_run_before(toks, i, maxn=4):
    """Indices of up to maxn capitalised tokens directly before position i (connector words allowed inside, not at the edge)."""
    j = i
    n = 0
    while j > 0 and n < maxn:
        t = toks[j - 1]
        tl = t.lower()
        if tl in FUNC:
            break
        if t[0].isupper() or t[0].isdigit():
            j -= 1; n += 1
        elif tl in _AMP_LOW and j - 2 >= 0 and toks[j - 2][0].isupper():
            j -= 1; n += 1
        else:
            break
    while j < i and (toks[j].lower() in _AMP_LOW or len(toks[j].strip(".")) <= 1):
        j += 1
    return j


def org_lines(lines, out: list):
    for ln in lines:
        if len(ln) < 6 or len(ln) > 160:
            continue
        toks = _WORD.findall(ln)
        if len(toks) < 2:
            continue
        low = [t.lower().strip(".,") for t in toks]
        for i, t in enumerate(low):
            if not toks[i][0].isupper():
                continue
            cand = None
            if t in ORG_SUFFIX:
                if i >= 1:
                    if t in _CASE_SENSITIVE_SUFFIX and not (toks[i].endswith(".") or toks[i] in ("AG", "BV", "SAS", "SPA", "SRL", "PLC", "GBR", "OHG", "PTY")):
                        continue
                    j = _caps_run_before(toks, i)
                    if j < i:
                        cand = " ".join(toks[j:i + 1])
            elif t in ORG_KW_AFTER:
                if t in ORG_KW_BEFORE and i + 1 < len(toks):
                    if low[i + 1] in _CONNECT:
                        k = i + 2
                        while k < len(toks) and k < i + 5 and (toks[k][0].isupper() or low[k] in _AMP_LOW):
                            k += 1
                        while k > i + 2 and low[k - 1] in _AMP_LOW:
                            k -= 1
                        if k > i + 2:
                            cand = " ".join(toks[i:k])
                    elif t.startswith(("univers", "institut", "hochschule", "ecole", "école")) and toks[i + 1][0].isupper() and low[i + 1] not in STOP:
                        cand = " ".join(toks[i:i + 2])
                if cand is None and i >= 1:
                    j = _caps_run_before(toks, i, 3)
                    if j < i:
                        cand = " ".join(toks[j:i + 1])
            if not cand:
                continue
            ws = cand.split()
            for q, w in enumerate(ws):
                if q and w.lower().strip(".,") in FUNC:
                    ws = ws[:q]
                    break
            cand = " ".join(ws).strip(" .,;:-")
            if len(cand) < 8 or not org_like(cand):
                continue
            words = [w.lower().strip(".,") for w in cand.split()]
            body = [w for w in words if w not in ORG_SUFFIX and w not in ORG_KW_AFTER and w not in _AMP_LOW and w not in _CONNECT]
            if body and (len(body) >= 2 or not (body[0] in STOP or _is_dictionary(body[0]))):
                out.append(("company", cand))


_NOTICE = re.compile(r"(?i)\b(?:property\s+of|proprietary\s+(?:to|of)|confidential\s+(?:to|property\s+of)|owned\s+by|belongs\s+to|courtesy\s+of|"
                     r"eigentum\s+(?:der|des|von)|propiedad\s+de|propriété\s+(?:de|du)|proprietà\s+(?:di|della)|eigendom\s+van|"
                     r"manufactured\s+by|produced\s+by|supplied\s+by|prepared\s+(?:for|by)|created\s+for|made\s+for|submitted\s+(?:to|by)|copyright\s+holder)[:\s]+")
_STOPTAIL = {"is", "are", "was", "and", "may", "must", "shall", "should", "will", "can", "no", "not", "all", "to", "in", "on", "at", "for", "the", "this", "it", "its", "which", "that", "be", "by", "as", "or", "ist", "und", "darf", "dürfen", "es"}


def notice_holders(text: str, out: list):
    for m in _NOTICE.finditer(text):
        tail = text[m.end(): m.end() + 120].split("\n")[0]
        toks = _WORD.findall(tail)
        keep = []
        for t in toks[:7]:
            tl = t.lower().strip(".,")
            if tl in _STOPTAIL and (keep and tl not in ("and",)):
                break
            if not (t[0].isupper() or tl in _AMP_LOW):
                break
            keep.append(t)
        while keep and keep[-1].lower().strip(".,") in _AMP_LOW:
            keep.pop()
        h = " ".join(keep).strip(" .,;:-")
        if len(h) >= 5 and org_like(h):
            words = [w.lower().strip(".,") for w in h.split()]
            if words[0] in STOP or words[0] in {"the", "a", "an", "our", "your", "its", "this", "these", "all"}:
                continue
            if all(w in STOP or _is_dictionary(w) for w in words) and len(words) < 2:
                continue
            out.append(("company", h))


_BARE_DOMAIN = re.compile(r"(?<![\w@./-])((?:[A-Za-z0-9][A-Za-z0-9-]{2,}\.)+(?:com|net|org|edu|de|fr|nl|ch|co\.uk|ac\.uk|io|info|eu|it|es|se|dk|no|fi|pl|cz|at|be))(?![\w@-])", re.I)
_INTL_PHONE = re.compile(r"(?<![\w.])(\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]\d{2,5}){2,4})(?![\d.])")
_US_PHONE = re.compile(r"(?<![\w.])(\(\d{3}\)\s?\d{3}[-.\s]\d{4})(?![\d])")
_STREET_EN = re.compile(r"\b(\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Drive|Lane|Way|Court|Parkway))\b\.?")
_STREET_DE = re.compile(r"\b([A-ZÄÖÜ][a-zäöüß]{3,}(?:straße|strasse|str\.|weg|platz|allee|gasse|ring|damm)\s+\d{1,4}[a-z]?)\b")


def contact_patterns(text: str, out: list):
    if "@" in text:
        for l, d in detect.find_emails(text):
            out.append(("email", f"{l}@{d}"))
    for m in _BARE_DOMAIN.finditer(text):
        d = m.group(1)
        label = d.split(".")[0].lower()
        if len(label) >= 4 and label not in STOP and not re.search(r"\d{4,}", d):
            out.append(("domain", d.lower()))
    for m in _INTL_PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if 9 <= len(digits) <= 15:
            out.append(("phone", m.group(1).strip()))
    for m in _US_PHONE.finditer(text):
        out.append(("phone", m.group(1).strip()))
    for m in detect.find_phones(text):
        out.append(("phone", m))
    for rx in (_STREET_EN, _STREET_DE):
        for m in rx.finditer(text):
            out.append(("address", m.group(1).strip()))


# ------------------------------------------------------------------------------------------------ entry point
def title_block_candidates(doc, out: list, max_pages: int = MAX_PAGES):
    """Append (kind, value) candidates found in the visible text of the first pages of an open pymupdf document."""
    n = min(len(doc), max_pages)
    for i in range(n):
        try:
            page = doc[i]
            groups = _spans(page)
        except Exception:
            continue
        if not groups:
            continue
        spans = [s for g in groups.values() for s in g]
        lines = [s[4] for s in spans]
        text = "\n".join(lines)
        dense = len(spans) > DENSE_WORDS
        if not dense:
            for g in groups.values():
                labelled_fields(g, out)
        org_lines(lines, out)
        notice_holders(text, out)
        contact_patterns(text, out)
