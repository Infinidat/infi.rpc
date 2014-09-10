import sys
import linecache
from os import path, pardir, sep

# FIXME
BASEDIR = path.abspath(path.join(path.dirname(__file__), pardir, pardir, pardir))

from infi.gevent_utils.json_utils import encode, decode

def format_tb(tb, limit=None):
    """A shorthand for 'format_list(extract_stack(f, limit))."""
    return format_list(extract_tb(tb, limit))


def extract_tb(tb, limit=None):
    if limit is None:
        if hasattr(sys, 'tracebacklimit'):
            limit = sys.tracebacklimit
    list = []
    n = 0
    while tb is not None and (limit is None or n < limit):
        f = tb.tb_frame
        lineno = tb.tb_lineno
        co = f.f_code
        filename = co.co_filename
        name = co.co_name
        _locals = tb. tb_frame.f_locals
        linecache.checkcache(filename)
        line = linecache.getline(filename, lineno, f.f_globals)
        if line:
            line = line.strip()
        else:
            line = None
        list.append((filename, lineno, name, line, _locals))
        tb = tb.tb_next
        n = n + 1
    return list


def safe_json_repr(value, length_limit=1024):
    try:
        encoded_string = encode(value)
        if length_limit and len(encoded_string) > length_limit:
            raise AssertionError()
        return decode(encoded_string)
    except:
        pass
    try:
        encoded_string = repr(value)
        if length_limit and len(encoded_string) > length_limit:
            raise AssertionError()
        return encoded_string
    except:
        pass
    return object.__repr__(value)


def format_list(extracted_list):
    list = []
    for filename, lineno, name, line, _locals in extracted_list:
        relpath = "{}:{}".format(filename.replace(BASEDIR + sep, ''), str(lineno))
        item = dict(line=line, name=name, locals=dict(), relpath=relpath)
        if isinstance(_locals, dict):
            item['locals'] = {key: safe_json_repr(value) for key, value in _locals.iteritems()}
        list.append(item)
    return list
