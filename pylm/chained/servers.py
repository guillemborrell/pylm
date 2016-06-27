from pylm.persistence.kv import DictDB
from pylm.components.connections import PushConnection
from pylm.components.core import Router, zmq_context
from pylm.components.messages_pb2 import PalmMessage
from pylm.components.utils import PushHandler, Pinger, PerformanceCounter, CacheService
from pylm.components.services import PullService, WorkerPullService, WorkerPushService
from google.protobuf.message import DecodeError
from threading import Thread
import traceback
import logging
import zmq
import sys


class Server(object):
    def __init__(self, name, pull_address, next_address,
                 db_address, log_address, perf_address, ping_address,
                 cache=DictDB(), palm=False, debug_level=logging.DEBUG,
                 messages=sys.maxsize):

        self.name = name
        self.cache = cache

        # Addresses
        self.pull_address = pull_address
        self.next_address = next_address

        self.pull = zmq_context.socket(zmq.PULL)
        self.pull.bind(pull_address)

        self.push = zmq_context.socket(zmq.PUSH)
        self.push.connect(next_address)

        # Configure the log handler
        handler = PushHandler(log_address)
        self.logger = logging.getLogger(name)
        self.logger.addHandler(handler)
        self.logger.setLevel(debug_level)

        # Handle that controls if the messages have to be processed
        self.palm = palm

        # Maximum number of messages
        self.messages = messages

        # Message already allocated
        self.message = PalmMessage()

        # Configure the performance counter
        self.perfcounter = PerformanceCounter(listen_address=perf_address)

        # Configure the pinger.
        self.pinger = Pinger(listen_address=ping_address, every=30.0)

        # Configure the cache server
        self.db_address = db_address
        self.cache_service = CacheService(self.name,
                                          db_address,
                                          self.logger,
                                          cache=self.cache)

        # This is the pinger thread that keeps the pinger alive.
        pinger_thread = Thread(target=self.pinger.start)
        pinger_thread.daemon = True
        pinger_thread.start()

    def start(self):
        threads = [
            Thread(target=self.cache_service.start)
        ]
        for t in threads:
            t.start()

        for i in range(self.messages):
            message_data = self.pull.recv()
            self.logger.debug('{} Got a message'.format(self.name))
            result = b'0'
            try:
                self.message.ParseFromString(message_data)
                [server, function] = self.message.function.split('.')
                try:
                    user_function = getattr(self, function)
                    self.logger.debug('Looking for {}'.format(function))
                    try:
                        # This is a little exception for the cache to accept
                        # a value
                        if self.message.HasField('cache'):
                            result = user_function(self.message.payload,
                                                   self.message.cache)
                        else:
                            result = user_function(self.message.payload)

                    except:
                        self.logger.error('{} User function gave an error'.format(self.name))
                        exc_type, exc_value, exc_traceback = sys.exc_info()
                        lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                        for l in lines:
                            self.logger.exception(l)

                except AttributeError:
                    self.logger.error('Function {} was not found'.format(function))
            except DecodeError:
                self.logger.error('Message could not be decoded')

            self.message.payload = result
            self.push.send(self.message.SerializeToString())


class Master(object):
    def __init__(self, name, pull_address, next_address,
                 worker_pull_address, worker_push_address, db_address,
                 log_address, perf_address, ping_address, cache=DictDB(),
                 palm=False, debug_level=logging.DEBUG):
        """
        Connected PALM master server. It gets a message from the pull socket, that
        is bind, and sends the result from the push socket connected to the next_address
        :param name: Name of the server
        :param pull_address: Pull address to be bind
        :param next_address: Push address to be connected to a Pull socket of the next server
        :param worker_pull_address: Pull address for the worker connection
        :param worker_push_address: Push address for the worker connection
        :param db_address: Persistency address to be bind
        :param log_address: Address of the log service to be connected to
        :param perf_address: Address of the performance counter collector
        :param ping_address: Address of the ping collector
        :param cache: Key-value database to be used internally
        :param palm: True if the message that is sent through the server is a PALM message
        :param debug_level: Debug level for logging
        """
        self.name = name
        self.cache = cache

        # Addresses:
        self.pull_address = pull_address
        self.push_address = next_address
        self.worker_pull_address = worker_pull_address
        self.worker_push_address = worker_push_address

        # Configure the log handler
        handler = PushHandler(log_address)
        self.logger = logging.getLogger(name)
        self.logger.addHandler(handler)
        self.logger.setLevel(debug_level)

        # Handle that controls if the messages have to be processed
        self.palm = palm

        # Configure the performance counter
        self.perfcounter = PerformanceCounter(listen_address=perf_address)

        # Configure the pinger.
        self.pinger = Pinger(listen_address=ping_address, every=30.0)

        # Configure the broker and the connectors
        self.broker = Router(logger=self.logger)
        self.pull_service = PullService(
            'Pull',
            pull_address,
            broker_address=self.broker.inbound_address,
            logger=self.logger,
            palm=palm,
            cache=cache)
        self.push_connection = PushConnection(
            'Push',
            next_address,
            broker_address=self.broker.outbound_address,
            logger=self.logger,
            palm=palm,
            cache=cache)
        self.worker_pull_service = WorkerPullService(
            'WorkerPull',
            worker_pull_address,
            broker_address=self.broker.inbound_address,
            logger=self.logger,
            palm=palm,
            cache=cache)
        self.worker_push_service = WorkerPushService(
            'WorkerPush',
            worker_push_address,
            broker_address=self.broker.outbound_address,
            logger=self.logger,
            palm=palm,
            cache=cache)

        self.broker.register_inbound('Pull', route='WorkerPush', log='to_broker')
        self.broker.register_inbound('WorkerPull', route='Push', log='from_broker')
        self.broker.register_outbound('WorkerPush', log='to_broker')
        self.broker.register_outbound('Push', log='to_sink')

        # Configure the cache server
        self.db_address = db_address
        self.cache_service = CacheService(self.name,
                                          db_address,
                                          self.logger,
                                          cache=self.cache)

        # This is the pinger thread that keeps the pinger alive.
        pinger_thread = Thread(target=self.pinger.start)
        pinger_thread.daemon = True
        pinger_thread.start()

    def start(self):
        threads = [
            Thread(target=self.broker.start),
            Thread(target=self.push_connection.start),
            Thread(target=self.pull_service.start),
            Thread(target=self.worker_push_service.start),
            Thread(target=self.worker_pull_service.start),
            Thread(target=self.cache_service.start)
        ]
        for t in threads:
            t.start()