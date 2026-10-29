# XIM surrounding-text conversion boundary

`vendor/window/x11.set_surrounding_text` validates its arguments but returns
`Unsupported` for a valid open, listening window. It does not register
`XNStringConversionCallback`, mutate preedit/focus state, or enqueue an edit.
The existing XIM preedit and committed-text paths continue independently.

The [Xlib specification](https://www.x.org/releases/X11R7.6/doc/libX11/specs/libX11/libX11.html#String_Conversion_Callback)
defines optional string-conversion callbacks for retrieving or deleting client
text. Position and extent use characters, and returned string/feedback storage
must be compatible with `XFree`. A correct callback alone is insufficient for
protocol transport qualification.

Audited upstream source: libX11 mirror commit
`ff8706a5eae25b8bafce300527079f68a201d27f`,
[`modules/im/ximcp/imCallbk.c`](https://github.com/mirror/libX11/blob/ff8706a5eae25b8bafce300527079f68a201d27f/modules/im/ximcp/imCallbk.c#L262).
In `_XimStrConversionCallback`:

- The reply copies from the address of `cbrec.text->string.mbs`, rather than
  the pointed-to text. This cannot serialize the returned string correctly and
  can read past the pointer field when the requested byte count is larger.
- The reply dereferences every `feedback[i]`, despite the specification allowing
  (and recommending) null feedback. A valid callback following that contract
  can therefore reach a null dereference.
- `cbrec.text` is not initialized before invoking the callback. The source
  also lacks the returned-storage cleanup described by the callback contract.

These are defects in the audited protocol reply path, not proof that every
local input-method module behaves identically. No public XIM capability query
reliably distinguishes a safe local callback implementation from that reply
path. Advertising success based on a mocked callback would consequently be
misleading. The backend remains explicitly unsupported until a safe transport
can be identified and qualified; no private libX11 layout or client-side memory
trick is used as a workaround.

`tests/window-surround-xim.py` exercises the production validation boundary and
proves that unsupported publication leaves the queue, preedit, focus state and
committed-text summary untouched. It requires no running input method.
