import unittest
from types import SimpleNamespace

from mkdocs_translator.translator import DocumentTranslator


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(response):
    completions = FakeCompletions(response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class ApiClientTests(unittest.TestCase):
    def test_blocking_response_content_and_usage(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="English"))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )
        client, completions = fake_client(response)
        translator = DocumentTranslator(
            "en",
            response_mode="blocking",
            client=client,
            system_prompt="system prompt",
        )
        translated, metadata = translator.translate_text("中文")
        self.assertEqual("English", translated)
        self.assertEqual(5, metadata["usage"]["total_tokens"])
        self.assertEqual("system prompt", completions.calls[0]["messages"][0]["content"])
        self.assertEqual("English", completions.calls[0]["messages"][1]["content"].split("<target_language>")[1].split("</target_language>")[0])

    def test_streaming_response_and_unknown_usage(self):
        chunks = [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="日"))], usage=None),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="本語"))], usage=None),
        ]
        client, completions = fake_client(chunks)
        seen_chunks = []
        translator = DocumentTranslator(
            "ja",
            response_mode="streaming",
            client=client,
            system_prompt="system prompt",
        )
        translated, metadata = translator.translate_text("中文", progress_callback=seen_chunks.append)
        self.assertEqual("日本語", translated)
        self.assertIsNone(metadata["usage"])
        self.assertEqual([1, 2], seen_chunks)
        self.assertTrue(completions.calls[0]["stream"])


if __name__ == "__main__":
    unittest.main()
