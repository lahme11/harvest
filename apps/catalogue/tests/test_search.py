from unittest import mock

from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse

from apps.catalogue import services
from apps.core.testing import local, make_producer, make_product


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cork = make_producer('maire', name='Ballymaloe Bakehouse', county='cork', verified=True)
        dublin = make_producer('sean', name='Liberties Loaves', county='dublin')
        clare = make_producer('aoife', name='Burren Hens', county='clare', verified=True)
        cls.cork_bread = make_product(cork, name='Sourdough loaf', category='bakery', price='6.50',
                                      ingredients='wheat flour, water, salt', allergens='cereals_gluten')
        cls.dublin_bread = make_product(dublin, name='Sourdough batch loaf', category='bakery', price='5.00',
                                        ingredients='wheat flour, water, salt, E300', allergens='cereals_gluten')
        cls.organic_eggs = make_product(clare, name='Free-range eggs', category='eggs', unit='dozen', price='4.20',
                                        organic=True, allergens='eggs')
        cls.plain_eggs = make_product(dublin, name='Duck eggs', category='eggs', unit='half_dozen', price='3.80',
                                      allergens='eggs')
        cls.bar = make_product(dublin, name='Protein bar', category='pantry', price='2.20',
                               ingredients='soy protein isolate, glucose syrup, sweetener: sucralose, flavouring',
                               allergens='soybeans')
        cls.cheese = make_product(cork, name='Farmhouse cheddar', category='dairy', price='7.00',
                                  ingredients='pasteurised cows milk, salt, cultures, rennet', allergens='milk')
        cls.draft = make_product(cork, name='Sourdough draft', category='bakery', status='draft',
                                 ingredients='wheat flour, water, salt')
        cls.paused = make_product(cork, name='Sourdough paused', category='bakery', status='paused',
                                  ingredients='wheat flour, water, salt')

    def search(self, **params):
        query = QueryDict(mutable=True)
        for key, value in params.items():
            if isinstance(value, list):
                query.setlist(key, value)
            else:
                query[key] = value
        return list(services.search_from_params(query)[1])

    def test_every_word_must_match_something(self):
        self.assertEqual(self.search(q='sourdough cork'), [self.cork_bread])
        self.assertEqual(set(self.search(q='sourdough')), {self.cork_bread, self.dublin_bread})

    def test_producer_name_and_ingredient_words(self):
        self.assertEqual(self.search(q='burren'), [self.organic_eggs])
        self.assertEqual(self.search(q='sucralose'), [self.bar])

    def test_organic_keyword(self):
        self.assertEqual(self.search(q='organic eggs'), [self.organic_eggs])

    def test_category_word(self):
        self.assertEqual(set(self.search(q='dairy')), {self.cheese})

    def test_quoted_phrase(self):
        self.assertEqual(self.search(q='"batch loaf"'), [self.dublin_bread])

    def test_drafts_and_paused_never_appear(self):
        results = self.search(q='sourdough')

        self.assertNotIn(self.draft, results)
        self.assertNotIn(self.paused, results)

    def test_max_nova(self):
        results = self.search(max_nova='2')

        self.assertIn(self.organic_eggs, results)
        self.assertNotIn(self.cork_bread, results)
        self.assertNotIn(self.bar, results)

    def test_min_score(self):
        results = self.search(min_score='80')

        self.assertNotIn(self.bar, results)
        self.assertIn(self.cork_bread, results)

    def test_free_from(self):
        results = self.search(free_from=['milk', 'cereals_gluten'])

        self.assertNotIn(self.cheese, results)
        self.assertNotIn(self.cork_bread, results)
        self.assertIn(self.organic_eggs, results)

    def test_filters(self):
        self.assertEqual(set(self.search(category='eggs')), {self.organic_eggs, self.plain_eggs})
        self.assertEqual(set(self.search(county='clare')), {self.organic_eggs})
        self.assertEqual(set(self.search(organic='on')), {self.organic_eggs})
        self.assertEqual(set(self.search(verified='on')), {self.cork_bread, self.organic_eggs, self.cheese})
        self.assertEqual(set(self.search(price_min='5', price_max='6.50')), {self.cork_bread, self.dublin_bread})

    def test_sorting(self):
        by_score = self.search(sort='score')
        by_price = self.search(sort='price')

        self.assertEqual(by_score[-1], self.bar)
        self.assertEqual(by_price[0], self.bar)
        self.assertEqual(self.search(sort='-price')[0], self.cheese)

    def test_invalid_values_are_ignored(self):
        self.assertEqual(len(self.search(max_nova='9', sort='bogus', price_min='abc')), 6)


class BrowseViewTests(TestCase):
    def setUp(self):
        producer = make_producer('maire', verified=True)
        self.product = make_product(producer, name='Wexford strawberries', category='fruit', price='4.00')

    def test_browse_page(self):
        response = self.client.get(reverse('catalogue:browse'), {'q': 'strawberries'})

        self.assertContains(response, 'Wexford strawberries')
        self.assertContains(response, '1 product')

    def test_api(self):
        data = self.client.get(reverse('catalogue:api'), {'q': 'strawberries'}).json()

        self.assertEqual(data['count'], 1)
        result = data['results'][0]
        self.assertEqual(result['name'], 'Wexford strawberries')
        self.assertEqual(result['price'], '4.00')
        self.assertEqual(result['nova_group'], 1)
        self.assertEqual(result['url'], self.product.get_absolute_url())

    def test_home_shows_new_products(self):
        response = self.client.get(reverse('core:home'))

        self.assertContains(response, 'Wexford strawberries')


class InSeasonTests(TestCase):
    def test_lists_products_in_season_this_month(self):
        producer = make_producer('maire', verified=True)
        make_product(producer, name='Bramley apples', category='fruit', season_months='9,10,11')
        make_product(producer, name='Asparagus', category='vegetables', season_months='5')
        make_product(producer, name='Potatoes', category='vegetables')

        with mock.patch('django.utils.timezone.now', return_value=local(2026, 10, 15, 12)):
            response = self.client.get(reverse('catalogue:season'))

        self.assertContains(response, 'Bramley apples')
        self.assertContains(response, 'October')
        self.assertNotContains(response, 'Asparagus')
        self.assertNotContains(response, 'Potatoes')

    def test_other_month(self):
        producer = make_producer('maire', verified=True)
        make_product(producer, name='Asparagus', category='vegetables', season_months='5')

        response = self.client.get(reverse('catalogue:season'), {'month': '5'})

        self.assertContains(response, 'Asparagus')
