from io import BytesIO

from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.catalogue import services
from apps.catalogue.models import ProductPhoto
from apps.core.testing import TemporaryMediaMixin, image_upload, make_producer, make_product, make_user


class PhotoTests(TemporaryMediaMixin, TestCase):
    def setUp(self):
        self.producer = make_producer('niamh')
        self.product = make_product(self.producer)
        self.client.force_login(self.producer.user)

    def test_upload_strips_exif_and_makes_thumbnail(self):
        exif = Image.Exif()
        exif[0x8825] = {2: (53.0, 20.0, 0.0)}
        exif[0x010F] = 'PhoneMaker'

        self.client.post(reverse('catalogue:photos', args=[self.product.pk]),
                         {'photos': [image_upload(exif=exif.tobytes())]})

        photo = ProductPhoto.objects.get()
        with Image.open(photo.image.path) as stored:
            self.assertEqual(len(stored.getexif()), 0)
            self.assertLessEqual(max(stored.size), 1600)
        with Image.open(photo.thumbnail.path) as thumb:
            self.assertLessEqual(thumb.size[0], 480)
        self.assertTrue(photo.is_cover)

    def test_photo_limit(self):
        with override_settings(MAX_PHOTOS_PER_PRODUCT=2):
            response = self.client.post(reverse('catalogue:photos', args=[self.product.pk]),
                                        {'photos': [image_upload(f'p{i}.jpg') for i in range(3)]}, follow=True)

        self.assertEqual(ProductPhoto.objects.count(), 0)
        self.assertContains(response, 'up to 2 photos')

    def test_not_an_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(reverse('catalogue:photos', args=[self.product.pk]),
                                    {'photos': [SimpleUploadedFile('x.jpg', b'not an image', 'image/jpeg')]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductPhoto.objects.count(), 0)

    def test_set_cover_and_delete_removes_files(self):
        services.add_photos(self.product, [image_upload('a.jpg'), image_upload('b.jpg')])
        first, second = self.product.photos.order_by('position')

        self.client.post(reverse('catalogue:photo_cover', args=[second.pk]))
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertTrue(second.is_cover)
        self.assertFalse(first.is_cover)

        path = second.image.path
        self.client.post(reverse('catalogue:photo_delete', args=[second.pk]))
        first.refresh_from_db()
        self.assertTrue(first.is_cover)
        import os
        self.assertFalse(os.path.exists(path))

    def test_cannot_touch_other_producers_photos(self):
        other = make_product(make_producer('sean'))
        services.add_photos(other, [image_upload()])

        response = self.client.post(reverse('catalogue:photo_delete', args=[other.photos.get().pk]))

        self.assertEqual(response.status_code, 404)


class DetailTests(TestCase):
    def setUp(self):
        self.producer = make_producer('niamh')

    def test_live_product_shows_analysis(self):
        product = make_product(self.producer, name='Oat bar', category='pantry',
                               ingredients='oats, glucose syrup, emulsifier: soya lecithin')

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, 'Oat bar')
        self.assertContains(response, 'NOVA 4')
        self.assertContains(response, 'a marker of ultra-processing')

    def test_draft_is_404_to_others_and_visible_to_owner(self):
        product = make_product(self.producer, status='draft')

        self.assertEqual(self.client.get(product.get_absolute_url()).status_code, 404)
        self.client.force_login(make_user('buyer'))
        self.assertEqual(self.client.get(product.get_absolute_url()).status_code, 404)
        self.client.force_login(self.producer.user)
        self.assertEqual(self.client.get(product.get_absolute_url()).status_code, 200)

    def test_owner_sees_allergen_hints(self):
        product = make_product(self.producer, name='Shortbread', category='bakery',
                               ingredients='wheat flour, butter, sugar', allergens='cereals_gluten')
        self.client.force_login(self.producer.user)

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, 'Ingredients mention butter, but Milk isn')

    def test_off_comparison(self):
        product = make_product(self.producer, name='Biscuits', category='bakery', ingredients='flour, sugar',
                               off_nova_group=4)

        response = self.client.get(product.get_absolute_url())

        self.assertContains(response, 'Open Food Facts: NOVA 4')

    def test_view_count_ignores_the_owner(self):
        product = make_product(self.producer)

        self.client.get(product.get_absolute_url())
        self.client.force_login(self.producer.user)
        self.client.get(product.get_absolute_url())

        product.refresh_from_db()
        self.assertEqual(product.view_count, 1)

    def test_wrong_slug_redirects(self):
        product = make_product(self.producer, name='Carrots')

        response = self.client.get(reverse('catalogue:detail', args=[product.pk, 'wrong']))

        self.assertRedirects(response, product.get_absolute_url(), status_code=301)

    def test_verified_producer_page_lists_live_products(self):
        farm = make_producer('maire', name='Burren Hill Farm', verified=True)
        make_product(farm, name='Lamb chops', category='meat')
        make_product(farm, name='Hidden draft', status='draft')

        response = self.client.get(farm.get_absolute_url())

        self.assertContains(response, 'Lamb chops')
        self.assertNotContains(response, 'Hidden draft')

    def test_in_season(self):
        product = make_product(self.producer, season_months='5,6')

        self.assertTrue(product.in_season(5))
        self.assertFalse(product.in_season(10))
        self.assertTrue(make_product(self.producer, name='Onions').in_season(10))


class PhotoProcessingTests(TestCase):
    def test_png_with_transparency_becomes_jpeg(self):
        from apps.catalogue.photos import process_upload

        buffer = BytesIO()
        Image.new('RGBA', (300, 200), (10, 20, 30, 0)).save(buffer, format='PNG')
        buffer.seek(0)

        image, thumb = process_upload(buffer)

        self.assertTrue(image.name.endswith('.jpg'))
        self.assertTrue(thumb.name.endswith('-thumb.jpg'))
