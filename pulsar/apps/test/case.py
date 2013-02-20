import sys
import io
import logging
from inspect import istraceback
from functools import partial

from pulsar import is_failure, multi_async, get_actor, maybe_async,\
                     is_async, maybe_failure, send
from pulsar.utils.pep import pickle


__all__ = ['TestRequest', 'sequential']


LOGGER = logging.getLogger('pulsar.test')

def sequential(cls):
    '''Decorator for a :class:`TestCase` which cause its test functions to run
sequentially rather than in an asynchronous fashion.'''
    cls._sequential_execution = True
    return cls

def test_method(cls, method):
    try:
        return cls(method)
    except ValueError:
        return None


class TestRequest(object):
    '''A class which wraps a test case class and runs all its test functions

.. attribute:: testcls

    A :class:`unittest.TestCase` class to be run on this request.

.. attribute:: tag

    A string indicating the tag associated with :attr:`testcls`.
'''
    def __init__(self, testcls, tag):
        self.testcls = testcls
        self.tag = tag

    def __repr__(self):
        return self.testcls.__name__
    __str__ = __repr__

    def start(self):
        worker = get_actor()
        worker.app.local.pop('runner')
        runner = worker.app.runner
        testcls = self.testcls
        if not isinstance(testcls, type):
            testcls = testcls()
        testcls.tag = self.tag
        testcls.cfg = worker.cfg
        LOGGER.debug('Testing %s', self)
        all_tests = runner.loadTestsFromTestCase(testcls)
        num = all_tests.countTestCases()
        if num:
            result = self.run(runner, testcls, all_tests, worker.cfg)
            result = maybe_async(result, max_errors=0)
            if is_async(result):
                return result.add_both(partial(self.close, runner, testcls))
        return self.close(runner, testcls)
        
    def run(self, runner, testcls, all_tests, cfg):
        '''Run all test functions from the :attr:`testcls` using the
following algorithm:

* Run the class method ``setUpClass`` of :attr:`testcls` if defined.
* Call :meth:`run_test` for each test functions in :attr:`testcls`
* Run the class method ``tearDownClass`` of :attr:`testcls` if defined.
'''
        run_test_function = runner.run_test_function
        sequential = getattr(testcls, '_sequential_execution', cfg.sequential)
        skip_tests = getattr(testcls, "__unittest_skip__", False)
        should_stop = False
        test_cls = test_method(testcls, 'setUpClass')
        timeout = cfg.timeout
        if test_cls and not skip_tests:
            outcome = yield run_test_function(testcls,
                                        getattr(testcls,'setUpClass'),
                                        timeout)
            should_stop = self.add_failure(test_cls, runner, outcome)
        #
        # run the tests
        if not should_stop:
            if sequential:
                # Loop over all test cases in class
                for test in all_tests:
                    yield self.run_test(test, runner, timeout)
            else:
                all = (self.run_test(test, runner, timeout) for test in all_tests)
                yield multi_async(all)
        #
        test_cls = test_method(testcls, 'tearDownClass')
        if test_cls and not skip_tests:
            outcome = yield run_test_function(testcls,
                                              getattr(testcls,'tearDownClass'),
                                              timeout)
            self.add_failure(test_cls, runner, outcome)
    
    def close(self, runner, testcls, result=None):
        # send runner result to monitor
        LOGGER.debug('Sending %s results back to monitor', self)
        send('monitor', 'test_result', testcls.tag,
             testcls.__name__, runner.result)
       
    def run_test(self, test, runner, timeout):
        '''\
Run a *test* function using the following algorithm

* Run :meth:`_pre_setup` method if available in :attr:`testcls`.
* Run :meth:`setUp` method in :attr:`testcls`.
* Run the test function.
* Run :meth:`tearDown` method in :attr:`testcls`.
* Run :meth:`_post_teardown` method if available in :attr:`testcls`.
'''
        try:
            ok = True
            runner.startTest(test)
            run_test_function = runner.run_test_function
            testMethod = getattr(test, test._testMethodName)
            if (getattr(test.__class__, "__unittest_skip__", False) or
                getattr(testMethod, "__unittest_skip__", False)):
                reason = (getattr(test.__class__,
                                  '__unittest_skip_why__', '') or
                          getattr(testMethod,
                                  '__unittest_skip_why__', ''))
                runner.addSkip(test, reason)
                raise StopIteration
            # _pre_setup function if available
            if hasattr(test,'_pre_setup'):
                outcome = yield run_test_function(test, test._pre_setup, timeout)
                ok = ok and not self.add_failure(test, runner, outcome)
            # _setup function if available
            if ok:
                outcome = yield run_test_function(test, test.setUp, timeout)
                ok = not self.add_failure(test, runner, outcome)
                if ok:
                    # Here we perform the actual test
                    outcome = yield run_test_function(test, testMethod, timeout)
                    ok = not self.add_failure(test, runner, outcome)
                    if ok:
                        test.result = outcome
                    outcome = yield run_test_function(test, test.tearDown, timeout)
                    ok = ok and not self.add_failure(test, runner, outcome)
            # _post_teardown
            if hasattr(test,'_post_teardown'):
                outcome = yield run_test_function(test,test._post_teardown, timeout)
                ok = ok and not self.add_failure(test, runner, outcome)
            # run the stopTest
            runner.stopTest(test)
        except StopIteration:
            pass
        except Exception as e:
            ok = ok and not self.add_failure(test, runner, e)
        else:
            if ok:
                runner.addSuccess(test)

    def add_failure(self, test, runner, failure):
        '''Add *failure* to the list of errors if *failure* is indeed a failure.
Return `True` if *failure* is a failure, otherwise return `False`.'''
        failure = maybe_failure(failure)
        if is_failure(failure):
            for trace in failure:
                e = trace[1]
                try:
                    raise e
                except test.failureException:
                    runner.addFailure(test, trace)
                except Exception:
                    runner.addError(test, trace)
                return True
        else:
            return False