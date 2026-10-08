"""Reference lists shared by every app: counties, the 14 EU allergens and months."""

COUNTIES = [
    ('carlow', 'Carlow'), ('cavan', 'Cavan'), ('clare', 'Clare'), ('cork', 'Cork'), ('donegal', 'Donegal'),
    ('dublin', 'Dublin'), ('galway', 'Galway'), ('kerry', 'Kerry'), ('kildare', 'Kildare'),
    ('kilkenny', 'Kilkenny'), ('laois', 'Laois'), ('leitrim', 'Leitrim'), ('limerick', 'Limerick'),
    ('longford', 'Longford'), ('louth', 'Louth'), ('mayo', 'Mayo'), ('meath', 'Meath'),
    ('monaghan', 'Monaghan'), ('offaly', 'Offaly'), ('roscommon', 'Roscommon'), ('sligo', 'Sligo'),
    ('tipperary', 'Tipperary'), ('waterford', 'Waterford'), ('westmeath', 'Westmeath'), ('wexford', 'Wexford'),
    ('wicklow', 'Wicklow'),
]

ALLERGENS = [
    ('celery', 'Celery'),
    ('cereals_gluten', 'Cereals containing gluten'),
    ('crustaceans', 'Crustaceans'),
    ('eggs', 'Eggs'),
    ('fish', 'Fish'),
    ('lupin', 'Lupin'),
    ('milk', 'Milk'),
    ('molluscs', 'Molluscs'),
    ('mustard', 'Mustard'),
    ('nuts', 'Tree nuts'),
    ('peanuts', 'Peanuts'),
    ('sesame', 'Sesame'),
    ('soybeans', 'Soya'),
    ('sulphites', 'Sulphites'),
]

MONTHS = [
    (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'), (5, 'May'), (6, 'June'),
    (7, 'July'), (8, 'August'), (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
]

COUNTY_LABELS = dict(COUNTIES)
ALLERGEN_LABELS = dict(ALLERGENS)
MONTH_LABELS = dict(MONTHS)
