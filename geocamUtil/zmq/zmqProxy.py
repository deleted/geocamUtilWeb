#!/usr/bin/env python
# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys
import traceback

import tornado.ioloop
import tornado.web
from tornado import websocket

import zmq
from zmq.eventloop.zmqstream import ZMQStream
from zmq.eventloop import ioloop
ioloop.install()

from geocamUtil import anyjson as json
from geocamUtil.zmq.util import zmqLoop
from geocamUtil.zmq.subscriber import ZmqSubscriber

# pylint: disable=W0223

class JsonRpcService(object):
    """
    Very basic implementation of a JSON-RPC 2.0 service.
    """
    def writeResponse(self, response):
        """
        Implement in derived classes.
        """
        raise NotImplementedError()

    def writeError(self, rawRequest, requestId, code, message):
        print >> sys.stderr, 'Web client request error: %s' % message
        print >> sys.stderr, 'Request was: %s' % rawRequest
        response = {'jsonrpc': '2.0',
                    'error': {'code': code, 'message': message},
                    'id': requestId}
        self.writeResponse(response)

    def writeSuccess(self, requestId, result):
        response = {'jsonrpc': '2.0',
                    'result': result,
                    'id': requestId}
        self.writeResponse(response)

    def handleRequest(self, rawRequest):
        try:
            request = json.loads(rawRequest)
        except ValueError:
            self.writeError(rawRequest, None, -32700, 'invalid json')
            return

        version = request.get('jsonrpc', None)
        if version != '2.0':
            self.writeError(rawRequest, -32600, 'request does not have jsonrpc == "2.0"')
            return

        requestId = request.get('id', None)
        if requestId is None:
            self.writeError(rawRequest, -32600, 'request has no id')
            return

        params = request.get('params', None)
        if not isinstance(params, dict):
            self.writeError(rawRequest, requestId, -32600, 'params field must be a dict')
            return

        methodName = request.get('method', None)
        if isinstance(methodName, (str, unicode)):
            handlerName = 'handle_' + methodName
            handler = getattr(self, handlerName, None)
        else:
            handler = None
        if handler is None or not callable(handler):
            self.writeError(rawRequest, requestId, -32601, 'unknown method %s' % repr(method))
            return

        try:
            result = handler(**params)
        except:  # pylint: disable=W0702
            errClass, errObject, errTB = sys.exc_info()[:3]
            traceback.print_tb(errTB)
            print >> sys.stderr, '%s.%s: %s' % (errClass.__module__,
                                                errClass.__name__,
                                                str(errObject))
            self.writeError(rawRequest, requestId, -32000, 'internal server error')
            return

        self.writeSuccess(requestId, result)


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("The zmqProxy server forwards 0MQ messages via WebSockets. Point your WebSockets subscriber at ws://hostname:port/zmq/")


class ClientSocket(websocket.WebSocketHandler, JsonRpcService):
    def __init__(self, *args, **kwargs):
        super(ClientSocket, self).__init__(*args, **kwargs)
        self.handlers = {}

    def open(self):
        print "WebSocket opened"

    def writeResponse(self, response):
        self.write_message('zmqProxy.response:' + json.dumps(response))

    def on_message(self, text):
        self.handleRequest(text)

    def handle_subscribe(self, topic):
        topic = topic.encode('utf-8')
        print >> sys.stderr, 'Client subscribing to topic "%s"' % topic
        handlerId = proxyG.subscriber.subscribeRaw(topic, self.forward)
        self.handlers[handlerId] = 1
        return handlerId

    def handle_unsubscribe(self, handlerId):
        print >> sys.stderr, 'Client unsubscribing handler %s' % handlerId
        proxyG.subscriber.unsubscribe(handlerId)
        del self.handlers[handlerId]

    def forward(self, topic, msg):
        print >> sys.stderr, 'forward %s %s' % (topic, msg)
        self.write_message(''.join((topic, ':', msg)))

    def on_close(self):
        print "WebSocket closed"
        for handlerId in self.handlers.iterkeys():
            proxyG.subscriber.unsubscribe(handlerId)


class ZmqProxy(object):
    def __init__(self, opts):
        self.opts = opts

        self.subscriber = ZmqSubscriber(**ZmqSubscriber.getOptionValues(self.opts))
        self.application = tornado.web.Application([
            (r"^/?$", MainHandler),
            (r"^/zmq/$", ClientSocket),
            ])

    def start(self):
        # initialize zmq
        self.subscriber.start()

        # start serving web clients
        print 'binding to port %d' % self.opts.port
        self.application.listen(self.opts.port)


def main():
    import optparse
    parser = optparse.OptionParser('usage: %prog')
    parser.add_option('-p', '--port',
                      type='int', default=8001,
                      help='TCP port where websocket server should listen [%default]')
    ZmqSubscriber.addOptions(parser, 'zmqProxy')
    opts, args = parser.parse_args()
    if args:
        parser.error('expected no args')

    global proxyG
    proxyG = ZmqProxy(opts)
    proxyG.start()

    zmqLoop()


if __name__ == "__main__":
    main()
