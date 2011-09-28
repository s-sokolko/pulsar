import time

from .py2py3 import ispy3k, iteritems

__all__ = ['urlparse',
           'unquote',
           'urlsplit',
           'Headers',
           'bytes_to_str',
           'is_hoppish',
           'http_date']


weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
monthname = [None,
             'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

HOP_HEADERS = set("""
    connection keep-alive proxy-authenticate proxy-authorization
    te trailers transfer-encoding upgrade
    server date
    """.split())

if ispy3k:
    from urllib.parse import urlparse, unquote, urlsplit
    
    def bytes_to_str(b):
        return str(b, 'latin1')
    
else:
    from urlparse import urlparse, unquote, urlsplit
    
    def bytes_to_str(b):
        return b

    
def is_hoppish(header):
    return header.lower().strip() in HOP_HEADERS


def http_date(timestamp=None):
    """Return the current date and time formatted for a message header."""
    if timestamp is None:
        timestamp = time.time()
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
    s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
            weekdayname[wd],
            day, monthname[month], year,
            hh, mm, ss)
    return s

    
class Headers(object):
    
    def __init__(self, defaults=None):
        self._dict = {}
        self._keys = []
        if defaults is not None:
            self.extend(defaults)
    
    def __repr__(self):
        return self._dict.__repr__()
    __str__ = __repr__
    
    def extend(self, iterable):
        """Extend the headers with a dict or an iterable yielding keys and
        values.
        """
        if isinstance(iterable, dict):
            for key, value in iteritems(iterable):
                if isinstance(value, (tuple, list)):
                    for v in value:
                        self.add(key, v)
                else:
                    self.add(key, value)
        else:
            for key, value in iterable:
                self.add(key, value)
                
    def __iter__(self):
        d = self._dict
        for k in self._keys:
            yield k,d[k]

    def __len__(self):
        return len(self._keys)
    
    def __getitem__(self, key):
        ikey = key.lower()
        return self._dict[ikey]

    def __setitem__(self, key, value):
        key = key.lower()
        if value:
            if isinstance(value, (tuple, list)):
                value = ','.join(value)
            value = value.lower()
            if key in self._dict:
                value = ','.join((self._dict[key],value))
            else:
                self._keys.append(key)
            self._dict[key] = value
        
    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default
        