from __future__ import absolute_import
import unittest
import collections
import datetime
import json
from eliot_profiler import _Profiler, _CallGraphRoot, _MessageInfo


def drain_queue(q):
    output = []
    while True:
        try:
            output.append(q.popleft())
        except IndexError:
            return output


MockFrame = collections.namedtuple('MockFrame',
                                   'f_code f_globals f_lineno f_back')
MockCode = collections.namedtuple('MockCode', 'co_filename co_name')


class MockedOutProfiler(_Profiler):
    def _current_frames(self):
        return {
            12345: mock_frame('__main__:main:1', 'business.app:__init__:5',
                              'business.backend:doStuff:10')
        }


def mock_frame(*frames):
    result = None
    for frame in frames:
        module, method, line = frame.split(':')
        filename = module.replace('.', '/') + '.py'
        result = MockFrame(
            MockCode(filename, method), {'__name__': module}, int(line),
            result)
    return result


class EliotProfilerTest(unittest.TestCase):
    def test_max_actions_per_run(self):
        instance = _Profiler(max_actions_per_run=2)
        instance.handle_message({'task_uuid': '1', 'action_status': 'started'})
        instance.handle_message({
            'task_uuid': '1',
            'action_status': 'succeeded'
        })
        instance.handle_message({'task_uuid': '2', 'action_status': 'started'})
        instance.handle_message({
            'task_uuid': '2a',
            'action_status': 'started'
        })
        instance.handle_message({'task_uuid': '2a', 'action_status': 'failed'})
        instance.handle_message({'task_uuid': '2', 'action_status': 'failed'})
        instance.handle_message({'task_uuid': '3', 'action_status': 'started'})
        instance.handle_message({
            'task_uuid': '3',
            'action_status': 'succeeded'
        })
        messages = drain_queue(instance.message_queue)
        self.assertEqual(6, len(messages))
        self.assertEqual('1', messages[0].next_task_uuid)
        self.assertEqual(None, messages[1].next_task_uuid)
        self.assertEqual('2', messages[2].next_task_uuid)
        self.assertEqual('2a', messages[3].next_task_uuid)
        self.assertEqual('2', messages[4].next_task_uuid)
        self.assertEqual(None, messages[5].next_task_uuid)

    def test_dont_handle_message_outside_action(self):
        instance = _Profiler(store_all_logs=True)
        instance.handle_message({'task_uuid': '99', 'msg': 'outside'})
        instance.handle_message({'task_uuid': '1', 'action_status': 'started'})
        instance.handle_message({'task_uuid': '1', 'msg': 'inside'})
        instance.handle_message({'task_uuid': '1', 'action_status': 'failed'})
        messages = drain_queue(instance.message_queue)
        self.assertEqual(3, len(messages))
        self.assertEqual('started', messages[0].message['action_status'])
        self.assertEqual('inside', messages[1].message['msg'])
        self.assertEqual('failed', messages[2].message['action_status'])

    def test_dont_store_all_logs(self):
        instance = _Profiler(store_all_logs=False)
        instance.handle_message({'task_uuid': '1', 'action_status': 'started'})
        instance.handle_message({'task_uuid': '1', 'msg': 'inside'})
        instance.handle_message({'task_uuid': '1', 'action_status': 'failed'})
        messages = drain_queue(instance.message_queue)
        self.assertEqual(2, len(messages))
        self.assertEqual('started', messages[0].message['action_status'])
        self.assertEqual('failed', messages[1].message['action_status'])

    def test_ingest_message(self):
        instance = _Profiler()
        messages = []
        instance.add_destination(messages.append)

        msg1 = _MessageInfo(
            message={
                'action_status': 'started',
                'task_uuid': '1',
                'msg': 'Hi'
            },
            next_task_uuid='1')
        msg1.frame = mock_frame('__main__:main:1', 'business.app:__init__:5',
                                'eliot._action:startAction:100',
                                'eliot_profiler:emit:101')
        msg1.monotonic = 0.0
        msg1.clock = datetime.datetime(1988, 1, 1, 9, 0, 0)
        msg1.thread = 12345
        instance._ingest_message(msg1)

        msg2 = _MessageInfo(
            message={
                'action_status': 'success',
                'task_uuid': '1',
                'msg': 'World'
            },
            next_task_uuid=None)
        msg2.frame = mock_frame('__main__:main:1', 'business.app:__init__:5',
                                'eliot._action:endAction:100',
                                'eliot_profiler:emit:101')
        msg2.monotonic = 1.0
        msg2.clock = datetime.datetime(
            1987, 1, 1, 9, 0,
            0)  # Clock skew should be ignored, after first message
        msg2.thread = 12345
        instance._ingest_message(msg2)

        self.assertEqual([{
            "task_uuid": "1",
            "children": [{
                "start_time": "1988-01-01T09:00:00",
                "instruction": "__main__.py:main",
                "self_time": 0.0,
                "end_time": "1988-01-01T09:00:01",
                "time": 0.0,
                "children": [{
                    "start_time": "1988-01-01T09:00:00",
                    "instruction": "business/app.py:__init__",
                    "self_time": 0.0,
                    "end_time": "1988-01-01T09:00:01",
                    "time": 0.0,
                    "children": [{
                        "message": {
                            "msg": "Hi",
                            "task_uuid": "1",
                            "action_status": "started"
                        },
                        "message_time": "1988-01-01T09:00:00"
                    }, {
                        "message": {
                            "msg": "World",
                            "task_uuid": "1",
                            "action_status": "success"
                        },
                        "message_time": "1988-01-01T09:00:01"
                    }]
                }]
            }],
            "thread": 12345
        }], messages)

    def test_profiling_cycle(self):
        # import pudb
        # pu.db
        instance = MockedOutProfiler()
        messages = []
        instance.add_destination(messages.append)

        msg1 = _MessageInfo(
            message={
                'action_status': 'started',
                'task_uuid': '1',
                'msg': 'Hi'
            },
            next_task_uuid='1')
        msg1.frame = mock_frame('__main__:main:1', 'business.app:__init__:5',
                                'eliot._action:startAction:100',
                                'eliot_profiler:emit:101')
        msg1.monotonic = 0.0
        msg1.clock = datetime.datetime(1988, 1, 1, 9, 0, 0)
        msg1.thread = 12345
        instance.message_queue.append(msg1)

        instance._profile_once(0.1, 0.5)

        msg2 = _MessageInfo(
            message={
                'action_status': 'success',
                'task_uuid': '1',
                'msg': 'World'
            },
            next_task_uuid=None)
        msg2.frame = mock_frame('__main__:main:1', 'business.app:__init__:5',
                                'eliot._action:endAction:100',
                                'eliot_profiler:emit:101')
        msg2.monotonic = 1.0
        msg2.clock = datetime.datetime(
            1987, 1, 1, 9, 0,
            0)  # Clock skew should be ignored, after first message
        msg2.thread = 12345
        instance.message_queue.append(msg2)

        instance._profile_once(0.1, 1.5)

        self.assertEqual([{
            "task_uuid": "1",
            "children": [{
                "start_time": "1988-01-01T09:00:00",
                "instruction": "__main__.py:main",
                "self_time": 0.0,
                "end_time": "1988-01-01T09:00:01",
                "time": 0.1,
                "children": [{
                    "start_time": "1988-01-01T09:00:00",
                    "instruction": "business/app.py:__init__",
                    "self_time": 0.0,
                    "end_time": "1988-01-01T09:00:01",
                    "time": 0.1,
                    "children": [{
                        "message": {
                            "msg": "Hi",
                            "task_uuid": "1",
                            "action_status": "started"
                        },
                        "message_time": "1988-01-01T09:00:00"
                    }, {
                        "self_time": 0.1,
                        "start_time": "1988-01-01T09:00:00.500000",
                        "instruction": "business/backend.py:doStuff",
                        "end_time": "1988-01-01T09:00:00.500000",
                        "time": 0.1
                    }, {
                        "message": {
                            "msg": "World",
                            "task_uuid": "1",
                            "action_status": "success"
                        },
                        "message_time": "1988-01-01T09:00:01"
                    }]
                }]
            }],
            "thread": 12345
        }], messages)


class CallGraphTest(unittest.TestCase):
    def test_call_graph(self):
        instance = _CallGraphRoot('thread1', '12345',
                                  datetime.datetime(2016, 1, 21, 9, 0, 0))
        instance.ingest(['main', 'doIt', '_innerDoIt'], 1.0, 1.0)
        instance.ingest(['main', 'doIt', '_innerDoSomethingElse'], 1.0, 2.0)
        instance.ingest(['main', 'doIt', '_innerDoIt'], 1.0, 3.0)
        instance.ingest(['main', 'doIt'], 1.0, 4.0)
        instance.ingest(['main', 'doIt'], 0.0, 4.5, {'event': 'something'})
        instance.ingest(['main', 'doIt', '_innerDoIt'], 1.0, 5.0)
        jsonized = instance.jsonize()
        self.assertEqual({
            "task_uuid": "12345",
            "children": [{
                "start_time": "2016-01-21T09:00:01",
                "instruction": "main",
                "self_time": 0,
                "end_time": "2016-01-21T09:00:05",
                "time": 5.0,
                "children": [{
                    "start_time": "2016-01-21T09:00:01",
                    "instruction": "doIt",
                    "self_time": 1.0,
                    "end_time": "2016-01-21T09:00:05",
                    "time": 5.0,
                    "children": [{
                        "self_time": 2.0,
                        "start_time": "2016-01-21T09:00:01",
                        "instruction": "_innerDoIt",
                        "end_time": "2016-01-21T09:00:03",
                        "time": 2.0
                    }, {
                        "self_time": 1.0,
                        "start_time": "2016-01-21T09:00:02",
                        "instruction": "_innerDoSomethingElse",
                        "end_time": "2016-01-21T09:00:02",
                        "time": 1.0
                    }, {
                        "message": {
                            "event": "something"
                        },
                        "message_time": "2016-01-21T09:00:04.500000"
                    }, {
                        "self_time": 1.0,
                        "start_time": "2016-01-21T09:00:05",
                        "instruction": "_innerDoIt",
                        "end_time": "2016-01-21T09:00:05",
                        "time": 1.0
                    }]
                }]
            }],
            "thread": "thread1"
        }, jsonized)


if __name__ == '__main__':
    unittest.main()