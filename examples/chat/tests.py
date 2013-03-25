'''Tests the websocket middleware in pulsar.apps.ws.'''
from pulsar import send
from pulsar.apps import rpc, http
from pulsar.apps.http import HttpClient
from pulsar.apps.test import unittest, dont_run_with_thread

from .manage import server


class TestWebChat(unittest.TestCase):
    app = None
    concurrency = 'thread'
    
    @classmethod
    def setUpClass(cls):
        s = server(bind='127.0.0.1:0', name=cls.__name__,
                   concurrency=cls.concurrency)
        cls.app = yield send('arbiter', 'run', s)
        cls.uri = 'http://%s:%s' % cls.app.address
        cls.rpc = rpc.JsonProxy('%s/rpc' % cls.uri)
        cls.client = http.HttpClient()
        
    @classmethod
    def tearDownClass(cls):
        if cls.app is not None:
            yield send('arbiter', 'kill_actor', cls.app.name)
            
    def test_rpc(self):
        '''Send a message to the rpc'''
        response = yield self.client.get('%s/message' % self.uri).on_finished
        self.assertEqual(response.status_code, 101)
        result = yield self.rpc.message('Hi!')
        self.assertEqual(result, 'OK')