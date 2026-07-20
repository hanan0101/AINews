import unittest
from unittest.mock import patch

from backend.pipeline.modeling import model_client


class ModelClientRewriteConfigTests(unittest.TestCase):
    def test_gemini_rewrite_uses_explicit_output_limit(self):
        with patch.object(model_client, "MODEL_PROVIDER", "gemini"), patch.object(
            model_client.gemini_client, "generate_json", return_value={"rewritten": []}
        ) as generate:
            result = model_client.generate_json_for_role("rewrite", "prompt", {"items": []})

        self.assertEqual(result, {"rewritten": []})
        generate.assert_called_once_with(
            "prompt",
            {"items": []},
            model=model_client.model_for_role("rewrite"),
            max_output_tokens=model_client.gemini_client.GEMINI_REWRITE_MAX_OUTPUT_TOKENS,
        )


if __name__ == "__main__":
    unittest.main()
