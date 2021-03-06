import concurrent.futures
import time
from concurrent.futures import ThreadPoolExecutor

import zmq

from pylm.clients import Client
from pylm.parts.core import zmq_context
from pylm.parts.messages_pb2 import PalmMessage


def fake_server(messages=1):
    db_socket = zmq_context.socket(zmq.REP)
    db_socket.bind('inproc://db')

    pull_socket = zmq_context.socket(zmq.PULL)
    pull_socket.bind('inproc://pull')

    pub_socket = zmq_context.socket(zmq.PUB)
    pub_socket.bind('inproc://pub')

    # PUB-SUB takes a while
    time.sleep(1.0)
    
    for i in range(messages):
        message_data = pull_socket.recv()
        print(i)
        message = PalmMessage()
        message.ParseFromString(message_data)

        topic = message.client
        pub_socket.send_multipart([topic.encode('utf-8'), message_data])


def test_subscribed_client_single():
    got = []

    client = Client(
        server_name='someserver',
        db_address='inproc://db',
        push_address='inproc://pull',
        sub_address='inproc://pub',
        this_config=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(fake_server, messages=2),
            executor.submit(client.job, 'f', [b'1', b'2'], messages=2)
        ]

        for future in concurrent.futures.as_completed(results):
            try:
                result = future.result()
                if result:
                    for r in result:
                        got.append(r)

            except Exception as exc:
                print(exc)

    assert len(got) == 2


def test_subscribed_client_multiple():
    got = []

    client = Client(
        server_name='someserver',
        db_address='inproc://db',
        sub_address='inproc://pub',
        push_address='inproc://pull',
        this_config=True)

    client1 = Client(
        server_name='someserver',
        db_address='inproc://db',
        sub_address='inproc://pub',
        push_address='inproc://pull',
        this_config=True)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(fake_server, messages=4),
            executor.submit(client.job, 'f', [b'1', b'2'], messages=2),
            executor.submit(client1.job, 'f', [b'a', b'b'], messages=2)
        ]

        for future in concurrent.futures.as_completed(results):
            try:
                result = future.result()
                if result:
                    for r in result:
                        got.append(r)

            except Exception as exc:
                print(exc)

    assert len(got) == 4
    
if __name__ == '__main__':
    test_subscribed_client_single()
    test_subscribed_client_multiple()
