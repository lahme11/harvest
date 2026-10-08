"""The ingredient analyser: how processed is a product, judged from its ingredient list?

Pure Python with no Django imports, so it can be tested and reused on its own. `analyse()` parses an
ingredient list, matches each ingredient against a reference list of additives and markers of
ultra-processing, and returns a NOVA group (1–4), a clean score out of 100, a grade and plain-English reasons.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'additives.json'

MARKER_KINDS = frozenset({
    'colour', 'emulsifier', 'stabiliser', 'thickener', 'gelling_agent', 'sweetener', 'flavour_enhancer',
    'flavouring', 'glazing_agent', 'humectant', 'modified_starch', 'bulking_agent', 'foaming_agent',
    'anti_foaming', 'protein_isolate', 'sugar_variant', 'modified_fat', 'carrier',
})

KIND_LABELS = {
    'colour': 'a colour', 'preservative': 'a preservative', 'antioxidant': 'an antioxidant',
    'emulsifier': 'an emulsifier', 'stabiliser': 'a stabiliser', 'thickener': 'a thickener',
    'gelling_agent': 'a gelling agent', 'sweetener': 'a sweetener', 'flavour_enhancer': 'a flavour enhancer',
    'flavouring': 'a flavouring', 'acidity_regulator': 'an acidity regulator', 'raising_agent': 'a raising agent',
    'anti_caking': 'an anti-caking agent', 'glazing_agent': 'a glazing agent', 'humectant': 'a humectant',
    'modified_starch': 'a modified starch', 'bulking_agent': 'a bulking agent', 'foaming_agent': 'a foaming agent',
    'anti_foaming': 'an anti-foaming agent', 'carrier': 'a carrier', 'protein_isolate': 'an industrial protein',
    'sugar_variant': 'an industrial sugar', 'modified_fat': 'a modified fat', 'other': 'an additive',
}

FUNCTION_WORDS = {
    'emulsifier': 'emulsifier', 'emulsifiers': 'emulsifier', 'emulsifying salt': 'emulsifier',
    'emulsifying salts': 'emulsifier', 'preservative': 'preservative', 'preservatives': 'preservative',
    'antioxidant': 'antioxidant', 'antioxidants': 'antioxidant', 'colour': 'colour', 'colours': 'colour',
    'color': 'colour', 'colors': 'colour', 'colouring': 'colour', 'sweetener': 'sweetener',
    'sweeteners': 'sweetener', 'thickener': 'thickener', 'thickeners': 'thickener',
    'thickening agent': 'thickener', 'stabiliser': 'stabiliser', 'stabilisers': 'stabiliser',
    'stabilizer': 'stabiliser', 'stabilizers': 'stabiliser', 'gelling agent': 'gelling_agent',
    'gelling agents': 'gelling_agent', 'acidity regulator': 'acidity_regulator',
    'acidity regulators': 'acidity_regulator', 'acid': 'acidity_regulator', 'acids': 'acidity_regulator',
    'raising agent': 'raising_agent', 'raising agents': 'raising_agent', 'flavour enhancer': 'flavour_enhancer',
    'flavour enhancers': 'flavour_enhancer', 'humectant': 'humectant', 'humectants': 'humectant',
    'glazing agent': 'glazing_agent', 'glazing agents': 'glazing_agent', 'anti-caking agent': 'anti_caking',
    'anti-caking agents': 'anti_caking', 'anticaking agent': 'anti_caking', 'firming agent': 'other',
    'bulking agent': 'bulking_agent', 'bulking agents': 'bulking_agent', 'flour treatment agent': 'other',
    'foaming agent': 'foaming_agent', 'anti-foaming agent': 'anti_foaming', 'carrier': 'carrier',
}

CULINARY = frozenset({
    'salt', 'sea salt', 'rock salt', 'iodised salt', 'table salt', 'sugar', 'cane sugar', 'raw cane sugar',
    'brown sugar', 'light brown sugar', 'dark brown sugar', 'caster sugar', 'icing sugar', 'demerara sugar',
    'muscovado sugar', 'coconut sugar', 'beet sugar', 'honey', 'maple syrup', 'golden syrup', 'molasses',
    'treacle', 'black treacle', 'agave syrup', 'olive oil', 'extra virgin olive oil', 'virgin olive oil',
    'rapeseed oil', 'cold pressed rapeseed oil', 'sunflower oil', 'vegetable oil', 'palm oil', 'coconut oil',
    'sesame oil', 'groundnut oil', 'butter', 'unsalted butter', 'salted butter', 'ghee', 'lard', 'dripping',
    'beef dripping', 'vinegar', 'cider vinegar', 'apple cider vinegar', 'white wine vinegar',
    'red wine vinegar', 'balsamic vinegar', 'malt vinegar', 'spirit vinegar', 'starch', 'corn starch',
    'cornflour', 'cornstarch', 'potato starch', 'tapioca starch', 'rice starch', 'wheat starch',
})

SUGARS = frozenset({term for term in CULINARY if 'sugar' in term or 'syrup' in term} |
                   {'honey', 'molasses', 'treacle', 'black treacle'})
SALTS = frozenset({term for term in CULINARY if term.endswith('salt')})
WATER = frozenset({'water', 'filtered water', 'spring water', 'mineral water', 'purified water', 'drinking water'})

MARKER_PHRASES = ('flavouring', 'flavourings', 'flavoring', 'flavorings', 'hydrogenated')

ALLERGEN_KEYWORDS = {
    'milk': ('milk', 'butter', 'buttermilk', 'cream', 'cheese', 'whey', 'casein', 'caseinate', 'lactose',
             'yoghurt', 'yogurt', 'ghee', 'curd', 'kefir'),
    'eggs': ('egg', 'eggs', 'albumen', 'egg white', 'egg yolk'),
    'cereals_gluten': ('wheat', 'barley', 'rye', 'oat', 'oats', 'spelt', 'kamut', 'gluten', 'semolina',
                       'durum', 'bulgur', 'couscous'),
    'soybeans': ('soya', 'soy', 'soybean', 'soybeans', 'edamame', 'tofu', 'tempeh'),
    'nuts': ('almond', 'almonds', 'hazelnut', 'hazelnuts', 'walnut', 'walnuts', 'cashew', 'cashews', 'pecan',
             'pecans', 'pistachio', 'pistachios', 'macadamia', 'brazil nut', 'brazil nuts'),
    'peanuts': ('peanut', 'peanuts', 'groundnut', 'groundnuts'),
    'sesame': ('sesame', 'tahini'),
    'mustard': ('mustard',),
    'celery': ('celery', 'celeriac'),
    'fish': ('fish', 'salmon', 'cod', 'tuna', 'anchovy', 'anchovies', 'mackerel', 'haddock', 'hake', 'trout'),
    'crustaceans': ('prawn', 'prawns', 'shrimp', 'crab', 'lobster', 'crayfish', 'langoustine'),
    'molluscs': ('mussel', 'mussels', 'oyster', 'oysters', 'clam', 'clams', 'squid', 'octopus', 'scallop',
                 'scallops', 'snail', 'snails'),
    'lupin': ('lupin',),
    'sulphites': ('sulphite', 'sulphites', 'sulfite', 'sulfites', 'sulphur dioxide', 'sulfur dioxide'),
}

ALLERGEN_LABELS = {
    'milk': 'Milk', 'eggs': 'Eggs', 'cereals_gluten': 'Cereals containing gluten', 'soybeans': 'Soya',
    'nuts': 'Tree nuts', 'peanuts': 'Peanuts', 'sesame': 'Sesame', 'mustard': 'Mustard', 'celery': 'Celery',
    'fish': 'Fish', 'crustaceans': 'Crustaceans', 'molluscs': 'Molluscs', 'lupin': 'Lupin',
    'sulphites': 'Sulphites',
}

NOT_ALLERGENS = ('cocoa butter', 'shea butter', 'peanut butter', 'almond butter', 'cashew butter',
                 'coconut milk', 'almond milk', 'oat milk', 'soya milk', 'soy milk', 'rice milk', 'coconut cream',
                 'cream of tartar', 'buckwheat')

SULPHITE_CODES = frozenset(f'E{n}' for n in range(220, 229))

E_NUMBER = re.compile(r'(?<![a-z0-9])e\s*-?\s*(\d{3,4})\s*([a-z])?(?:\s*\(\s*[ivx]+\s*\))?(?![a-z0-9])')
PERCENT = re.compile(r'\(?\s*(\d+(?:[.,]\d+)?)\s*%\s*\)?')
FREE_FROM = re.compile(r'\b[a-z]+-free\b')
DESCRIPTORS = re.compile(r'\b(?:organic|free-range|free range)\b')
TRANSLATE = str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'", '–': '-', '—': '-', ' ': ' '})


@dataclass
class ParsedIngredient:
    """One ingredient from a label. Bracketed sub-ingredients are its children."""

    name: str
    display: str
    percent: float | None = None
    function: str | None = None
    children: list = field(default_factory=list)


@dataclass
class Entry:
    code: str | None
    name: str
    aliases: list
    kind: str
    marker: bool

    @property
    def label(self):
        return f'{self.code} ({self.name.lower()})' if self.code else self.name.lower()


@dataclass
class Analysis:
    nova_group: int
    clean_score: int
    grade: str
    leaves: list
    reasons: list
    unknown: list
    additives: list

    def to_dict(self):
        return asdict(self)


class Reference:
    """The additive reference list, indexed for matching by E-number, name and contained phrase."""

    def __init__(self, entries):
        self.entries = entries
        self.by_code = {entry.code: entry for entry in entries if entry.code}
        self.by_name = {}
        for entry in entries:
            for name in [entry.name, *entry.aliases]:
                self.by_name.setdefault(normalise(name), entry)
        phrases = sorted((name for name in self.by_name if len(name) >= 4), key=len, reverse=True)
        self.phrase_pattern = re.compile(r'(?<![a-z0-9])(?:' + '|'.join(map(re.escape, phrases)) + r')(?![a-z0-9])') \
            if phrases else None
        self.and_phrases = tuple(name for name in self.by_name if ' and ' in name)

    @classmethod
    def from_entries(cls, rows):
        return cls([Entry(code=row.get('code') or None, name=row['name'], aliases=list(row.get('aliases') or []),
                          kind=row['kind'], marker=bool(row['marker'])) for row in rows])

    def lookup_code(self, code):
        entry = self.by_code.get(code)
        if entry is None and code[-1].isalpha():
            entry = self.by_code.get(code[:-1])
        return entry

    def match(self, name):
        """The entry for an ingredient name: by E-number, exact name, or a known phrase inside it."""
        code = find_e_number(name)
        if code:
            return self.lookup_code(code), code
        if name in self.by_name:
            return self.by_name[name], None
        if self.phrase_pattern:
            found = self.phrase_pattern.search(name)
            if found:
                return self.by_name[found.group(0)], None
        return None, None


def default_reference():
    """The reference list bundled with the app, without needing a database."""
    return Reference.from_entries(json.loads(DATA_FILE.read_text(encoding='utf-8')))


def normalise(text):
    """Lowercase, plain punctuation, single spaces, and no trailing full stops or asterisks."""
    text = text.translate(TRANSLATE).lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text.strip(' .*"\'')


def match_key(name):
    """The form of a name used for matching: without "organic", "free-range" or "x-free" claims."""
    name = FREE_FROM.sub('', name)
    name = DESCRIPTORS.sub('', name)
    return re.sub(r'\s+', ' ', name).strip(' .*-')


def normalise_e_number(token):
    """`E 471`, `e-471`, `E471a`, `e 160a(ii)` → `E471`, `E471`, `E471A`, `E160A`; None if not an E-number."""
    text = normalise(token)
    found = E_NUMBER.fullmatch(text)
    if not found:
        return None
    return f'E{found.group(1)}{(found.group(2) or "").upper()}'


def find_e_number(text):
    found = E_NUMBER.search(text)
    if not found:
        return None
    return f'E{found.group(1)}{(found.group(2) or "").upper()}'


def _split_top_level(text, separators=',;'):
    """Split on separators that are not inside brackets. Unbalanced brackets are tolerated."""
    parts, depth, current = [], 0, []
    for char in text:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        if char in separators and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)
    parts.append(''.join(current))
    return [part.strip() for part in parts if part.strip()]


def _split_and(item, protected):
    """Split "salt and pepper" into two items, unless "and" is part of a known name."""
    lowered = normalise(item)
    if ' and ' not in lowered or any(phrase in lowered for phrase in protected):
        return [item]
    pieces, depth, start, i = [], 0, 0, 0
    while i < len(item):
        char = item[i]
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        elif depth == 0 and item[i:i + 5].lower() == ' and ':
            pieces.append(item[start:i])
            start = i + 5
            i += 4
        i += 1
    pieces.append(item[start:])
    return [piece.strip() for piece in pieces if piece.strip()]


def _split_bracket(item):
    """Split "name (inner) rest" into (name + rest, inner); inner is None when there are no brackets."""
    opening = next((i for i, char in enumerate(item) if char in '(['), None)
    if opening is None:
        return item, None
    depth = 0
    for i in range(opening, len(item)):
        if item[i] in '([':
            depth += 1
        elif item[i] in ')]':
            depth -= 1
            if depth == 0:
                return (item[:opening] + ' ' + item[i + 1:]).strip(), item[opening + 1:i]
    return item[:opening].strip(), item[opening + 1:]


def _take_percent(text):
    found = PERCENT.search(text)
    if not found:
        return text, None
    return (text[:found.start()] + text[found.end():]).strip(), float(found.group(1).replace(',', '.'))


def _parse_item(item, protected, function=None):
    display = item.strip()
    head, inner = _split_bracket(display)
    colon = head.find(':')
    if colon > 0 and inner is None:
        func = normalise(head[:colon])
        if func in FUNCTION_WORDS:
            return [_parse_item(head[colon + 1:], protected, function=func)[0]]
    head, percent = _take_percent(head)
    name = match_key(normalise(head))
    if inner is not None:
        inner_text, inner_percent = _take_percent(inner)
        if not inner_text.strip(' ,;'):
            return [ParsedIngredient(name=name, display=display, percent=inner_percent if percent is None else percent,
                                     function=function)]
        if name in FUNCTION_WORDS:
            children = parse_ingredients(inner, protected, function=name)
            return [ParsedIngredient(name=name, display=display, percent=percent, function=name, children=children)]
        children = parse_ingredients(inner, protected)
        return [ParsedIngredient(name=name, display=display, percent=percent, function=function, children=children)]
    return [ParsedIngredient(name=name, display=display, percent=percent, function=function)]


def parse_ingredients(text, protected=(), function=None):
    """Parse an ingredient list into a tree of ParsedIngredient (bracketed groups become children)."""
    text = (text or '').translate(TRANSLATE)
    items = []
    for part in _split_top_level(text):
        for piece in _split_and(part, protected):
            for parsed in _parse_item(piece, protected, function):
                if parsed.name or parsed.children:
                    if function and not parsed.function:
                        parsed.function = function
                    items.append(parsed)
    return items


def _leaves(items, reference):
    """Depth-first leaf ingredients. A node that is itself a known additive is a leaf (its bracket is a source)."""
    leaves = []
    for item in items:
        if item.children and item.name not in FUNCTION_WORDS:
            entry, _ = reference.match(item.name)
            if entry is not None:
                leaves.append(item)
                continue
        if item.children:
            leaves.extend(_leaves(item.children, reference))
        else:
            leaves.append(item)
    return leaves


def _classify(leaf, reference):
    """Return (category, entry, code) where category is marker/additive/unknown/culinary/water/food."""
    name = leaf.name
    if any(phrase in name.split() or phrase in name for phrase in MARKER_PHRASES):
        entry, code = reference.match(name)
        return 'marker', entry, code
    entry, code = reference.match(name)
    if code and entry is None:
        return 'unknown', None, code
    if entry is not None:
        return ('marker' if entry.marker else 'additive'), entry, code or entry.code
    kind = FUNCTION_WORDS.get(leaf.function or '')
    if kind:
        return ('marker' if kind in MARKER_KINDS else 'additive'), None, None
    if name in WATER:
        return 'water', None, None
    if name in CULINARY:
        return 'culinary', None, None
    return 'food', None, None


def grade_for(score):
    if score >= 85:
        return 'A'
    if score >= 70:
        return 'B'
    if score >= 50:
        return 'C'
    if score >= 30:
        return 'D'
    return 'E'


def _label(leaf, entry, code):
    """How an additive is named in reasons: "E471 (mono- and diglycerides…)" or the word on the label."""
    if entry is not None and entry.code:
        return entry.label
    if entry is not None:
        return leaf.name if leaf.name != entry.name.lower() else entry.name.lower()
    return code or leaf.name


def _describe(label, kind):
    """ "vanillin, a flavouring" — but just "flavouring" when the label already says what it is."""
    kind_label = KIND_LABELS.get(kind, 'an additive')
    noun = kind_label.split(' ', 1)[1]
    return label if noun in label else f'{label}, {kind_label}'


def _ordinal(n):
    return {1: '1st', 2: '2nd', 3: '3rd'}.get(n, f'{n}th')


def _is_sugar(leaf, category, entry):
    return leaf.name in SUGARS or (category == 'marker' and entry is not None and entry.kind == 'sugar_variant')


def analyse(text, reference, product_name=''):
    """Classify an ingredient list. Empty text means a single whole food (the product name)."""
    items = parse_ingredients(text, reference.and_phrases)
    if not items:
        name = match_key(normalise(product_name)) or 'whole food'
        items = [ParsedIngredient(name=name, display=product_name or name)]
    leaves = _leaves(items, reference)
    classified = [(leaf, *_classify(leaf, reference)) for leaf in leaves]

    reasons, additives, unknown = [], [], []
    seen_markers, seen_additives = [], []
    for leaf, category, entry, code in classified:
        if category == 'marker':
            label = _label(leaf, entry, code)
            key = entry.name if entry else label
            if key in seen_markers:
                continue
            seen_markers.append(key)
            kind = entry.kind if entry else FUNCTION_WORDS.get(leaf.function or '', 'flavouring')
            reasons.append(f'Contains {_describe(label, kind)}: a marker of ultra-processing')
            additives.append(code or (entry.code if entry and entry.code else (entry.name if entry else leaf.name)))
        elif category == 'additive':
            label = _label(leaf, entry, code)
            key = entry.name if entry else label
            if key in seen_additives:
                continue
            seen_additives.append(key)
            kind = entry.kind if entry else FUNCTION_WORDS.get(leaf.function or '', 'other')
            reasons.append(f'Contains {_describe(label, kind)}')
            additives.append(code or (entry.code if entry and entry.code else (entry.name if entry else leaf.name)))
        elif category == 'unknown':
            if code not in unknown:
                unknown.append(code)
                additives.append(code)
                reasons.append(f"Contains {code}, which isn't in our additive reference list")

    categories = [category for _, category, _, _ in classified]
    foods = categories.count('food')
    if seen_markers:
        nova = 4
    elif foods and (categories.count('culinary') or seen_additives or unknown):
        nova = 3
    elif not foods and (categories.count('culinary') or seen_additives or unknown):
        nova = 2
    else:
        nova = 1

    score = 100
    if seen_markers:
        score -= 25 + 10 * (len(seen_markers) - 1)
    score -= 6 * len(seen_additives)
    score -= 5 * len(unknown)

    top_level_sugar = None
    for position, item in enumerate(items[:2], start=1):
        if not item.children:
            category, entry, _ = _classify(item, reference)
            if _is_sugar(item, category, entry):
                top_level_sugar = (position, item.name)
                break
    if top_level_sugar:
        position, sugar_name = top_level_sugar
        score -= 15
        subject = 'Sugar' if sugar_name == 'sugar' else f'Sugar ({sugar_name})'
        reasons.append(f'{subject} is the {_ordinal(position)} ingredient')
    elif any(_is_sugar(leaf, category, entry) for leaf, category, entry, _ in classified):
        score -= 5
        reasons.append('Contains added sugar')
    if any(leaf.name in SALTS for leaf in leaves):
        score -= 3
        reasons.append('Contains added salt')
    if len(leaves) > 5:
        score -= 2 * (len(leaves) - 5)
        reasons.append(f'Long ingredient list ({len(leaves)} ingredients)')
    score = max(0, min(100, score))

    if not additives:
        reasons.insert(0, 'No additives found')
    if nova == 1:
        reasons.insert(0, 'A single whole food' if len(leaves) == 1 else 'Only whole foods')
    elif nova == 2:
        reasons.insert(0, 'Only culinary ingredients such as oil, butter, sugar or salt')

    return Analysis(nova_group=nova, clean_score=score, grade=grade_for(score), leaves=[leaf.name for leaf in leaves],
                    reasons=reasons, unknown=unknown, additives=additives)


def allergen_hints(text, ticked):
    """Warnings for allergens the ingredient words suggest but the seller hasn't ticked."""
    lowered = normalise(text or '')
    for phrase in NOT_ALLERGENS:
        lowered = lowered.replace(phrase, ' ')
    lowered = FREE_FROM.sub(' ', lowered)
    hints = []
    for slug, words in ALLERGEN_KEYWORDS.items():
        if slug in ticked:
            continue
        found = next((word for word in words if re.search(rf'(?<![a-z]){re.escape(word)}(?![a-z])', lowered)), None)
        if found is None and slug == 'sulphites':
            codes = {f'E{m.group(1)}' for m in E_NUMBER.finditer(lowered)}
            found = next(iter(sorted(codes & SULPHITE_CODES)), None)
        if found:
            hints.append(f"Ingredients mention {found}, but {ALLERGEN_LABELS[slug]} isn't ticked")
    return hints
