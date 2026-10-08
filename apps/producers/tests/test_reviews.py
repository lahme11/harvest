from django.test import TestCase
from django.urls import reverse

from apps.core.testing import make_order, make_producer, make_product, make_user
from apps.producers import services


class ReviewTests(TestCase):
    def setUp(self):
        self.farm = make_producer('maire', name='Burren Hill Farm', verified=True)
        self.buyer = make_user('aoife')
        self.product = make_product(self.farm)

    def collect(self, buyer=None):
        return make_order(buyer or self.buyer, self.product, status='collected')

    def test_needs_a_collected_order(self):
        self.assertFalse(services.can_review(self.buyer, self.farm))
        make_order(self.buyer, self.product, status='accepted')
        self.assertFalse(services.can_review(self.buyer, self.farm))

        self.collect()

        self.assertTrue(services.can_review(self.buyer, self.farm))

    def test_refused_without_an_order(self):
        with self.assertRaises(services.ProducerError):
            services.save_review(self.buyer, self.farm, 5, 'Lovely.')

    def test_cannot_review_own_farm_or_home_producers(self):
        home = make_producer('niamh', verified=False)
        make_order(self.buyer, make_product(home, name='Jam', category='pantry', ingredients='plums, sugar'),
                   status='collected')

        self.assertFalse(services.can_review(self.farm.user, self.farm))
        self.assertFalse(services.can_review(self.buyer, home))

    def test_second_review_edits_the_first(self):
        self.collect()
        services.save_review(self.buyer, self.farm, 4, 'Good eggs.')

        review = services.save_review(self.buyer, self.farm, 5, 'Great eggs.')

        self.assertEqual(self.farm.reviews.count(), 1)
        self.assertEqual((review.rating, review.text), (5, 'Great eggs.'))

    def test_rating_must_be_one_to_five(self):
        self.collect()

        with self.assertRaises(services.ProducerError):
            services.save_review(self.buyer, self.farm, 6, 'Too good.')

    def test_reply_once(self):
        self.collect()
        review = services.save_review(self.buyer, self.farm, 5, 'Great.')

        services.reply(review, self.farm.user, 'Thank you!')

        with self.assertRaises(services.ProducerError):
            services.reply(review, self.farm.user, 'Thanks again!')
        with self.assertRaises(services.ProducerError):
            services.reply(review, self.buyer, 'Not my farm.')

    def test_rating_summary_and_farm_page(self):
        self.collect()
        other = make_user('brian')
        self.collect(other)
        services.save_review(self.buyer, self.farm, 5, 'Great.')
        services.save_review(other, self.farm, 4, 'Good.')

        self.assertEqual(services.rating_summary(self.farm), (4.5, 2))
        response = self.client.get(self.farm.get_absolute_url())
        self.assertContains(response, '4.5')
        self.assertContains(response, 'Great.')
        directory = self.client.get(reverse('producers:directory'))
        self.assertContains(directory, '(2)')

    def test_review_through_the_view(self):
        self.collect()
        self.client.force_login(self.buyer)

        self.client.post(reverse('producers:review', args=[self.farm.slug]), {'rating': '5', 'text': 'Superb lamb.'})

        self.assertEqual(self.farm.reviews.get().text, 'Superb lamb.')
