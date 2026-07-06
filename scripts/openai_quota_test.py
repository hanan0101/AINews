import argparse
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError


def safe_get(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def get_output_text(response):
    text = safe_get(response, "output_text")
    if text:
        return text
    try:
        parts = []
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if hasattr(content, "text"):
                        parts.append(content.text)
        return "\n".join(parts)
    except Exception:
        return ""


def print_usage(response):
    usage = safe_get(response, "usage")
    if not usage:
        print("Usage: not returned")
        return
    print("Usage:")
    print("  input_tokens :", safe_get(usage, "input_tokens"))
    print("  output_tokens:", safe_get(usage, "output_tokens"))
    print("  total_tokens :", safe_get(usage, "total_tokens"))


def build_prompt(prompt_size):
    if prompt_size == "small":
        return "Say exactly: connection-ok"
    if prompt_size == "medium":
        return """
Classify this course for an internal employee newsletter:
Title: Generative AI for workplace productivity
URL: https://example.com/course
Snippet: Learn how employees can use AI tools to summarize, draft, and organize daily work.

Return short JSON only.
"""
    if prompt_size == "large":
        courses = []
        for i in range(1, 31):
            courses.append({
                "title": f"Generative AI for Work Course {i}",
                "url": f"https://example.com/course-{i}",
                "platform": "Test Platform",
                "snippet": "A practical course about using AI tools at work for productivity, writing, automation, and decision support.",
            })
        return f"""
You classify AI courses for an internal employee newsletter.

Classify every course by:
- is_ai_course
- is_course
- audience
- level: beginner / intermediate / advanced
- employee_fit_score from 0 to 5
- decision: accept / reject / needs_review

Return JSON only.

Courses:
{courses}
"""
    raise ValueError("Unknown prompt_size")


def load_project_env():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / "backend" / ".env", override=True)
    load_dotenv(root / ".env", override=False)


def main():
    parser = argparse.ArgumentParser(description="Standalone OpenAI API quota/rate-limit test.")
    parser.add_argument("--requests", type=int, default=3, help="Number of API requests to send.")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds between requests.")
    parser.add_argument("--prompt-size", choices=["small", "medium", "large"], default="small")
    parser.add_argument("--max-output-tokens", type=int, default=300)
    parser.add_argument("--model", default="", help="Override model. Defaults to AI_UPDATES_OPENAI_MODEL or OPENAI_MODEL.")
    args = parser.parse_args()

    load_project_env()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = (args.model or os.getenv("AI_UPDATES_OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing. Put it in backend/.env")

    client = OpenAI(api_key=api_key)
    prompt = build_prompt(args.prompt_size)

    print("=" * 70)
    print("OpenAI API quota/rate-limit test")
    print("Key loaded:", bool(api_key), "prefix:", api_key[:7])
    print("Model:", model)
    print("Requests:", args.requests)
    print("Sleep:", args.sleep)
    print("Prompt size:", args.prompt_size)
    print("Max output tokens:", args.max_output_tokens)
    print("=" * 70)

    success = 0
    failed = 0
    for i in range(1, args.requests + 1):
        print(f"\n[{i}/{args.requests}] Sending at {datetime.now().strftime('%H:%M:%S')}...")
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
                max_output_tokens=args.max_output_tokens,
            )
            text = get_output_text(response)
            print("SUCCESS")
            print("Response:")
            print((text or "").strip()[:500])
            print_usage(response)
            success += 1
        except AuthenticationError as exc:
            failed += 1
            print("AUTH ERROR")
            print("The API key is invalid or unauthorized.")
            print(str(exc)[:1200])
            break
        except RateLimitError as exc:
            failed += 1
            print("RATE LIMIT / QUOTA")
            print("This usually means RPM/TPM limit, spend limit, or insufficient quota.")
            print(str(exc)[:1500])
        except APIStatusError as exc:
            failed += 1
            print("API STATUS ERROR")
            print("Status code:", exc.status_code)
            print(str(exc)[:1500])
            if exc.status_code == 429:
                print("Meaning: rate limit or quota.")
            elif exc.status_code == 402:
                print("Meaning: billing, credits, or spend limit.")
            elif exc.status_code == 403:
                print("Meaning: model/project permission issue.")
            elif exc.status_code == 404:
                print("Meaning: model name is invalid or unavailable.")
        except APIConnectionError as exc:
            failed += 1
            print("CONNECTION ERROR")
            print(str(exc)[:1200])
        except Exception as exc:
            failed += 1
            print("UNKNOWN ERROR")
            print(type(exc).__name__)
            print(str(exc)[:1500])

        if i < args.requests:
            print(f"Waiting {args.sleep} seconds...")
            time.sleep(args.sleep)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("Success:", success)
    print("Failed :", failed)
    print("=" * 70)


if __name__ == "__main__":
    main()
