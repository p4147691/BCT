import base64
import json
import struct
import unittest

from bct.core.bridge_pr3k_pipe_frame import (
    MAX_PIPE_FRAME_BYTES,
    PIPE_FRAME_VERSION,
    PipeFrameError,
    decode_peer_frame,
    encode_peer_frame,
)


def wire(value: bytes) -> bytes:
    return struct.pack("<I", len(value)) + value


class PipeFrameTests(unittest.TestCase):
    def test_round_trip_preserves_exact_canonical_peer_bytes(self):
        peer = b'{"version":1,"proof":"not-a-secret"}'
        decoded = decode_peer_frame(encode_peer_frame(peer))
        self.assertEqual("peer_frame", decoded.operation)
        self.assertEqual(peer, decoded.peer_frame)

    def test_encoder_rejects_empty_or_non_bytes_peer_frame(self):
        for value in (b"", "peer", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "PIPE_FRAME_ARGUMENT_DENIED"):
                    encode_peer_frame(value)

    def test_decoder_rejects_short_oversize_truncated_and_trailing_frames(self):
        valid = encode_peer_frame(b"peer")
        cases = (
            b"",
            b"\x00\x00\x00",
            struct.pack("<I", MAX_PIPE_FRAME_BYTES + 1),
            struct.pack("<I", 5) + b"{}",
            valid + b"x",
        )
        for value in cases:
            with self.subTest(value=value[:8]):
                with self.assertRaisesRegex(PipeFrameError, "PIPE_FRAME_DENIED"):
                    decode_peer_frame(value)

    def test_decoder_rejects_unknown_fields_operations_duplicate_fields_and_nonfinite_values(self):
        encoded = base64.b64encode(b"peer").decode("ascii")
        cases = (
            json.dumps({"version": PIPE_FRAME_VERSION, "operation": "peer_frame",
                        "peer_frame_b64": encoded, "extra": True}).encode(),
            json.dumps({"version": PIPE_FRAME_VERSION, "operation": "other",
                        "peer_frame_b64": encoded}).encode(),
            ('{"version":1,"version":1,"operation":"peer_frame",'
             '"peer_frame_b64":"cGVlcg=="}').encode(),
            ('{"version":NaN,"operation":"peer_frame",'
             '"peer_frame_b64":"cGVlcg=="}').encode(),
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaisesRegex(PipeFrameError, "PIPE_FRAME_DENIED"):
                    decode_peer_frame(wire(value))

    def test_decoder_rejects_noncanonical_or_invalid_base64(self):
        for encoded in ("cGVlcg", "not-base64!", ""):
            body = json.dumps({"version": PIPE_FRAME_VERSION, "operation": "peer_frame",
                               "peer_frame_b64": encoded}).encode()
            with self.subTest(encoded=encoded):
                with self.assertRaisesRegex(PipeFrameError, "PIPE_FRAME_DENIED"):
                    decode_peer_frame(wire(body))


if __name__ == "__main__":
    unittest.main()
