import datetime as dt
import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from apps.catalogue import services as catalogue
from apps.catalogue.models import Product
from apps.messaging import services as messaging
from apps.orders import services as orders
from apps.orders.models import Order, OrderEvent, OrderItem
from apps.producers import services as producers
from apps.producers.models import CollectionPoint, CollectionSlot, Producer, SlotRule
from apps.reports import services as reports
from apps.saved import services as saved
from apps.subscriptions import services as subscriptions
from apps.subscriptions.models import Subscription

BUYERS = [
    ('aoife', 'Aoife', 'Byrne'),
    ('brian', 'Brian', 'Walsh'),
    ('ciara', 'Ciara', 'Doyle'),
    ('declan', 'Declan', 'Ryan'),
]

PRODUCERS = [
    {
        'username': 'maire', 'first_name': 'Máire', 'name': 'Burren Hill Farm', 'county': 'clare', 'verified': True,
        'description': 'Grass-fed beef and lamb from limestone pastures in the Burren, and free-range hens.',
        'point': ('Farm gate', 'Carron, Co. Clare'), 'rules': [(4, '16:00', '18:00', 60, 4), (5, '10:00', '13:00', 60, 6)],
        'products': [
            ('Grass-fed beef mince', 'meat', '500g', '6.50', 20, '', '', '', 'Minced from dry-aged forequarter.'),
            ('Lamb chops', 'meat', '500g', '9.50', 12, '', '', '3,4,5,6,7,8,9', 'Burren spring lamb.'),
            ('Free-range eggs', 'eggs', 'dozen', '4.50', 30, '', 'eggs', '', 'From hens that roam the hill.'),
            ('Beef sausages', 'meat', '500g', '7.00', 15,
             'beef (85%), rusk (wheat flour, salt, raising agent: ammonium bicarbonate), water, sea salt, black pepper, '
             'nutmeg', 'cereals_gluten', '', 'Made on the farm every Thursday.'),
            ('Dry-aged sirloin steak', 'meat', 'each', '14.00', 3, '', '', '', 'Aged 28 days on the bone.'),
        ],
    },
    {
        'username': 'sean', 'first_name': 'Seán', 'name': 'Kinsale Bay Fish', 'county': 'cork', 'verified': True,
        'description': 'Day-boat fish and rope-grown mussels landed at Kinsale.',
        'point': ('Pier kiosk', 'Kinsale Pier, Co. Cork'), 'rules': [(3, '15:00', '18:00', 60, 5)],
        'products': [
            ('Fresh hake fillets', 'fish', '500g', '9.00', 10, '', 'fish', '', 'Caught yesterday, filleted this morning.'),
            ('Rope-grown mussels', 'fish', 'kg', '6.00', 15, '', 'molluscs', '9,10,11,12,1,2,3,4', 'Cleaned and debearded.'),
            ('Oak-smoked salmon', 'fish', '250g', '11.50', 12, 'salmon (98%), salt, demerara sugar, oak smoke', 'fish',
             '', 'Cold-smoked over oak chips for 12 hours.'),
            ('Whole mackerel', 'fish', 'each', '3.50', 20, '', 'fish', '6,7,8,9', 'Line-caught in summer.'),
        ],
    },
    {
        'username': 'fiona', 'first_name': 'Fiona', 'name': 'Slaney Valley Dairy', 'county': 'carlow',
        'verified': True, 'description': 'A small herd of Friesians and Jerseys, milked on the banks of the Slaney.',
        'point': ('Dairy shop', 'Bunclody Road, Co. Carlow'), 'rules': [(5, '09:00', '12:00', 30, 3)],
        'products': [
            ('Whole milk', 'dairy', 'litre', '1.80', 40, 'whole milk', 'milk', '', 'Pasteurised, not homogenised.'),
            ('Natural yoghurt', 'dairy', '500g', '3.20', 25, 'whole milk, live cultures', 'milk', '', 'Thick and tangy.'),
            ('Farmhouse cheddar', 'dairy', '250g', '6.80', 18, "pasteurised cows' milk, salt, starter cultures, rennet",
             'milk', '', 'Matured for 12 months.'),
            ('Strawberry yoghurt', 'dairy', '500g', '3.60', 20, 'whole milk, strawberries (10%), sugar, live cultures',
             'milk', '', 'Made with Wexford strawberries.'),
            ('Salted butter', 'dairy', '250g', '3.90', 30, 'cream (milk), salt', 'milk', '', 'Churned weekly.'),
        ],
    },
    {
        'username': 'eoin', 'first_name': 'Eoin', 'name': 'Wexford Fruit Farm', 'county': 'wexford',
        'verified': True, 'description': 'Third-generation fruit growers near Enniscorthy.',
        'point': ('Farm shop', 'Enniscorthy, Co. Wexford'), 'rules': [(2, '14:00', '18:00', 60, 4), (5, '10:00', '14:00', 60, 6)],
        'products': [
            ('Wexford strawberries', 'fruit', '250g', '4.00', 40, '', '', '5,6,7,8', 'Picked the morning you collect.'),
            ('Bramley apples', 'fruit', 'kg', '2.80', 50, '', '', '9,10,11,12', 'The best cooking apple there is.'),
            ('Eating apples (Katy)', 'fruit', 'kg', '3.20', 40, '', '', '9,10,11', 'Crisp and sweet.'),
            ('Cloudy apple juice', 'drinks', 'litre', '4.50', 30, 'pressed apples (99.9%), vitamin C', '', '',
             'Pressed from our own apples.'),
            ('Strawberry jam', 'pantry', 'jar', '5.50', 20,
             'strawberries (55%), sugar, lemon juice, gelling agent: pectin', '', '', 'Made in small batches.'),
        ],
    },
    {
        'username': 'padraig', 'first_name': 'Pádraig', 'name': 'Nore Valley Organics', 'county': 'kilkenny',
        'verified': True, 'organic_cert_no': 'IE-ORG-0412',
        'description': 'Certified organic vegetables grown in rotation on 12 acres beside the River Nore.',
        'point': ("Kilkenny Farmers' Market", 'The Parade, Kilkenny'),
        'rules': [(3, '10:00', '14:00', 60, 6), (5, '09:00', '12:00', 60, 6)],
        'products': [
            ('Organic carrots', 'vegetables', 'kg', '2.20', 60, '', '', '7,8,9,10,11,12,1,2', 'Unwashed, so they keep.'),
            ('Organic kale', 'vegetables', 'bunch', '2.50', 30, '', '', '10,11,12,1,2,3', 'Curly and cavolo nero.'),
            ('Organic Rooster potatoes', 'vegetables', 'kg', '1.80', 100, '', '', '', 'Floury, for roasting.'),
            ('Organic leeks', 'vegetables', 'kg', '3.00', 30, '', '', '10,11,12,1,2,3', ''),
            ('Organic butternut squash', 'vegetables', 'each', '3.50', 20, '', '', '9,10,11', ''),
            ('Organic asparagus', 'vegetables', 'bunch', '5.00', 0, '', '', '5,6', 'A short season in May and June.'),
        ],
        'boxes': [
            ('Small organic veg box', '18.00', 15, 'Six to eight seasonal vegetables for one or two people.'),
            ('Family organic veg box', '28.00', 10, 'Ten or more seasonal vegetables for a family of four.'),
        ],
    },
    {
        'username': 'grainne', 'first_name': 'Gráinne', 'name': 'Copper Kettle Bakery', 'county': 'galway',
        'verified': True, 'description': 'A craft bakery in Galway city: long-fermented breads and pastries.',
        'point': ('Shop counter', 'Shop Street, Galway'), 'rules': [(4, '08:00', '12:00', 60, 5), (5, '08:00', '12:00', 60, 5)],
        'products': [
            ('Sourdough loaf', 'bakery', 'each', '6.50', 24, 'organic wheat flour, water, sea salt', 'cereals_gluten', '',
             'Fermented for 36 hours.'),
            ('Brown soda bread', 'bakery', 'each', '4.20', 20,
             'wholemeal wheat flour, buttermilk, wheat flour, bicarbonate of soda, salt', 'cereals_gluten,milk', '',
             'The way Gráinne’s grandmother made it.'),
            ('Rye sourdough', 'bakery', 'each', '6.80', 12, 'rye flour, water, salt', 'cereals_gluten', '', 'Dense and dark.'),
            ('Butter croissant', 'bakery', 'each', '2.80', 40,
             'wheat flour, butter (milk) (28%), water, sugar, yeast, salt, egg', 'cereals_gluten,milk,eggs', '',
             'Laminated by hand.'),
            ('Sandwich toast loaf', 'bakery', 'each', '3.20', 20,
             'wheat flour, water, yeast, rapeseed oil, salt, emulsifiers: E471, E472e, '
             'flour treatment agent: ascorbic acid', 'cereals_gluten', '',
             'Our soft loaf for sandwiches. It needs emulsifiers to stay soft, and our analyser says so.'),
        ],
    },
    {
        'username': 'niamh', 'first_name': 'Niamh', 'name': "Niamh's Kitchen", 'county': 'dublin', 'verified': False,
        'description': 'Jams, chutneys and granola made in a Rathmines kitchen.',
        'point': ('Doorstep pickup', 'Rathmines, Dublin 6'), 'rules': [(6, '11:00', '13:00', 60, 4)],
        'products': [
            ('Rhubarb and ginger jam', 'pantry', 'jar', '5.00', 12, 'rhubarb (60%), sugar, ginger, lemon juice', '', '',
             'Tart and warming.'),
            ('Tomato chutney', 'pantry', 'jar', '5.50', 10,
             'tomatoes, onions, cider vinegar, brown sugar, raisins, mustard seeds, salt, spices', 'mustard', '', ''),
            ('Honey and seed granola', 'pantry', '500g', '7.50', 15,
             'rolled oats (55%), honey, sunflower seeds, pumpkin seeds, almonds, rapeseed oil, cinnamon',
             'cereals_gluten,nuts', '', 'Baked low and slow.'),
            ('Raw Dublin honey', 'pantry', 'jar', '9.00', 8, 'honey', '', '', 'From hives in Dartry.'),
            ('Cold-pressed rapeseed oil', 'pantry', 'litre', '8.50', 10, 'cold pressed rapeseed oil', '', '', ''),
        ],
    },
    {
        'username': 'ciaran', 'first_name': 'Ciarán', 'name': 'Ciarán’s Snack Co.', 'county': 'louth', 'verified': False,
        'description': 'Snacks and bars from Dundalk.',
        'point': ('Dundalk unit', 'Coes Road, Dundalk'), 'rules': [(5, '12:00', '14:00', 60, 4)],
        'products': [
            ('Chocolate protein bar', 'pantry', 'each', '2.20', 60,
             'milk chocolate (sugar, cocoa butter, whole milk powder, cocoa mass, emulsifier: soya lecithin, '
             'flavouring), soy protein isolate, glucose syrup, humectant: glycerol, palm fat, sweetener: sucralose, '
             'salt', 'milk,soybeans', '', '20 g of protein.'),
            ('Cheese and onion crisps', 'pantry', 'each', '1.50', 80,
             'potatoes, sunflower oil, cheese and onion seasoning (whey powder, onion powder, salt, cheese powder '
             '(milk), flavour enhancer: monosodium glutamate, yeast extract, acidity regulator: citric acid, '
             'colour: annatto)', 'milk', '', ''),
            ('Sea salt crisps', 'pantry', 'each', '1.40', 80, 'potatoes, sunflower oil, sea salt', '', '',
             'Just three ingredients.'),
            ('Citrus energy drink', 'drinks', 'each', '1.90', 50,
             'carbonated water, sugar, acid: citric acid, taurine, acidity regulator: sodium citrates, flavourings, '
             'caffeine, colour: E150d, sweetener: sucralose', '', '', ''),
        ],
    },
    {
        'username': 'orla', 'first_name': 'Orla', 'name': "Orla's Ferments", 'county': 'cork', 'verified': False,
        'description': 'Live ferments from a stall at Mahon Point.',
        'point': ('Mahon Point market stall', 'Mahon Point, Cork'), 'rules': [(3, '10:00', '14:00', 60, 4)],
        'products': [
            ('Kimchi', 'pantry', 'jar', '7.00', 20,
             'napa cabbage (70%), radish, spring onion, garlic, ginger, chilli, sea salt, fish sauce (anchovy, salt)',
             'fish', '', 'Fermented for two weeks.'),
            ('Sauerkraut', 'pantry', 'jar', '6.00', 20, 'white cabbage, sea salt', '', '', ''),
            ('Ginger kombucha', 'drinks', 'each', '3.80', 30, 'filtered water, green tea, raw cane sugar, ginger, live cultures',
             '', '', 'Low in sugar by the time it is bottled.'),
        ],
    },
]


class Command(BaseCommand):
    help = 'Load demo producers, products, orders, subscriptions and reviews. Prints fresh passwords.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete the existing demo data first.')

    def handle(self, *args, **options):
        usernames = self.demo_usernames()
        if User.objects.filter(username__in=usernames).exists():
            if not options['reset']:
                self.stdout.write('Demo data already exists. Run with --reset to rebuild it.')
                return
            self.reset(usernames)
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'), transaction.atomic():
            passwords = self.build()
        self.stdout.write(self.style.SUCCESS('Demo data loaded. Log in with:'))
        self.stdout.write(f'  {"username":<14} {"role":<40} password')
        for username, role, password in passwords:
            self.stdout.write(f'  {username:<14} {role:<40} {password}')

    def demo_usernames(self):
        return ['harvest_admin'] + [b[0] for b in BUYERS] + [p['username'] for p in PRODUCERS]

    def reset(self, usernames):
        users = User.objects.filter(username__in=usernames)
        Subscription.objects.filter(buyer__in=users).delete()
        Subscription.objects.filter(box__producer__user__in=users).delete()
        Order.objects.filter(buyer__in=users).delete()
        Order.objects.filter(producer__user__in=users).delete()
        users.delete()

    def user(self, username, first_name, last_name='', **extra):
        password = secrets.token_urlsafe(9)
        user = User.objects.create_user(username, f'{username}@example.com', password, first_name=first_name,
                                        last_name=last_name, **extra)
        return user, password

    def build(self):
        passwords = []
        admin, password = self.user('harvest_admin', 'Harvest', 'Admin', is_staff=True, is_superuser=True)
        passwords.append(('harvest_admin', 'staff (admin site)', password))
        buyers = {}
        for username, first, last in BUYERS:
            buyers[username], password = self.user(username, first, last)
            passwords.append((username, 'buyer', password))

        farms = {}
        for spec in PRODUCERS:
            user, password = self.user(spec['username'], spec['first_name'])
            role = 'verified farm' if spec['verified'] else 'home producer'
            passwords.append((spec['username'], f'{role}: {spec["name"]}', password))
            farms[spec['username']] = self.producer(user, spec)

        self.orders(buyers, farms)
        self.extras(buyers, farms, admin)
        return passwords

    def producer(self, user, spec):
        producer = producers.create_producer(user, spec['name'], spec['county'], spec['description'])
        if spec['verified']:
            application = producers.apply_for_verification(
                producer, spec['name'], f'IE-{secrets.randbelow(900000) + 100000}', spec['county'], spec['description'])
            producers.approve_application(application)
            producer.refresh_from_db()
            producer.organic_cert_no = spec.get('organic_cert_no', '')
            producer.save()
        point = CollectionPoint.objects.create(producer=producer, name=spec['point'][0], address=spec['point'][1],
                                               county=spec['county'])
        for weekday, start, end, minutes, capacity in spec['rules']:
            SlotRule.objects.create(point=point, weekday=weekday, start_time=dt.time.fromisoformat(start),
                                    end_time=dt.time.fromisoformat(end), slot_minutes=minutes, capacity=capacity)
        producers.generate_slots(point=point)
        organic = bool(spec.get('organic_cert_no'))
        for name, category, unit, price, stock, ingredients, allergens, season, description in spec['products']:
            product = catalogue.save_product(producer, {
                'name': name, 'category': category, 'unit': unit, 'price': Decimal(price), 'stock': stock,
                'ingredients': ingredients, 'description': description, 'organic': organic,
                'allergens': [a for a in allergens.split(',') if a],
                'season_months': [int(m) for m in season.split(',') if m], 'kind': 'standard',
            })
            catalogue.publish(product)
        for name, price, max_subscribers, description in spec.get('boxes', []):
            box = catalogue.save_product(producer, {
                'name': name, 'category': 'vegetables', 'unit': 'box', 'price': Decimal(price), 'stock': 0,
                'ingredients': '', 'description': description, 'organic': organic, 'allergens': [],
                'season_months': [], 'kind': 'box', 'box_frequency': 'weekly', 'max_subscribers': max_subscribers,
            })
            catalogue.publish(box)
        return producer

    def product(self, producer, name):
        return Product.objects.get(producer=producer, name=name)

    def checkout(self, buyer, producer, items):
        for name, quantity in items:
            orders.add_to_basket(buyer, self.product(producer, name), quantity)
        slot = orders.available_slots(buyer, producer)[0]
        orders.reserve(buyer, producer, slot)
        return orders.confirm(buyer, producer, slot)

    def past_order(self, buyer, producer, items, days_ago, status, payment='cash'):
        point = producer.points.first()
        start = (timezone.now() - timedelta(days=days_ago)).replace(minute=0, second=0, microsecond=0)
        slot, _ = CollectionSlot.objects.get_or_create(point=point, start=start, defaults={
            'end': start + timedelta(hours=1), 'capacity': 6})
        order = Order.objects.create(number=orders.next_order_number(start.year), buyer=buyer, producer=producer,
                                     slot=slot, point=point, status=status, total=Decimal('0.00'))
        total = Decimal('0.00')
        for name, quantity in items:
            product = self.product(producer, name)
            line = product.price * quantity
            OrderItem.objects.create(order=order, product=product, name=product.name, unit=product.get_unit_display(),
                                     unit_price=product.price, quantity=quantity, line_total=line)
            total += line
        order.total = total
        order.accepted_at = order.ready_at = start - timedelta(hours=20)
        if status == Order.Status.COLLECTED:
            order.collected_at, order.payment_method = start + timedelta(minutes=20), payment
        if status == Order.Status.NO_SHOW:
            order.no_show_at = start + timedelta(hours=3)
        order.closed_at = start + timedelta(hours=3)
        order.save()
        for previous, current in (('', 'pending'), ('pending', 'accepted'), ('accepted', 'ready'), ('ready', status)):
            OrderEvent.objects.create(order=order, actor=producer.user if previous else buyer, from_status=previous,
                                      to_status=current)
        return order

    def orders(self, buyers, farms):
        aoife, brian, ciara = buyers['aoife'], buyers['brian'], buyers['ciara']
        burren, kinsale, slaney = farms['maire'], farms['sean'], farms['fiona']
        wexford, nore, bakery = farms['eoin'], farms['padraig'], farms['grainne']

        pending = self.checkout(aoife, burren, [('Free-range eggs', 2), ('Lamb chops', 1)])
        messaging.post_message(pending, aoife, 'Hi! Could I collect at the start of the slot? Thanks.')
        messaging.post_message(pending, burren.user, 'Of course, see you then.')

        accepted = self.checkout(aoife, bakery, [('Sourdough loaf', 1), ('Butter croissant', 4)])
        orders.perform(accepted, bakery.user, 'accept')

        ready = self.checkout(brian, slaney, [('Farmhouse cheddar', 1), ('Natural yoghurt', 2)])
        orders.perform(ready, slaney.user, 'accept')
        orders.perform(ready, slaney.user, 'mark_ready')

        cancelled = self.checkout(brian, kinsale, [('Fresh hake fillets', 1)])
        orders.perform(cancelled, brian, 'cancel')

        rejected = self.checkout(brian, wexford, [('Bramley apples', 3)])
        orders.perform(rejected, wexford.user, 'reject', reason='A hailstorm damaged this week’s apples, sorry!')

        self.past_order(aoife, nore, [('Organic carrots', 2), ('Organic kale', 1)], 9, Order.Status.COLLECTED)
        self.past_order(aoife, kinsale, [('Rope-grown mussels', 2)], 16, Order.Status.COLLECTED, 'card')
        self.past_order(ciara, burren, [('Grass-fed beef mince', 2), ('Free-range eggs', 1)], 6, Order.Status.COLLECTED)
        self.past_order(ciara, bakery, [('Rye sourdough', 1)], 12, Order.Status.NO_SHOW)
        self.past_order(brian, nore, [('Organic Rooster potatoes', 5)], 20, Order.Status.COLLECTED, 'card')

    def extras(self, buyers, farms, admin):
        aoife, brian, ciara, declan = buyers['aoife'], buyers['brian'], buyers['ciara'], buyers['declan']
        nore, kinsale, burren = farms['padraig'], farms['sean'], farms['maire']

        producers.save_review(aoife, nore, 5, 'The best carrots I have ever eaten, and the kale lasts all week.')
        producers.save_review(aoife, kinsale, 4, 'Lovely mussels. The kiosk was busy but worth the wait.')
        producers.save_review(brian, nore, 5, 'Proper floury Roosters. Pádraig always has a tip for cooking them.')
        review = producers.save_review(ciara, burren, 5, 'You can taste the difference in grass-fed beef.')
        producers.reply(review, burren.user, 'Thanks Ciara, the herd says hello!')

        box = Product.objects.get(producer=nore, name='Small organic veg box')
        rule = min(SlotRule.objects.filter(point__producer=nore), key=subscriptions.first_bookable_date)
        subscriptions.subscribe(declan, box, rule)
        subscriptions.generate_box_orders()

        saved.toggle_favourite(aoife, Product.objects.get(name='Wexford strawberries'))
        saved.toggle_favourite(aoife, Product.objects.get(name='Organic asparagus'))
        saved.save_search(ciara, 'Organic veg in Kilkenny', 'q=organic&county=kilkenny&category=vegetables')

        crisps = Product.objects.get(name='Cheese and onion crisps')
        reports.file_report(crisps, brian, 'misleading_ingredients',
                            'The bag says "all natural" but the label lists MSG and yeast extract.')
