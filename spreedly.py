import httplib, urlparse, time, calendar, urllib
from datetime import datetime
from decimal import Decimal
from xml.etree.ElementTree import fromstring
from xml.etree import ElementTree
from base64 import b64encode

API_VERSION = 'v4'

class SpreedlyException(Exception):
    def __init__(self, code, msg):
        self.code = code
        self.msg = msg

    def __str__(self):
        return "%s, %s" % (self.code, self.msg)

def utc_to_local(dt):
    ''' Converts utc datetime to local'''
    secs = calendar.timegm(dt.timetuple())
    return datetime(*time.localtime(secs)[:6])

def str_to_datetime(s):
    ''' Converts ISO 8601 string (2009-11-10T21:11Z) to LOCAL datetime'''
    if s is None or s == '':
        return None
    return utc_to_local(datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ'))

class Protocol(object):

    reverse_adapters = {
        bool: lambda b: 'true' if b is True else 'false',
        datetime: str,
        str: str,
        unicode: unicode,
        int: str,
        long: str,
        Decimal: str,
        None: lambda s: '',
    }

    adapters = {
        'integer': int,
        'decimal': Decimal,
        'boolean': lambda s: s == 'true',
        'string': unicode,
        'datetime': str_to_datetime,
    }

    def __init__(self, token, site_name):
        self.auth = b64encode('%s:x' % token)
        self.base_host = 'spreedly.com'
        self.base_path = '/api/%s/%s' % (API_VERSION, site_name)
        self.base_url = 'https://%s%s' % (self.base_host, self.base_path)

    def query(self, url, data=None, method='GET'):
        url = '%s/%s' % (self.base_url, url)

        parts = urlparse.urlparse(url)
        port = parts.port or 443

        headers = {'Authorization': 'Basic %s' % self.auth}
        if method in ('POST', 'PUT'):
            headers['Content-Type'] = 'application/xml'

        con = httplib.HTTPSConnection(parts.hostname, port)
        data = data if data is not None else ''
        con.request(
            method,
            "%s?%s" % (parts.path, parts.query),
            data,
            headers
        )
        response = con.getresponse()
        
        if response.status > 299:
            raise SpreedlyException(response.status, response.read())

        return response.read()

    def get(self, url):
        return self._parse_tree(fromstring(self.query(url, method='GET')))
    
    def post(self, url, data):
        return self._parse_tree(fromstring(self.query(url, data=data, method='POST')))
    
    def put(self, url, data):
        return self.query(url, data=data, method='PUT')

    def delete(self, url):
        return self.query(url, method='DELETE')
    
    def _parse_tree(self, root):
        if root.get('type', None) == 'array':
            return [self._parse_tree(d) for d in list(root)]

        result = {}

        for element in list(root):
            element_type = element.get('type', 'string')
            text = element.text if element.text is not None else ''
            key = element.tag.replace('-', '_')

            if element_type == 'array':
                result[key] = self._parse_tree(element)
            else:
                if element_type != 'string' and text == '':
                    value = None
                else:
                    value = self.adapters[element_type](text)
                
                result[key] = value

        return result

    def serialize(self, val):
        return self.reverse_adapters[type(val)](val)

    def create_document(self, root_tag, **kwargs):
        root = ElementTree.Element(root_tag)

        for key, value in kwargs.iteritems():
            ElementTree.SubElement(root, key.replace('_', '-')).text = self.serialize(value)

        return ElementTree.tostring(root)

class Spreedly(object):
    def __init__(self, token, site_name):
        self.protocol = Protocol(token, site_name)

    def get_plans(self):
        return self.protocol.get('subscription_plans.xml')
    
    def create_subscriber(self, customer_id, **kwargs):
        kwargs['customer_id'] = customer_id
        data = self.protocol.create_document('subscriber', **kwargs)
        
        return self.protocol.post('subscribers.xml', data)
    
    def delete_subscriber(self, id):
        if 'test' in self.protocol.base_path:
            self.protocol.delete('subscribers/%s.xml' % id)
    
    def subscribe_to_trial(self, subscriber_id, plan_id):
        data = self.protocol.create_document('subscription-plan', id=plan_id)
        url = 'subscribers/%s/subscribe_to_free_trial.xml' % subscriber_id
        return self.protocol.post(url, data)
    
    def subscribe_to_plan(self, subscriber_id, feature_level):
        data = self.protocol.create_document('lifetime-complimentary-subscription', feature_level=feature_level)
        url = 'subscribers/%s/lifetime_complimentary_subscriptions.xml' % subscriber_id
        return self.protocol.post(url, data)
    
    def allow_another_trial(self, subscriber_id):
        url = 'subscribers/%s/allow_free_trial.xml' % subscriber_id
        return self.protocol.post(url, '')

    def cleanup(self):
        '''Removes ALL subscribers. NEVER USE IN PRODUCTION!'''
        if 'test' in self.protocol.base_path:
            self.protocol.delete('subscribers.xml')
    
    def get_subscriber(self, subscriber_id):
        url = 'subscribers/%s.xml' % subscriber_id
        return self.protocol.get(url)
        
    def update_subscriber(self, subscriber_id, **kwargs):
        url = 'subscribers/%s.xml' % subscriber_id
        data = self.protocol.create_document('subscriber', **kwargs)
        
        self.protocol.put(url, data)
        
def subscribe_url(site_name, customer_id, token, plan_id, return_url):
    return 'https://spreedly.com/%(site_name)s/subscribers/%(customer_id)s/%(token)s/subscribe/%(plan_id)d?return_url=%(return_url)s' % {
        'site_name': site_name,
        'customer_id': customer_id,
        'token': token,
        'plan_id': plan_id,
        'return_url': urllib.quote(return_url, ''),
    }

def change_subscription_url(site_name, token, return_url):
    return 'https://spreedly.com/%(site_name)s/subscriber_accounts/%(token)s?return_url=%(return_url)s' % {
        'site_name': site_name,
        'token': token,
        'return_url': urllib.quote(return_url, ''),
    }


__all__ = (Spreedly, SpreedlyException, subscribe_url, change_subscription_url)

if __name__ == '__main__':
    import unittest

    SPREEDLY_AUTH_TOKEN = 'a9e3cfde076fb343633aaf35f0578ec3d673b087'
    SPREEDLY_SITE_NAME = 'pingbrigadetest'

    class  TestCase(unittest.TestCase):

        subscriber_keys = ['subscription_plan_name', 'eligible_for_free_trial', 'updated_at', 'on_gift', 'ready_to_renew_since', 'billing_country', 'billing_last_name', 'on_metered', 'billing_zip', 'payment_account_on_file', 'customer_id', 'recurring', 'email', 'active_until', 'store_credit_currency_code', 'in_grace_period', 'billing_address1', 'billing_first_name', 'ready_to_renew', 'card_expires_before_next_auto_renew', 'active', 'billing_phone_number', 'billing_city', 'store_credit', 'screen_name', 'created_at', 'feature_level', 'grace_until', 'token', 'on_trial', 'lifetime_subscription', 'billing_state']

        plan_keys = ['charge_after_first_period', 'charge_later_duration_quantity', 'description', 'force_recurring', 'updated_at', 'feature_level', 'created_at', 'enabled', 'duration_units', 'plan_type', 'needs_to_be_renewed', 'duration_quantity', 'amount', 'charge_later_duration_units', 'return_url', 'terms', 'minimum_needed_for_charge', 'price', 'id', 'currency_code', 'name']

        def setUp(self):
            self.sclient = Spreedly(SPREEDLY_AUTH_TOKEN, SPREEDLY_SITE_NAME)

            # Remove all subscribers
            self.sclient.cleanup()

        def tearDown(self):
            # Remove all subscribers
            self.sclient.cleanup()

        def test_get_plans(self):
            for plan in self.sclient.get_plans():
                returned_keys = plan.keys()
                for key in self.plan_keys:
                    self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))

        def test_create_subscriber(self):
            subscriber_def = {
                'screen_name': 'test', 
                'billing_first_name': u'\u7684\u4e00\u4e2d\u5b78\u6709\u570b\u5927\u6703\u662f\u8cc7\u4eba',
                'billing_last_name': u'H\u00c9llo',
            }

            subscriber = self.sclient.create_subscriber(1, **subscriber_def)

            returned_keys = subscriber.keys()
            for key in self.subscriber_keys:
                self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))

            for key, value in subscriber_def.iteritems():
                self.assertEqual(value, subscriber[key], "Expected value for key %s does not equal return value." % key)

            # Delete subscriber
            self.sclient.delete_subscriber(1)

        def test_subscribe_trial(self):
            # Create a subscriber first
            subscriber = self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )

            # Subscribe to a free trial
            subscription = self.sclient.subscribe_to_trial(1, 10399)
            returned_keys = subscriber.keys()
            for key in self.subscriber_keys:
                self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))
            
            self.assertTrue(subscription['on_trial'] is True)

            # Delete subscriber
            self.sclient.delete_subscriber(1)
        
        def test_lifetime_subscription(self):
            # Create a subscriber first
            subscriber = self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )

            # Subscribe to a free trial
            subscription = self.sclient.subscribe_to_plan(1, 'free')
            returned_keys = subscriber.keys()
            for key in self.subscriber_keys:
                self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))
            
            #self.assertTrue(subscription['on_trial'] is True)

            # Delete subscriber
            self.sclient.delete_subscriber(1)

        def test_allow_another_trial(self):
            self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )

            # Subscribe to a free trial
            subscriber = self.sclient.allow_another_trial(1)
            returned_keys = subscriber.keys()
            for key in self.subscriber_keys:
                self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))
            
            self.assertEqual(subscriber['eligible_for_free_trial'], True)

        def test_delete_subscriber(self):
            self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )
            try:
                self.sclient.delete_subscriber(1)
            except Exception, e:
                self.assertFalse(False, "Failed to delete subscriber: %s" % e)

        def test_get_subscriber(self):
            self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )

            subscriber = self.sclient.get_subscriber(1)
            returned_keys = subscriber.keys()
            for key in self.subscriber_keys:
                self.assertTrue(key in returned_keys, "%s not in %s" % (key, returned_keys))

            self.assertEquals(subscriber['email'], '')
            self.assertEquals(subscriber['screen_name'], 'test')
            self.assertEquals(subscriber['billing_first_name'], 'First')
            self.assertEquals(subscriber['billing_last_name'], 'Last')
                
            self.sclient.delete_subscriber(1)
            
        def test_update_subscriber(self):
            self.sclient.create_subscriber(1,
                screen_name='test', 
                billing_first_name='First',
                billing_last_name='Last',
            )
            
            self.sclient.update_subscriber(1, email='jack@bauer.com', screen_name='jb')
            subscriber = self.sclient.get_subscriber(1)
            self.assertEquals(subscriber['email'], 'jack@bauer.com')
            self.assertEquals(subscriber['screen_name'], 'jb')
            
    unittest.main()

