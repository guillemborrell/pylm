from pylm_ng.components.messages_pb2 import PalmMessage, BrokerMessage
from uuid import uuid4
import zmq
import sys


zmq_context = zmq.Context.instance()


class Broker(object):
    """
    Broker for the internal event-loop. It is a ROUTER socket that blocks
    waiting for the components to send something. This is more a bus than
    a broker.
    """
    def __init__(self,
                 inbound_address="inproc://inbound",
                 outbound_address="inproc://outbound",
                 logger=None,
                 cache=None,
                 messages=sys.maxsize,
                 max_buffer_size=sys.maxsize):
        """
        Initiate a broker instance
        :param inbound_address: Valid ZMQ bind address for inbound components
        :param outbound_address: Valid ZMQ bind address for outbound components
        :param logger: Logger instance
        :param cache: Global cache of the server
        :param messages: Maximum number of inbound messages. Defaults to infinity.
        :param messages: Number of messages allowed before the router starts buffering.
        :return:
        """
        # Socket that will listen to the inbound components
        self.inbound = zmq_context.socket(zmq.ROUTER)
        self.inbound.bind(inbound_address)
        self.inbound_address = inbound_address
        self.inbound_components = {}

        # Socket that listens to the outbound components
        self.outbound = zmq_context.socket(zmq.ROUTER)
        self.outbound.bind(outbound_address)
        self.outbound_address = outbound_address
        self.outbound_components = {}

        # Other utilities
        self.logger = logger
        self.messages = messages
        self.buffer = {}
        if max_buffer_size < 100:  # Enforce a limit in buffer size.
            max_buffer_size = 100
        self.max_buffer_size = max_buffer_size

        # Poller for the event loop
        self.poller = zmq.Poller()
        self.poller.register(self.outbound, zmq.POLLIN)
        self.poller.register(self.inbound, zmq.POLLIN)

        # Cache for the server
        self.cache = cache

    def register_inbound(self, name, route=None, log=''):
        """
        Register component by name. Only inbound components have to be registered.
        :param name: Name of the component. Each component has a name, that
          uniquely identifies it to the broker
        :param route: Each message that the broker gets from the component
          may be routed to another component. This argument gives the name
          of the target component for the message.
        :param log: Log message for each inbound connection.
        :return:
        """
        # If route is not specified, the component wants a message back.
        if not route:
            route = name

        self.inbound_components[name.encode('utf-8')] = {
            'route': route.encode('utf-8'),
            'log': log
        }

    def register_outbound(self, name, log=''):
        self.outbound_components[name.encode('utf-8')] = {
            'log': log
        }

    def start(self):
        # Buffer to store the message when the outbound component is not available
        # for routing. Maybe replace by a heap queue.
        buffering = False

        # List of available outbound components
        available_outbound = []

        self.logger.info('Launch broker')
        self.logger.info('Inbound socket: {}'.format(self.inbound))
        self.logger.info('Outbound socket: {}'.format(self.outbound))

        for i in range(self.messages):
            # Polls the outbound socket for inbound and outbound connections
            event = dict(self.poller.poll())
            self.logger.debug('Event {}'.format(event))

            if self.outbound in event:
                self.logger.debug('Handling outbound event')
                # TODO: Handle this message_data from outbound component, just like inbound
                component, empty, message_data = self.outbound.recv_multipart()

                # If messages for the outbound are buffered.
                if component in self.buffer:
                    # Look in the buffer
                    message_data = self.buffer[component].pop()
                    if len(self.buffer[component]) == 0:
                        del self.buffer[component]

                    # If the buffer is empty enough and the broker was buffering
                    if sum([len(v) for v in self.buffer.values()])*10 < self.max_buffer_size \
                            and buffering:
                        # Listen to inbound connections again.
                        self.logger.info('Broker accepting messages again.')
                        self.poller.register(self.inbound, zmq.POLLIN)
                        buffering = False

                    self.outbound.send_multipart([component, empty, message_data])

                # If they are no buffered messages, set outbound as available.
                else:
                    available_outbound.append(component)

            elif self.inbound in event:
                self.logger.debug('Handling inbound event')
                component, empty, message_data = self.inbound.recv_multipart()

                # Start internal routing
                route_to = self.inbound_components[component]['route']

                # If no routing needed
                if route_to == component:
                    self.logger.debug('Message back to {}'.format(route_to))
                    self.inbound.send_multipart([component, empty, message_data])

                # If an outbound is listening
                elif route_to in available_outbound:
                    self.logger.debug('Broker routing to {}'.format(route_to))
                    available_outbound.remove(route_to)
                    self.outbound.send_multipart([route_to, empty, message_data])

                    # Unblock the component
                    self.logger.debug('Unblocking inbound')
                    self.inbound.send_multipart([component, empty, b'1'])

                # If the corresponding outbound not is listening, buffer the message
                else:
                    self.logger.info('Sent to buffer.')
                    if route_to in self.buffer:
                        self.buffer[route_to].append(message_data)
                    else:
                        self.buffer[route_to] = [message_data]

                    if sum([len(v) for v in self.buffer.values()]) >= self.max_buffer_size:
                        self.logger.info('Broker buffering messages')
                        self.poller.unregister(self.inbound)
                        buffering = True

                    self.logger.debug('Unblocking inbound')
                    self.inbound.send_multipart([component, empty, b'1'])

            else:
                self.logger.critical('Socket not known.')

            self.logger.debug('Finished event cycle.')


class ComponentInbound(object):
    """
    Generic component that connects a REQ socket to the broker, and a
    socket to an inbound external service.
    """
    def __init__(self,
                 name,
                 listen_address,
                 socket_type,
                 reply=True,
                 broker_address="inproc://broker",
                 bind=False,
                 palm=False,
                 logger=None,
                 cache=None,
                 messages=sys.maxsize):
        """
        :param name: Name of the component
        :param listen_address: ZMQ socket address to listen to
        :param socket_type: ZMQ inbound socket type
        :param reply: True if the listening socket blocks waiting a reply
        :param broker_address: ZMQ socket address for the broker
        :param bind: True if socket has to bind, instead of connect.
        :param palm: True if the message is waiting is a PALM message. False if it is
          just a binary string
        :param logger: Logger instance
        :param cache: Cache for shared data in the server
        :param messages: Maximum number of inbound messages. Defaults to infinity.
        :return:
        """
        self.name = name.encode('utf-8')
        self.listen_to = zmq_context.socket(socket_type)
        if bind:
            self.listen_to.bind(listen_address)
        else:
            self.listen_to.connect(listen_address)
        self.listen_address = listen_address
        self.broker = zmq_context.socket(zmq.REQ)
        self.broker.identity = self.name
        self.broker.connect(broker_address)
        self.palm = palm
        self.logger = logger
        self.cache = cache
        self.messages = messages
        self.reply = reply

    def _translate_to_broker(self, message_data):
        """
        Translate the message that the component has got to be digestible by the broker
        :param message_data:
        :return:
        """
        broker_message_key = str(uuid4())
        if self.palm:
            palm_message = PalmMessage()
            palm_message.ParseFromString(message_data)
            payload = palm_message.payload

            # I store the message to get it later when the message is outbound. See that
            # if I am just sending binary messages, I do not need to assign any envelope.
            self.cache.set(broker_message_key, message_data)
        else:
            payload = message_data

        broker_message = BrokerMessage()
        broker_message.key = broker_message_key
        broker_message.payload = payload

        return broker_message.SerializeToString()

    def scatter(self, message_data):
        """
        To be overriden. Picks a message and returns a generator that multiplies the messages
        to the broker.
        :param message_data:
        :return:
        """
        yield message_data

    def handle_feedback(self, message_data):
        """
        To be overriden. Handles the feedback from the broker
        :param message_data:
        :return:
        """
        pass

    def reply_feedback(self):
        """
        To be overriden. Returns the feedback if the component has to reply.
        :return:
        """
        return b'0'

    def start(self):
        self.logger.info('Launch component {}'.format(self.name))
        for i in range(self.messages):
            self.logger.debug('Component {} blocked waiting messages'.format(self.name))
            message_data = self.listen_to.recv()
            self.logger.debug('Got inbound message')

            for scattered in self.scatter(message_data):
                scattered = self._translate_to_broker(scattered)
                self.broker.send(scattered)
                self.logger.debug('Component {} blocked waiting for broker'.format(self.name))
                self.handle_feedback(self.broker.recv())

            if self.reply:
                self.listen_to.send(self.reply_feedback())


class ComponentOutbound(object):
    """
    Generic component that connects a REQ socket to the broker, and a
    socket to an inbound external service.
    """
    def __init__(self,
                 name,
                 listen_address,
                 socket_type,
                 reply=True,
                 broker_address="inproc://broker",
                 bind=False,
                 palm=False,
                 logger=None,
                 cache=None,
                 messages=sys.maxsize):
        """
        :param name: Name of the component
        :param listen_address: ZMQ socket address to listen to
        :param socket_type: ZMQ inbound socket type
        :param reply: True if the listening socket blocks waiting a reply
        :param broker_address: ZMQ socket address for the broker,
        :param bind: True if the socket has to bind instead of connect.
        :param palm: The component is sending back a Palm message
        :param logger: Logger instance
        :param cache: Access to the cache of the server
        :param messages: Maximum number of inbound messages. Defaults to infinity.
        :return:
        """
        self.name = name.encode('utf-8')
        self.listen_to = zmq_context.socket(socket_type)
        if bind:
            self.listen_to.bind(listen_address)
        else:
            self.listen_to.connect(listen_address)
        self.listen_address = listen_address
        self.broker = zmq_context.socket(zmq.REQ)
        self.broker.identity = self.name
        self.broker.connect(broker_address)
        self.logger = logger
        self.palm = palm
        self.cache = cache
        self.messages = messages
        self.reply = reply

    def _translate_from_broker(self, message_data):
        """
        Translate the message that the component has got to be digestible by the broker
        :param message_data:
        :return:
        """
        broker_message = BrokerMessage()
        broker_message.ParseFromString(message_data)

        if self.palm:
            # Get the envelope of the message from the cache.
            message_data = self.cache.get(broker_message.key)
            palm_message = PalmMessage()
            palm_message.ParseFromString(message_data)
            palm_message.payload = broker_message.payload
            message_data = palm_message.SerializeToString()

        else:
            message_data = broker_message.payload

        return message_data

    def scatter(self, message_data):
        """
        To be overriden. Picks a message and returns a generator that multiplies the messages
        to the broker.
        :param message_data:
        :return:
        """
        yield message_data

    def handle_feedback(self, message_data):
        """
        To be overriden. Handles the feedback from the broker
        :param message_data:
        :return:
        """
        pass

    def reply_feedback(self):
        """
        To be overriden. Returns the feedback if the component has to reply.
        :return:
        """
        return b'0'

    def start(self):
        self.logger.info('Launch component {}'.format(self.name))
        self.broker.send(b'1')

        for i in range(self.messages):
            self.logger.debug('Component {} blocked waiting for broker'.format(self.name))
            message_data = self.broker.recv()
            self.logger.debug('Got message from broker')
            for scattered in self.scatter(message_data):
                self.listen_to.send(scattered)

                if self.reply:
                    self.handle_feedback(self.listen_to.recv())

            self.broker.send(self.reply_feedback())


class ComponentBypassInbound(object):
    """
    Generic inbound component that does not connect to the broker.
    """
    def __init__(self,
                 name,
                 listen_address,
                 socket_type,
                 reply=True,
                 bind=False,
                 logger=None,
                 cache=None):
        """
        :param name: Name of the component
        :param listen_address: ZMQ socket address to listen to
        :param socket_type: ZMQ inbound socket type
        :param reply: True if the listening socket blocks waiting a reply
        :param bind: True if the component has to bind instead of connect.
        :param logger: Logger instance
        :param cache: Access to the server cache
        :return:
        """
        self.name = name.encode('utf-8')
        self.listen_to = zmq_context.socket(socket_type)
        if bind:
            self.listen_to.bind(listen_address)
        else:
            self.listen_to.connect(listen_address)
        self.listen_address = listen_address
        self.logger = logger
        self.reply = reply
        self.cache = cache

    def recv(self, reply_data=None):
        """
        Receives, yields and returns answer_data if needed
        :param reply_data: Message to send if connection needs an answer.
        :return:
        """
        message_data = self.listen_to.recv()

        if self.reply:
            self.listen_to.send(reply_data)

        return message_data


class ComponentBypassOutbound(object):
    """
    Generic inbound component that does not connect to the broker.
    """
    def __init__(self,
                 name,
                 listen_address,
                 socket_type,
                 reply=True,
                 bind=False,
                 logger=None,
                 cache=None):
        """
        :param name: Name of the component
        :param listen_address: ZMQ socket address to listen to
        :param socket_type: ZMQ inbound socket type
        :param reply: True if the listening socket blocks waiting a reply
        :param bind: True if the socket has to bind instead of connect
        :param logger: Logger instance
        :param cache: Access to the cache of the server
        :return:
        """
        self.name = name.encode('utf-8')
        self.listen_to = zmq_context.socket(socket_type)
        if bind:
            self.listen_to.bind(listen_address)
        else:
            self.listen_to.connect(listen_address)
        self.listen_address = listen_address
        self.logger = logger
        self.reply = reply
        self.cache = cache

    def send(self, message_data):
        self.listen_to.send(message_data)

        if self.reply:
            message_data = self.listen_to.recv()
            return message_data

