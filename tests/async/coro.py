'''Deferred and asynchronous tools.'''
import unittest

from pulsar import Future, maybe_async, coroutine_return


def c_summation(value):
    result = yield value
    coroutine_return(result + 2)


class TestCoroDeferred(unittest.TestCase):

    def test_coroutine1(self):
        d1 = Deferred()
        a = maybe_async(c_summation(d1))
        d1.callback(1)
        yield a
        self.assertEqual(a.result(), 3)
        self.assertEqual(d1.result(), 1)

    def test_deferred1(self):
        a = Deferred()
        d1 = Deferred().add_callback(lambda r: a.callback(r+2))
        d1.callback(1)
        self.assertEqual(a.result(), 3)
        self.assertEqual(d1.result(), 3)

    def test_then1(self):
        a = Deferred()
        d1 = Deferred()
        d2 = d1.then().add_callback(lambda r: a.callback(r+2))
        d1.callback(1)
        self.assertEqual(a.result(), 3)
        self.assertEqual(d1.result(), 1)
        self.assertEqual(d2.result(), 3)

    def test_fail_coroutine1(self):
        d1 = Deferred()
        a = maybe_async(c_summation(d1))
        d1.callback('bla')
        try:
            yield a
        except TypeError:
            pass
        else:
            raise TypeError
        self.assertEqual(d1.result(), 'bla')

    def test_fail_deferred1(self):
        a = Deferred()
        d1 = Deferred().add_callback(lambda r: a.callback(r+2))\
                       .add_errback(a.callback)
        d1.callback('bla')
        d1.exception()  # to mute it
        self.assertRaises(TypeError, a.result)

    def test_fail_then1(self):
        a = Deferred()
        d1 = Deferred()
        d2 = d1.then().add_callback(lambda r: a.callback(r+2))\
                      .add_errback(a.callback)
        d1.callback('bla')
        self.assertRaises(TypeError, a.result)
        self.assertEqual(d1.result(), 'bla')
        d2.exception()  # to mute it
        self.assertRaises(TypeError, d2.result)
