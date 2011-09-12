# Author: Jacob Kristhammar, 2010
#
# Updated version of websocket.py[1] that implements latest[2] stable version
# of the websocket protocol.
#
# NB. It's no longer possible to manually select which callback that should
#     be invoked upon message reception. Instead you must override the
#     on_message(message) method to handle incoming messsages.
#     This also means that you don't have to explicitly invoke
#     receive_message, in fact you shouldn't.
#
# [1] http://github.com/facebook/tornado/blob/
#     2c89b89536bbfa081745336bb5ab5465c448cb8a/tornado/websocket.py
# [2] http://tools.ietf.org/html/draft-hixie-thewebsocketprotocol-76

import functools
import hashlib
import logging
import re
import struct
import time

import pulsar
from pulsar.utils.py2py3 import to_bytestring

from .wsgi import PulsarWsgiHandler, Request


__all__ = ['WebSocketRequest','WebSocket']


class WebSocketRequest(Request):
    """A single WebSocket request.

    This class provides basic functionality to process WebSockets requests as
    specified in
    http://tools.ietf.org/html/draft-hixie-thewebsocketprotocol-76
    """
    fields = ("HTTP_ORIGIN",
              "HTTP_HOST",
              "HTTP_SEC_WEBSOCKET_KEY1",
              "HTTP_SEC_WEBSOCKET_KEY2")
    
    def _init(self):
        self._handle_websocket_headers()
        challenge = self.environ['wsgi.input'].read()
        self.challenge = self.challenge_response(challenge)

    def challenge_response(self, challenge):
        """Generates the challange response that's needed in the handshake

        The challenge parameter should be the raw bytes as sent from the
        client.
        """
        key_1 = self.environ.get("HTTP_SEC_WEBSOCKET_KEY1")
        key_2 = self.environ.get("HTTP_SEC_WEBSOCKET_KEY2")
        try:
            part_1 = self._calculate_part(key_1)
            part_2 = self._calculate_part(key_2)
        except ValueError:
            raise ValueError("Invalid Keys/Challenge")
        return self._generate_challenge_response(part_1, part_2, challenge)

    def _handle_websocket_headers(self):
        """Verifies all invariant- and required headers

        If a header is missing or have an incorrect value ValueError will be
        raised
        """
        environ = self.environ
        if environ.get("HTTP_UPGRADE", '').lower() != "websocket" or \
           environ.get("HTTP_CONNECTION", '').lower() != "upgrade" or \
           not all(map(lambda f: environ.get(f), self.fields)):
            raise pulsar.BadHttpRequest(400,"Missing/Invalid WebSocket headers")
        self.origin = environ.get('HTTP_ORIGIN')
        self.protocol = environ.get('HTTP_WEBSOCKET_PROTOCOL')
        
    def _calculate_part(self, key):
        """Processes the key headers and calculates their key value.

        Raises ValueError when feed invalid key."""
        key = to_bytestring(key)
        number, spaces = filter(str.isdigit, key), filter(str.isspace, key)
        try:
            key_number = int(number) / len(spaces)
        except (ValueError, ZeroDivisionError):
            raise ValueError
        return struct.pack(">I", key_number)

    def _generate_challenge_response(self, part_1, part_2, part_3):
        m = hashlib.md5()
        m.update(part_1)
        m.update(part_2)
        m.update(part_3)
        return m.digest()


class WebSocket(PulsarWsgiHandler):
    """Subclass this class to create a basic WebSocket handler.

    Override on_message to handle incoming messages. You can also override
    open and on_close to handle opened and closed connections.

    See http://www.w3.org/TR/2009/WD-websockets-20091222/ for details on the
    JavaScript interface. This implement the protocol as specified at
    http://tools.ietf.org/html/draft-hixie-thewebsocketprotocol-76.

    Here is an example Web Socket handler that echos back all received messages
    back to the client:

      class EchoWebSocket(websocket.WebSocketHandler):
          def open(self):
              print "WebSocket opened"

          def on_message(self, message):
              self.write_message(u"You said: " + message)

          def on_close(self):
              print "WebSocket closed"

    Web Sockets are not standard HTTP connections. The "handshake" is HTTP,
    but after the handshake, the protocol is message-based. Consequently,
    most of the Tornado HTTP facilities are not available in handlers of this
    type. The only communication methods available to you are write_message()
    and close(). Likewise, your request handler class should
    implement open() method rather than get() or post().

    If you map the handler above to "/websocket" in your application, you can
    invoke it in JavaScript with:

      var ws = new WebSocket("ws://localhost:8888/websocket");
      ws.onopen = function() {
         ws.send("Hello, world");
      };
      ws.onmessage = function (evt) {
         alert(evt.data);
      };

    This script pops up an alert box that says "You said: Hello, world".
    """
    REQUEST = WebSocketRequest
    
    def _init(self, handler = None, **kwargs):
        self.handler = handler

    def execute(self, request, start_response):
        self.open_args = args
        self.open_kwargs = kwargs
        try:
            self.ws_request = WebSocketRequest(self.request)
        except ValueError:
            logging.debug("Malformed WebSocket request received")
            self._abort()
            return
        scheme = "wss" if self.request.protocol == "https" else "ws"
        # Write the initial headers before attempting to read the challenge.
        # This is necessary when using proxies (such as HAProxy), which
        # need to see the Upgrade headers before passing through the
        # non-HTTP traffic that follows.
        self.stream.write(
            "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
            "Upgrade: WebSocket\r\n"
            "Connection: Upgrade\r\n"
            "Server: TornadoServer/%(version)s\r\n"
            "Sec-WebSocket-Origin: %(origin)s\r\n"
            "Sec-WebSocket-Location: %(scheme)s://%(host)s%(uri)s\r\n\r\n" % (dict(
                    version=tornado.version,
                    origin=self.request.headers["Origin"],
                    scheme=scheme,
                    host=self.request.host,
                    uri=self.request.uri)))
        self.stream.read_bytes(8, self._handle_challenge)

    def _handle_challenge(self, challenge):
        try:
            challenge_response = self.ws_request.challenge_response(challenge)
        except ValueError:
            logging.debug("Malformed key data in WebSocket request")
            self._abort()
            return
        self._write_response(challenge_response)

    def _write_response(self, challenge):
        self.stream.write("%s" % challenge)
        self.async_callback(self.open)(*self.open_args, **self.open_kwargs)
        self._receive_message()

    def write_message(self, message):
        """Sends the given message to the client of this Web Socket."""
        if isinstance(message, dict):
            message = tornado.escape.json_encode(message)
        if isinstance(message, unicode):
            message = message.encode("utf-8")
        assert isinstance(message, str)
        self.stream.write("\x00" + message + "\xff")

    def open(self, *args, **kwargs):
        """Invoked when a new WebSocket is opened."""
        pass

    def on_message(self, message):
        """Handle incoming messages on the WebSocket

        This method must be overloaded
        """
        raise NotImplementedError

    def on_close(self):
        """Invoked when the WebSocket is closed."""
        pass

    def close(self):
        """Closes this Web Socket.

        Once the close handshake is successful the socket will be closed.
        """
        if self.client_terminated and self._waiting:
            tornado.ioloop.IOLoop.instance().remove_timeout(self._waiting)
            self.stream.close()
        else:
            self.stream.write("\xff\x00")
            self._waiting = tornado.ioloop.IOLoop.instance().add_timeout(
                                time.time() + 5, self._abort)

    def _abort(self):
        """Instantly aborts the WebSocket connection by closing the socket"""
        self.client_terminated = True
        self.stream.close()

    def _receive_message(self):
        self.stream.read_bytes(1, self._on_frame_type)

    def _on_frame_type(self, byte):
        frame_type = ord(byte)
        if frame_type == 0x00:
            self.stream.read_until("\xff", self._on_end_delimiter)
        elif frame_type == 0xff:
            self.stream.read_bytes(1, self._on_length_indicator)
        else:
            self._abort()

    def _on_end_delimiter(self, frame):
        if not self.client_terminated:
            self.async_callback(self.on_message)(
                    frame[:-1].decode("utf-8", "replace"))
            self._receive_message()

    def _on_length_indicator(self, byte):
        if ord(byte) != 0x00:
            self._abort()
            return
        self.client_terminated = True
        self.close()

    def on_connection_close(self):
        self.client_terminated = True
        self.on_close()

    def _not_supported(self, *args, **kwargs):
        raise Exception("Method not supported for Web Sockets")




