# Change an API key

The Studio judge and the chatbot being tested have separate keys. Changing the judge key does not change the chatbot's model provider.

## Easiest option: change the judge on screen

Open Studio, select **Evaluate**, then **Choose your judge**. Open **Model and key**, enter the provider's model ID and API key, and select that judge. For a running evaluation, use **Apply judges to active run**. Keys entered here apply to that run; they are not written into the project `.env` or copied into reports.

## Save judge accounts in Studio's own .env

Edit `.env` in the Studio project root. On this PC it is `D:\AI-Agent-Testing-Studio\.env`. No chatbot folder or external credentials file is required.

Set `STUDIO_JUDGE_PROVIDER` to your default judge provider:

| Provider value | Key setting         | Model setting     |
| -------------- | ------------------- | ----------------- |
| `openai`       | `OPENAI_API_KEY`    | `OPENAI_MODEL`    |
| `claude`       | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` |
| `gemini`       | `GEMINI_API_KEY`    | `GEMINI_MODEL`    |
| `gemma`        | `GEMINI_API_KEY`    | `GEMMA_MODEL`     |
| `ollama`       | No cloud API key    | `OLLAMA_MODEL`    |

For example, select `STUDIO_JUDGE_PROVIDER=gemini`, enter your key in `GEMINI_API_KEY`, and set `GEMINI_MODEL` to a model available to your account. The provider's endpoint is selected automatically. You can use that judge to evaluate any connected chatbot; the target bot and judge do not need to share a provider.

You may configure several provider keys in this same file. When you choose judges on screen, Studio uses each matching provider's saved key. Entering a key in the UI overrides the saved key for that judge. Use **Show available models** to list models from that saved account. Password fields and API responses never reveal saved key values.

Restart the Studio backend after editing `.env`, when no evaluation is active. An environment variable already set in the launching terminal takes precedence over `.env`; update or remove an old terminal value if the change does not appear.

### Custom or advanced judge settings

Leave `STUDIO_JUDGE_URL`, `STUDIO_JUDGE_MODEL`, and `STUDIO_JUDGE_API_KEY` empty for normal provider selection. These values override the default provider when filled. For another compatible service, set `STUDIO_JUDGE_PROVIDER=custom` and supply its endpoint, model and key. A known provider's saved key is reused only for its configured endpoint; it is never automatically sent to an arbitrary bot or custom host.

Provider endpoints, model-variable names and credential-variable names live in `app/studio/settings.json`. Advanced installations may still explicitly opt into `STUDIO_JUDGE_ENV_FILE` and `STUDIO_JUDGE_KEY_NAME` for a separate credentials file. They are unused by default; a Studio-owned provider key takes priority. No target-bot path belongs in the standard setup.

## Change the Reliance chatbot's provider key

Edit `D:\reliance-project\backend\.env`, then restart the Reliance backend. Its source reads these names:

| Provider              | Key variable        | Model variable                 |
| --------------------- | ------------------- | ------------------------------ |
| Gemini / hosted Gemma | `GOOGLE_API_KEY`    | `GEMINI_MODEL` / `GEMMA_MODEL` |
| OpenAI                | `OPENAI_API_KEY`    | `OPENAI_MODEL`                 |
| Claude                | `ANTHROPIC_API_KEY` | `CLAUDE_MODEL`                 |
| Local Ollama          | No provider API key | `OLLAMA_MODEL`                 |

For Reliance, use `GOOGLE_API_KEY` for Gemini, not `GEMINI_API_KEY`. Set the requested provider in the chatbot as well; adding a key alone does not change an explicitly selected provider. Another chatbot may use a different configuration file; follow that chatbot's `.env.example`.

In Studio, a bot card's **Advanced connection settings → API key** authenticates requests to that chatbot's API. It does not update the cloud key inside the chatbot server.

Do not edit the Python source to rotate a key. Keep real keys in local `.env` files or password fields; `.env.example` contains placeholders and is safe to share.

## Where the testing code lives

| Mode                                                                       | Main files                                           |
| -------------------------------------------------------------------------- | ---------------------------------------------------- |
| Black-box: tests responses through chat/API                                | `app/assurance/black.py`, `app/blackbox/runner.py`   |
| Gray-box: uses supplied instructions, knowledge and traces to guide checks | `app/assurance/gray.py`, `app/studio/gray-v1.json`   |
| White-box: isolated read-only source scanning                              | `app/assurance/white.py`, `app/assurance/sandbox.py` |

The local files and the GitHub `master` branch use the same paths.
