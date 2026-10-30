"""GDB pretty-printers for Dyn debug builds.

Load with `source <sdk>/share/gdb/dyn.py`. Slices and strings are described as
{data, len} structs; these printers bound reads by len instead of a NUL byte.
"""
import gdb


def _slice_parts(value):
    t = value.type.strip_typedefs()
    if t.code != gdb.TYPE_CODE_STRUCT:
        return None
    fields = [f.name for f in t.fields()]
    if fields != ['data', 'len']:
        return None
    data = value['data']
    if data.type.strip_typedefs().code != gdb.TYPE_CODE_PTR:
        return None
    return data, int(value['len'])


def _limit():
    try:
        limit = gdb.parameter('print elements')
    except gdb.error:
        limit = 200
    return limit if limit else 1 << 31


class StringPrinter:
    def __init__(self, data, length):
        self.data, self.length = data, length

    def to_string(self):
        if self.length == 0:
            return '""'
        if int(self.data) == 0:
            return '<null, len=%d>' % self.length
        shown = min(self.length, _limit())
        try:
            raw = bytes(gdb.selected_inferior().read_memory(int(self.data), shown))
        except gdb.MemoryError:
            return '<unreadable 0x%x, len=%d>' % (int(self.data), self.length)
        text = raw.decode('utf-8', 'backslashreplace')
        text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\t', '\\t')
        return '"%s"%s' % (text, '...' if shown < self.length else '')

    def display_hint(self):
        return None


class SlicePrinter:
    def __init__(self, data, length):
        self.data, self.length = data, length

    def to_string(self):
        return 'len %d' % self.length

    def children(self):
        if int(self.data) == 0:
            return
        for i in range(min(self.length, _limit())):
            yield '[%d]' % i, (self.data + i).dereference()

    def display_hint(self):
        return 'array'


def lookup(value):
    parts = _slice_parts(value)
    if parts is None:
        return None
    data, length = parts
    element = data.type.strip_typedefs().target().strip_typedefs()
    if element.code == gdb.TYPE_CODE_INT and element.sizeof == 1 and element.name in ('u8', 'char', 'unsigned char'):
        return StringPrinter(data, length)
    return SlicePrinter(data, length)


def register(objfile=None):
    target = objfile if objfile is not None else gdb
    if lookup not in target.pretty_printers:
        target.pretty_printers.append(lookup)


register()
