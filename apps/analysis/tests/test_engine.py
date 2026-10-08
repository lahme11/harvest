import time
from unittest import TestCase

from apps.analysis import engine

REFERENCE = engine.default_reference()


def analyse(text, name=''):
    return engine.analyse(text, REFERENCE, product_name=name)


class LabelTableTests(TestCase):
    """Real-world labels and the NOVA group and grade we expect for each."""

    LABELS = [
        ('', 'Carrots', 1, 'A'),
        ('oats', '', 1, 'A'),
        ('almonds, raisins', '', 1, 'A'),
        ('olive oil', '', 2, 'A'),
        ('butter, salt', '', 2, 'A'),
        ('tomatoes, salt', '', 3, 'A'),
        ('wheat flour, water, salt, yeast', '', 3, 'A'),
        ('pork (90%), salt, preservative: sodium nitrite (E250)', '', 3, 'A'),
        ('potatoes, sunflower oil, salt', '', 3, 'A'),
        ('oat flour, glucose-fructose syrup, E471, flavouring', '', 4, None),
        ('milk chocolate (sugar, cocoa butter, emulsifier: soya lecithin), oats (45%)', '', 4, None),
    ]

    def test_labels(self):
        for text, name, nova, grade in self.LABELS:
            with self.subTest(text=text):
                result = analyse(text, name)
                self.assertEqual(result.nova_group, nova)
                if grade:
                    self.assertEqual(result.grade, grade)

    def test_chocolate_spread_is_ultra_processed_with_a_low_grade(self):
        result = analyse('sugar, palm oil, hazelnuts (13%), skimmed milk powder, fat-reduced cocoa, '
                         'emulsifier: lecithins (soya), vanillin')

        self.assertEqual(result.nova_group, 4)
        self.assertIn(result.grade, ('D', 'E'))

    def test_hydrogenated_fat_is_a_marker(self):
        self.assertEqual(analyse('flour, partially hydrogenated palm oil, salt').nova_group, 4)

    def test_function_word_alone_marks_ultra_processing(self):
        self.assertEqual(analyse('rice, sweetener (something unusual)').nova_group, 4)

    def test_water_does_not_change_the_group(self):
        self.assertEqual(analyse('tomatoes, water').nova_group, 1)
        self.assertEqual(analyse('water, salt').nova_group, 2)

    def test_free_from_claims_are_not_ingredients(self):
        self.assertEqual(analyse('lactose-free milk, gluten-free oats').nova_group, 1)

    def test_fortified_flour_is_not_ultra_processed(self):
        result = analyse('wheat flour (wheat flour, calcium carbonate, iron, niacin, thiamin), water, salt, yeast')

        self.assertEqual(result.nova_group, 3)


class ParseTests(TestCase):
    def test_nested_children_and_percent(self):
        items = engine.parse_ingredients('milk chocolate (sugar, cocoa butter, emulsifier: soya lecithin), oats (45%)')

        self.assertEqual([item.name for item in items], ['milk chocolate', 'oats'])
        chocolate, oats = items
        self.assertEqual([child.name for child in chocolate.children], ['sugar', 'cocoa butter', 'soya lecithin'])
        self.assertEqual(chocolate.children[2].function, 'emulsifier')
        self.assertEqual(oats.percent, 45.0)
        self.assertEqual(oats.children, [])

    def test_percent_inline(self):
        items = engine.parse_ingredients('hazelnuts 13%, sugar')

        self.assertEqual(items[0].name, 'hazelnuts')
        self.assertEqual(items[0].percent, 13.0)

    def test_display_keeps_original_text(self):
        items = engine.parse_ingredients('Organic Oats*')

        self.assertEqual(items[0].name, 'oats')
        self.assertEqual(items[0].display, 'Organic Oats*')

    def test_function_bracket_group(self):
        items = engine.parse_ingredients('emulsifiers (E471, E472e), salt')

        self.assertEqual(items[0].function, 'emulsifiers')
        self.assertEqual([child.name for child in items[0].children], ['e471', 'e472e'])
        self.assertTrue(all(child.function == 'emulsifiers' for child in items[0].children))

    def test_and_splits_top_level_items(self):
        self.assertEqual([i.name for i in engine.parse_ingredients('salt and pepper')], ['salt', 'pepper'])

    def test_and_inside_a_known_additive_name_is_kept(self):
        result = analyse('mono- and diglycerides of fatty acids, oats')

        self.assertEqual(result.nova_group, 4)
        self.assertEqual(len(result.leaves), 2)

    def test_square_brackets_nest(self):
        items = engine.parse_ingredients('filling [apple, sugar], pastry')

        self.assertEqual([child.name for child in items[0].children], ['apple', 'sugar'])

    def test_unbalanced_brackets_do_not_raise(self):
        items = engine.parse_ingredients('flour (wheat, water')

        self.assertEqual(items[0].name, 'flour')
        self.assertEqual([child.name for child in items[0].children], ['wheat', 'water'])

    def test_semicolons_split(self):
        self.assertEqual(len(engine.parse_ingredients('oats; raisins; almonds')), 3)

    def test_e_number_forms(self):
        cases = {'E 471': 'E471', 'e-471': 'E471', 'E471a': 'E471A', 'e 160a(ii)': 'E160A', 'E–471': 'E471',
                 'E 1442': 'E1442'}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(engine.normalise_e_number(raw), expected)
        self.assertIsNone(engine.normalise_e_number('emulsifier'))

    def test_messy_text(self):
        result = analyse('“Oats”, sugar – cane, E–471, raisins.')

        self.assertEqual(result.nova_group, 4)
        self.assertIn('E471', result.additives)

    def test_whitespace_only_is_empty(self):
        result = analyse('   \n ', 'Leeks')

        self.assertEqual(result.nova_group, 1)
        self.assertEqual(result.leaves, ['leeks'])

    def test_long_list_is_fast(self):
        text = ', '.join(f'ingredient number {i}' for i in range(200))

        started = time.perf_counter()
        result = analyse(text)

        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(len(result.leaves), 200)


class ScoreTests(TestCase):
    def test_one_marker_costs_25(self):
        self.assertEqual(analyse('oats, E471').clean_score, 75)

    def test_further_markers_cost_10(self):
        self.assertEqual(analyse('oats, E471, E415').clean_score, 65)

    def test_aliases_of_one_additive_count_once(self):
        self.assertEqual(analyse('oats, flavouring, natural flavourings').clean_score, 75)

    def test_non_marker_additive_costs_6(self):
        self.assertEqual(analyse('oats, E300').clean_score, 94)

    def test_sugar_first_costs_15(self):
        self.assertEqual(analyse('sugar, oats').clean_score, 85)

    def test_sugar_later_costs_5(self):
        self.assertEqual(analyse('oats, raisins, sugar').clean_score, 95)

    def test_salt_costs_3(self):
        self.assertEqual(analyse('tomatoes, salt').clean_score, 97)

    def test_long_list_costs_2_per_extra_ingredient(self):
        self.assertEqual(analyse('a, b, c, d, e, f, g').clean_score, 96)

    def test_unknown_e_number(self):
        result = analyse('oats, E1999')

        self.assertEqual(result.unknown, ['E1999'])
        self.assertEqual(result.clean_score, 95)
        self.assertEqual(result.nova_group, 3)

    def test_score_is_clamped_at_zero(self):
        text = 'oats, ' + ', '.join(f'E{code}' for code in (102, 104, 110, 122, 124, 129, 133, 150, 407, 412, 415, 471))

        result = analyse(text)

        self.assertEqual(result.clean_score, 0)
        self.assertEqual(result.grade, 'E')

    def test_grades(self):
        self.assertEqual(engine.grade_for(85), 'A')
        self.assertEqual(engine.grade_for(84), 'B')
        self.assertEqual(engine.grade_for(70), 'B')
        self.assertEqual(engine.grade_for(50), 'C')
        self.assertEqual(engine.grade_for(30), 'D')
        self.assertEqual(engine.grade_for(29), 'E')


class ReasonTests(TestCase):
    def test_marker_reason_names_the_additive(self):
        reasons = ' '.join(analyse('oats, E471').reasons)

        self.assertIn('E471', reasons)
        self.assertIn('emulsifier', reasons)
        self.assertIn('ultra-processing', reasons)

    def test_sugar_position_reason(self):
        self.assertIn('Sugar is the 1st ingredient', analyse('sugar, oats').reasons)

    def test_clean_label_reason(self):
        self.assertIn('No additives found', analyse('oats, raisins').reasons)

    def test_to_dict_round_trip(self):
        data = analyse('oats, E471').to_dict()

        self.assertEqual(data['nova_group'], 4)
        self.assertEqual(data['additives'], ['E471'])
        self.assertIn('reasons', data)


class AllergenHintTests(TestCase):
    def test_hints_for_unticked_allergens_only(self):
        hints = engine.allergen_hints('wheat flour, butter', {'cereals_gluten'})

        self.assertEqual(len(hints), 1)
        self.assertIn('butter', hints[0])
        self.assertIn('Milk', hints[0])

    def test_plant_butters_and_milks_are_not_dairy(self):
        self.assertEqual(engine.allergen_hints('cocoa butter, oat milk', {'cereals_gluten'}), [])

    def test_sulphite_e_numbers(self):
        hints = engine.allergen_hints('dried apricots, E220', set())

        self.assertTrue(any('Sulphites' in hint for hint in hints))

    def test_nothing_to_hint(self):
        self.assertEqual(engine.allergen_hints('carrots, onions', set()), [])
