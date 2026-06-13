"""Stratum target assignments must remain stable across vardiff changes."""

import asyncio
import json

from pool.stratum.session import StratumSession


class _Writer:
    def __init__(self):
        self.messages = []

    def get_extra_info(self, _name):
        return ("127.0.0.1", 12345)

    def write(self, data):
        self.messages.append(json.loads(data))

    async def drain(self):
        pass


def test_notify_assigns_unique_job_ids_and_preserves_difficulty():
    async def run():
        writer = _Writer()
        session = StratumSession(
            None,
            writer,
            on_submit=None,
            on_authorize=None,
            get_job_notify=lambda _difficulty: None,
            get_difficulty=lambda: 0.05,
        )

        session._session_difficulty = 0.05
        await session.send_notify(["btx-100-abcd"])
        first_id = writer.messages[-1]["params"][0]

        session._session_difficulty = 0.2
        await session.send_notify(["btx-100-abcd"])
        second_id = writer.messages[-1]["params"][0]

        assert first_id != second_id
        assert session._job_assignments[first_id] == ("btx-100-abcd", 0.05)
        assert session._job_assignments[second_id] == ("btx-100-abcd", 0.2)

    asyncio.run(run())
