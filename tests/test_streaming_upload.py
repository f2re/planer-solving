import asyncio

from web.backend.analysis_api import stream_upload


class FakeUpload:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        self.closed = False

    async def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def test_stream_upload_writes_in_chunks_without_fixed_limit(tmp_path):
    payload = b"planner" * 400_000
    upload = FakeUpload(payload)
    target = tmp_path / "large.xlsx"

    written = asyncio.run(stream_upload(upload, target))

    assert written == len(payload)
    assert target.read_bytes() == payload
    assert upload.closed is True
