#!/usr/bin/env python
# __BEGIN_LICENSE__
# Copyright (C) 2008-2010 United States Government as represented by
# the Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# __END_LICENSE__

import sys
import os
import logging
import datetime
import time
import traceback
import atexit

import zmq
from zmq.eventloop.zmqstream import ZMQStream
from zmq.eventloop import ioloop
ioloop.install()

from geocamUtil import anyjson as json
from geocamUtil.zmq.util import \
     DEFAULT_CENTRAL_RPC_PORT, \
     DEFAULT_CENTRAL_SUBSCRIBE_PORT, \
     DEFAULT_CENTRAL_PUBLISH_PORT, \
     getTimestamp

THIS_MODULE = 'zmqCentral'
DEFAULT_KEEPALIVE_MS = 10000


class ZmqCentral(object):
    def __init__(self, opts):
        self.opts = opts
        self.info = {}

    def announceConnect(self, moduleName, params):
        logging.debug('module %s connected', moduleName)
        self.publishAndLog('central.connect.%s:%s'
                           % (moduleName, json.dumps(params)))

    def announceDisconnect(self, moduleName):
        logging.info('module %s disconnected', moduleName)
        self.publishAndLog('central.disconnect.%s:%s'
                           % (moduleName,
                              json.dumps({'timestamp': getTimestamp()})))

    def publishAndLog(self, msg):
        timestamp = getTimestamp()
        self.pubStream.send(msg)
        self.messageLog.write('@@@ %d %d ' % (timestamp, len(msg)))
        self.messageLog.write(msg)
        self.messageLog.write('\n')

    def handleHeartbeat(self, params):
        moduleName = params['moduleName'].encode('utf-8')
        now = getTimestamp()
        params['centralTimestamp'] = now

        oldInfo = self.info.get(moduleName, None)
        if oldInfo:
            if oldInfo['pub'] != params['pub']:
                self.announceDisconnect(moduleName)
                self.announceConnect(moduleName, params)
        else:
            self.announceConnect(moduleName, params)

        self.info[moduleName] = params
        keepalive = params.get('keepalive', DEFAULT_KEEPALIVE_MS)
        params['timeout'] = now + keepalive
        return 'ok'

    def handleInfo(self, params):
        return self.info

    def handleMessages(self, messages):
        for msg in messages:
            if msg.startswith('central.heartbeat.'):
                try:
                    _topic, body = msg.split(':', 1)
                    self.handleHeartbeat(json.loads(body))
                except:  # pylint: disable=W0702
                    errClass, errObject, errTB = sys.exc_info()[:3]
                    errText = '%s.%s: %s' % (errClass.__module__,
                                             errClass.__name__,
                                             str(errObject))
                    logging.warning(''.join(traceback.format_tb(errTB)))
                    logging.warning(errText)
                    logging.warning('[error while handling heartbeat %s]', msg)
            self.publishAndLog(msg)

    def handleRpcCall(self, messages):
        for msg in messages:
            try:
                call = json.loads(msg)
                callId = call['id']
            except:  # pylint: disable=W0702
                self.rpcStream.send(json.dumps({'result': None,
                                                'error': 'malformed request'}))

            try:
                method = call['method']
                params = call['params']
                if method == 'info':
                    result = self.handleInfo(*params)
                else:
                    raise ValueError('unknown method %s' % method)
                self.rpcStream.send(json.dumps({'result': result,
                                                'error': None,
                                                'id': callId}))
            except:  # pylint: disable=W0702
                errClass, errObject, errTB = sys.exc_info()[:3]
                errText = '%s.%s: %s' % (errClass.__module__,
                                         errClass.__name__,
                                         str(errObject))
                logging.debug(''.join(traceback.format_tb(errTB)))
                logging.debug(errText)
                self.rpcStream.send(json.dumps({'result': None,
                                                'error': errText,
                                                'id': callId}))

    def handleDisconnectTimer(self):
        now = getTimestamp()
        disconnectModules = []
        for moduleName, entry in self.info.iteritems():
            timeout = entry.get('timeout', None)
            if timeout is not None and now > timeout:
                disconnectModules.append(moduleName)
        for moduleName in disconnectModules:
            self.announceDisconnect(moduleName)
            del self.info[moduleName]

    def readyLog(self, pathTemplate, timestamp):
        if '%s' in pathTemplate:
            timeText = timestamp.strftime('%Y-%m-%d-%H-%M-%S')
            logFile = pathTemplate % timeText
        else:
            logFile = pathTemplate
        if not os.path.exists(self.logDir):
            os.makedirs(self.logDir)
        logPath = os.path.join(self.logDir, logFile)
        if '%s' in pathTemplate:
            latestPath = os.path.join(self.logDir, pathTemplate % 'latest')
            if os.path.islink(latestPath):
                os.unlink(latestPath)
        os.symlink(logFile, latestPath)
        return logPath

    def start(self):
        # open log files
        now = datetime.datetime.utcnow()
        self.logDir = os.path.abspath(self.opts.logDir)
        self.messageLogPath = self.readyLog(self.opts.messageLog, now)
        self.messageLog = open(self.messageLogPath, 'a')
        self.consoleLogPath = self.readyLog(self.opts.consoleLog, now)

        rootLogger = logging.getLogger()
        rootLogger.setLevel(logging.DEBUG)
        fmt = logging.Formatter('%(asctime)s - %(levelname)-7s - %(message)s')
        fmt.converter = time.gmtime
        fh = logging.FileHandler(self.consoleLogPath)
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG)
        rootLogger.addHandler(fh)
        if self.opts.foreground:
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            ch.setFormatter(fmt)
            rootLogger.addHandler(ch)

        # daemonize
        if self.opts.foreground:
            logging.info('staying in foreground')
        else:
            logging.info('daemonizing')
            pid = os.fork()
            if pid != 0:
                os._exit(0)
            os.setsid()
            pid = os.fork()
            if pid != 0:
                os._exit(0)
            os.chdir('/')
            os.close(1)
            os.close(2)
            nullFd = os.open('/dev/null', os.O_RDWR)
            os.dup2(nullFd, 1)
            os.dup2(nullFd, 2)

        # set up zmq
        self.context = zmq.Context()
        self.rpcStream = ZMQStream(self.context.socket(zmq.REP))
        self.rpcStream.bind(self.opts.rpcEndpoint)
        self.rpcStream.on_recv(self.handleRpcCall)
        self.pubStream = ZMQStream(self.context.socket(zmq.PUB))
        self.pubStream.setsockopt(zmq.HWM, self.opts.highWaterMark)
        self.pubStream.bind(self.opts.publishEndpoint)

        self.subStream = ZMQStream(self.context.socket(zmq.SUB))
        self.subStream.bind(self.opts.subscribeEndpoint)
        self.subStream.setsockopt(zmq.SUBSCRIBE, '')
        self.subStream.on_recv(self.handleMessages)
        for entry in self.opts.subscribeTo:
            moduleName, endpoint = entry.split('@')
            self.subStream.connect(endpoint)
            self.info[moduleName] = {'moduleName': moduleName,
                                     'pub': endpoint}

        self.disconnectTimer = ioloop.PeriodicCallback(self.handleDisconnectTimer, 5000)
        self.disconnectTimer.start()

    def shutdown(self):
        self.messageLog.flush()


def main():
    import optparse
    parser = optparse.OptionParser('usage: %prog')
    parser.add_option('-r', '--rpcEndpoint',
                      default='tcp://127.0.0.1:%s' % DEFAULT_CENTRAL_RPC_PORT,
                      help='Endpoint to listen on for RPC requests [%default]')
    parser.add_option('-s', '--subscribeEndpoint',
                      default='tcp://127.0.0.1:%s' % DEFAULT_CENTRAL_SUBSCRIBE_PORT,
                      help='Endpoint to listen for messages on [%default]')
    parser.add_option('-p', '--publishEndpoint',
                      default='tcp://127.0.0.1:%s' % DEFAULT_CENTRAL_PUBLISH_PORT,
                      help='Endpoint to forward messages to [%default]')
    parser.add_option('--subscribeTo',
                      default=[],
                      action='append',
                      help='Non-central-aware publisher to subscribe to (format "moduleName@endpoint"; can specify multiple times)')
    parser.add_option('-d', '--logDir',
                      default='log',
                      help='Directory to place logs in [%default]')
    parser.add_option('-m', '--messageLog',
                      default='zmqCentral-messages-%s.txt',
                      help='Log file for message traffic [%default]')
    parser.add_option('-c', '--consoleLog',
                      default='zmqCentral-console-%s.txt',
                      help='Log file for debugging zmqCentral [%default]')
    parser.add_option('-f', '--foreground',
                      action='store_true', default=False,
                      help='Do not daemonize zmqCentral on startup')
    parser.add_option('--highWaterMark',
                      default=10000, type='int',
                      help='High-water mark for publish socket (see 0MQ docs) [%default]')
    opts, args = parser.parse_args()
    if args:
        parser.error('expected no args')
    zc = ZmqCentral(opts)
    zc.start()
    atexit.register(zc.shutdown)
    ioloop.IOLoop.instance().start()


if __name__ == '__main__':
    main()