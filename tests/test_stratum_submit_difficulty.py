"""Queued shares must retain the difficulty active when they arrived."""

import asyncio

from pool.stratum.session import StratumSession


class _Writer:
    def get_extra_info(self, _name):
        return ("127.0.0.1", 12345)

    def write(self, _data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


def test_submit_snapshots_difficulty_before_async_validation():
    async def run():
        seen_difficulties = []

        async def on_submit(**kwargs):
            seen_difficulties.append(kwargs["difficulty"])
            return {"accepted": False, "error": "test", "error_code": 23}

        session = StratumSession(
            asyncio.StreamReader(),
            _Writer(),
            on_submit=on_submit,
            on_authorize=lambda *_args: True,
            get_job_notify=lambda _difficulty: None,
            get_difficulty=lambda: 0.001,
        )
        session._authorized = True
        session._address = "btx1test"
        session._worker_name = "worker"
        session._canonical_name = "btx1test.worker"
        session._session_difficulty = 0.001

        await session._dispatch({
            "id": 7,
            "method": "mining.submit",
            "params": ["worker", "job", "00000000", "00000001", "00000002"],
        })
        session._session_difficulty = 0.5
        await asyncio.gather(*session._submit_tasks)

        assert seen_difficulties == [0.001]

    asyncio.run(run())
