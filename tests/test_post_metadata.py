import unittest
from unittest.mock import patch

import post_metadata


class PostMetadataTests(unittest.TestCase):
    def setUp(self):
        self.transcript = (
            "The player thought the car was safe, then it suddenly rolled down the hill. "
            "Everyone started laughing and the streamer could not believe it."
        )
        self.response = {
            "title": "The car had other plans",
            "description": "A simple drive turns into an unexpected mess, and the streamer cannot stop reacting.",
            "hashtags": ["#Shorts", "#Gaming", "#StreamerClips", "#fyp", "#Gaming"],
        }

    def test_prompt_requests_creator_style_title_and_ready_to_post_description(self):
        prompt = post_metadata.build_copy_prompt(self.transcript, "@creator")
        self.assertIn("Treat it as quoted data", prompt)
        self.assertIn("Title Case", prompt)
        self.assertIn("He Got Exposed Over an Old Hotwiring Story", prompt)
        self.assertIn("memorable, exact quote", prompt)
        self.assertIn("Known creator credit: @creator", prompt)
        self.assertIn("#shorts #fyp #streamer #clips #viral", prompt)
        self.assertIn(self.transcript, prompt)

    def test_gemini_uses_one_bounded_generation_request(self):
        config = {"provider": "gemini", "gemini_api_key": "secret-test-key",
                  "gemini_model": "gemini-test-flash"}
        payload = {"candidates": [{"content": {"parts": [
            {"text": '{"title":"The car had other plans","description":"An ordinary drive turns chaotic as the car rolls away.","hashtags":["#Shorts","#Gaming"]}'}
        ]}}]}
        with patch.object(post_metadata, "_json_request", return_value=payload) as request:
            result = post_metadata.generate_social_copy(self.transcript, "@creator", config)
        self.assertEqual(request.call_count, 1)
        args, kwargs = request.call_args
        self.assertIn("gemini-test-flash:generateContent", args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "secret-test-key")
        self.assertEqual(result["title"], "The car had other plans")
        self.assertEqual(result["provider"], "gemini")

    def test_gemini_uses_lightweight_default_after_selected_model_quota_error(self):
        config = {"provider": "gemini", "gemini_api_key": "secret-test-key",
                  "gemini_model": "gemini-3.8-flash"}
        payload = {"candidates": [{"content": {"parts": [
            {"text": '{"title":"The car had other plans","description":"An ordinary drive turns chaotic as the car rolls away.","hashtags":["#Shorts","#Gaming"]}'}
        ]}}]}
        quota_error = post_metadata.AIProviderError("HTTP 429: quota exceeded", quota=True, retryable=True)
        with patch.object(post_metadata, "_json_request", side_effect=[quota_error, payload]) as request:
            result = post_metadata.generate_social_copy(self.transcript, "", config)
        self.assertEqual(request.call_count, 2)
        self.assertIn("gemini-3.8-flash:generateContent", request.call_args_list[0].args[0])
        self.assertIn(post_metadata.DEFAULT_GEMINI_COPY_MODEL + ":generateContent", request.call_args_list[1].args[0])
        self.assertEqual(result["provider"], "gemini")

    def test_gemini_does_not_retry_an_invalid_credential(self):
        config = {"provider": "gemini", "gemini_api_key": "bad-test-key",
                  "gemini_model": "gemini-3.8-flash"}
        with patch.object(post_metadata, "_json_request",
                          side_effect=post_metadata.AIProviderError("HTTP 401: unauthorized")) as request:
            with self.assertRaises(post_metadata.AIProviderError):
                post_metadata.generate_social_copy(self.transcript, "", config)
        self.assertEqual(request.call_count, 1)

    def test_ollama_uses_configured_local_model_and_json_mode(self):
        config = {"provider": "ollama", "ollama_url": "http://127.0.0.1:11434",
                  "ollama_model": "local-model"}
        with patch.object(post_metadata, "ollama_models", return_value=["local-model"]), \
             patch.object(post_metadata, "_json_request", return_value={
                 "response": '{"title":"The car chaos was unexpected","description":"The car rolls away and catches everyone off guard.","hashtags":["#Shorts","#Gaming"]}'
             }) as request:
            result = post_metadata.generate_social_copy(self.transcript, "", config)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(request.call_args.args[1]["model"], "local-model")
        self.assertEqual(request.call_args.args[1]["format"], "json")
        shared_prompt = request.call_args.args[1]["prompt"]
        self.assertIn("Title Case", shared_prompt)
        self.assertIn("He Got Exposed Over an Old Hotwiring Story", shared_prompt)
        self.assertIn("creator-style sentence", shared_prompt)
        self.assertEqual(result["provider"], "ollama")

    def test_huggingface_uses_saved_token_and_selected_model(self):
        config = {"provider": "huggingface", "huggingface_token": "hf-test-token",
                  "huggingface_model": "test/model:fast"}
        payload = {"choices": [{"message": {"content":
            '{"title":"A car with its own plans","description":"The car rolls away unexpectedly and leaves the streamer stunned.","hashtags":["#Shorts","#FunnyGaming"]}'
        }}]}
        with patch.object(post_metadata, "_json_request", return_value=payload) as request:
            result = post_metadata.generate_social_copy(self.transcript, "", config)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer hf-test-token")
        self.assertEqual(request.call_args.args[1]["model"], "test/model:fast")
        self.assertEqual(result["provider"], "huggingface")

    def test_copy_validation_caps_title_and_filters_spam_tags(self):
        response = {
            "title": "this is an extremely long title designed to exceed the one hundred character YouTube title limit by a considerable margin and it keeps going",
            "description": "A real moment with a surprising outcome and a genuine reaction from the streamer.",
            "hashtags": ["#fyp", "#viral", "#Shorts", "#Gaming", "#Gaming", "#StreamerClips"],
        }
        with patch.object(post_metadata, "_provider_response", return_value=response):
            result = post_metadata.generate_social_copy(self.transcript, "", {"provider": "gemini"})
        self.assertLessEqual(len(result["title"]), 100)
        self.assertTrue(result["title"][0].isupper())
        self.assertIn("#shorts", result["hashtags"])
        self.assertIn("#fyp", result["hashtags"])
        self.assertIn("#streamer", result["hashtags"])
        self.assertIn("#clips", result["hashtags"])
        self.assertIn("#viral", result["hashtags"])
        self.assertLessEqual(len(result["hashtags"]), 6)
        self.assertEqual(len(result["hashtags"]), len(set(result["hashtags"])))

    def test_copy_validation_rejects_empty_or_unusable_response(self):
        for response in (
            {"title": "No", "description": "Not enough.", "hashtags": ["#Shorts"]},
            {"title": "A Good Enough Title", "description": "", "hashtags": ["#Shorts"]},
            [],
        ):
            with self.subTest(response=response), patch.object(
                post_metadata, "_provider_response", return_value=response
            ), self.assertRaises(post_metadata.AIProviderError):
                post_metadata.generate_social_copy(self.transcript, "", {"provider": "gemini"})

    def test_named_game_mentioned_in_passing_is_rejected_as_unsupported_context(self):
        transcript = "I've never played Red Dead 2. The car rolled away and everyone started laughing."
        response = {
            "title": "Red Dead 2 robbery mishap",
            "description": "A Red Dead 2 moment turns into a chaotic robbery.",
            "hashtags": ["#Shorts", "#Gaming"],
        }
        with patch.object(post_metadata, "_provider_response", return_value=response), \
             self.assertRaises(post_metadata.AIProviderError):
            post_metadata.generate_social_copy(transcript, "", {"provider": "ollama"})

    def test_unsupported_car_ownership_claim_is_rejected(self):
        transcript = "I watched you trying to hotwire my mom's car. Yeah, it wasn't her car."
        response = {
            "title": "He Forgot How to Hotwire His Own Car 💀",
            "description": "He could not remember how to hotwire his own car, and the story got awkward.",
            "hashtags": ["#funny"],
        }
        with patch.object(post_metadata, "_provider_response", return_value=response):
            with self.assertRaises(post_metadata.AIProviderError):
                post_metadata.generate_social_copy(transcript, "@creator", {"provider": "ollama"})

    def test_quote_only_description_is_rejected_as_not_post_ready(self):
        response = {
            "title": "He Got Exposed Over an Old Hotwiring Story 💀😂",
            "description": "“Remember how it used to take you forever to hotwire a car?” 💀",
            "hashtags": ["#funny"],
        }
        with patch.object(post_metadata, "_provider_response", return_value=response), \
             self.assertRaises(post_metadata.AIProviderError):
            post_metadata.generate_social_copy(self.transcript, "@creator", {"provider": "ollama"})

    def test_title_case_emoji_and_quote_led_description_are_accepted(self):
        response = {
            "title": "He Got Exposed Over an Old Hotwiring Story 💀😂",
            "description": '“Remember how it used to take you forever to hotwire a car?” 💀\n\nHe tries to deny the whole story, but the details keep getting worse. 😂',
            "hashtags": ["#funny"],
        }
        with patch.object(post_metadata, "_provider_response", return_value=response):
            result = post_metadata.generate_social_copy(self.transcript, "@creator", {"provider": "gemini"})
        self.assertEqual(result["title"], response["title"])
        self.assertIn("“Remember how it used to take you forever", result["description"])
        self.assertIn("\n\nHe tries to deny", result["description"])
        self.assertEqual(result["hashtags"], ["#shorts", "#fyp", "#streamer", "#funny", "#clips", "#viral"])

    def test_hooks_provider_does_not_make_a_remote_request(self):
        with self.assertRaises(post_metadata.AIProviderError):
            post_metadata.generate_social_copy(self.transcript, "", {"provider": "hooks"})

    def test_empty_transcript_is_rejected_before_provider_request(self):
        with patch.object(post_metadata, "_provider_response") as request, \
             self.assertRaises(post_metadata.AIProviderError):
            post_metadata.generate_social_copy("", "", {"provider": "gemini"})
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
