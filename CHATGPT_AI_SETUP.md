# CRT AI Assistant — Rebuilt Setup

The dedicated Streamlit page is `pages/4_ChatGPT_AI_Assistant.py`.

## Quick setup (no code editing)

1. Open the app and select **CRT AI Assistant** from the left navigation.
2. In the page sidebar, paste an OpenAI API key into **OpenAI API Key**. The field is masked.
3. Select a model and press **Test API Connection**.
4. If the test succeeds, ask questions in the chat box.

The key entered in the page is held only in the current Streamlit session memory; it is not written to the repository or a file. For a persistent server-side setup, add these values in Streamlit Cloud → Manage app → Settings → Secrets:

```toml
OPENAI_API_KEY = "your_openai_api_key"
OPENAI_MODEL = "gpt-5.5"
```

Never commit or share the API key. Create/manage keys at https://platform.openai.com/api-keys.

## Scanner data context

Run the Dashboard scan first. Run MTF Analysis or the Multi-Symbol Screener as needed. The assistant can then use the corresponding results held in the same Streamlit session. It cannot see scans from a different session or from a previous app restart.

## Troubleshooting

- **401 / invalid_api_key:** check the key and ensure it belongs to the intended OpenAI API project.
- **429 / insufficient_quota:** check API billing, credits, and project limits.
- **model_not_found / model access:** select a model enabled for the API project.
- **No scanner records:** run the relevant scan before asking for current setups.

ChatGPT subscriptions and API billing are separate. This page uses the OpenAI API; a ChatGPT Go subscription does not provide API usage credits.

## Safety and limitations

Requests send `store: false`. The assistant is read-only: it does not place or modify broker orders, does not continuously monitor markets, and does not provide guaranteed signals or investment advice. Yahoo Finance data can be delayed or incomplete.
