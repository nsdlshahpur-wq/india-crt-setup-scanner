# ChatGPT AI Assistant — Setup

## What changed
- Added a dedicated Streamlit page: `pages/4_ChatGPT_AI_Assistant.py`.
- Uses the OpenAI Responses API from the server-side Streamlit process.
- Reads the current session's Daily Scanner, selected-symbol MTF, five-pair screener, historical ensemble report, data errors and local breadth snapshot when available.
- Keeps a separate ChatGPT conversation in Streamlit session state. The existing Gemini command centre and scanner/ML rules are not modified.
- Sets `store: false` on Responses API requests. Do not send broker credentials or other secrets as prompts.

## Required deployment setting
In Streamlit Community Cloud:
1. Open the app → **Manage app** → **Settings** → **Secrets**.
2. Add:

```toml
OPENAI_API_KEY = "your_openai_api_key"
OPENAI_MODEL = "gpt-5.5"
```

3. Save and reboot/redeploy the app.

The API key must remain in Streamlit Secrets or a server environment variable. Never add it to GitHub, source code, screenshots, or browser-side code.

## How to use
1. Run the existing Dashboard scan first.
2. Run the MTF or Multi-Symbol Screener if you want those results included.
3. Open **ChatGPT AI Assistant** in the Streamlit navigation.
4. Ask questions in Hindi or English.

The page uses only records present in the current Streamlit session. If the app restarts or a scan has not been run, the relevant snapshot may be unavailable. It does not execute trades, and AI analysis is not a guarantee or investment advice.

## Model selection
`OPENAI_MODEL` is optional. The default is `gpt-5.5`. Use a model ID enabled for your OpenAI API project.
