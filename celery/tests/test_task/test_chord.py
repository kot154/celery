from __future__ import absolute_import
from __future__ import with_statement

from mock import patch
from contextlib import contextmanager

from celery import current_app
from celery.task import chords
from celery.task import task, TaskSet
from celery.tests.utils import AppCase, Mock

passthru = lambda x: x


@current_app.task
def add(x, y):
    return x + y


@contextmanager
def patch_unlock_retry():
    unlock = current_app.tasks["celery.chord_unlock"]
    retry = Mock()
    prev, unlock.retry = unlock.retry, retry
    yield unlock, retry
    unlock.retry = prev


class test_unlock_chord_task(AppCase):

    @patch("celery.result.TaskSetResult")
    def test_unlock_ready(self, TaskSetResult):

        @task
        def callback(*args, **kwargs):
            pass

        callback.delay = Mock()
        with patch_unlock_retry() as (unlock, retry):
            from celery.task import sets
            result = Mock(attrs=dict(ready=lambda: True,
                                    join=lambda **kw: [2, 4, 8, 6]))
            TaskSetResult.restore = lambda setid: result
            subtask, sets.subtask = sets.subtask, passthru
            try:
                unlock("setid", callback)
            finally:
                sets.subtask = subtask
            result.delete.assert_called_with()
            callback.delay.assert_called_with([2, 4, 8, 6])
            # did not retry
            self.assertFalse(retry.call_count)

    @patch("celery.result.TaskSetResult")
    def test_when_not_ready(self, TaskSetResult):
        with patch_unlock_retry() as (unlock, retry):
            callback = Mock()
            result = Mock(attrs=dict(ready=lambda: False))
            TaskSetResult.restore = lambda setid: result
            unlock("setid", callback, interval=10, max_retries=30)
            self.assertFalse(callback.delay.call_count)
            # did retry
            unlock.retry.assert_called_with(countdown=10, max_retries=30)

    def test_is_in_registry(self):
        self.assertIn("celery.chord_unlock", current_app.tasks)


class test_chord(AppCase):

    def test_apply(self):

        class chord(chords.chord):
            Chord = Mock()

        x = chord(add.subtask((i, i)) for i in xrange(10))
        body = add.subtask((2, ))
        result = x(body)
        self.assertEqual(result.task_id, body.options["task_id"])
        self.assertTrue(chord.Chord.apply_async.call_count)


class test_Chord_task(AppCase):

    def test_run(self):

        class Chord(chords.Chord):
            backend = Mock()

        body = dict()
        Chord()(TaskSet(add.subtask((i, i)) for i in xrange(5)), body)
        Chord()([add.subtask((i, i)) for i in xrange(5)], body)
        self.assertEqual(Chord.backend.on_chord_apply.call_count, 2)