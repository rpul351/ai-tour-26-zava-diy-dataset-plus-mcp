# Teammate guide: run the Zava Inventory Advisor on your own machine

You clone the branch, sign in to Azure, and start one script. The database builds itself and no secret is shared.

```text
Browser -> web app (:8005) -> agent service (:8006) -> 3 MCP tool servers -> PostgreSQL (Row Level Security)
                                         |
                                         +-> Azure OpenAI (your own az login)
```

## 0. What the project owner does first

You can skip this section. Ask the owner to confirm all three are done before you start.

1. Push the branch `714-project-feature-branch` and add you as a collaborator if the repository is private (GitHub, Settings, Collaborators).
2. Give your university account permission to call the model. The owner runs this once per person:

```bash
az role assignment create \
  --assignee "<your-email>@aucklanduni.ac.nz" \
  --role "Foundry User" \
  --scope /subscriptions/fc0d36e9-40e8-42d9-a294-2e8e70f7cfb7/resourceGroups/compsci714_rg
```

   To see who has access: `az role assignment list --scope <same scope> -o table`. To remove someone, use `az role assignment delete` with the same arguments.
3. Send you the three settings in step 4 below. None of them is a secret.

Every question you ask is billed to the owner's Azure subscription, at about $0.008 a question at list price. Do not run the evaluation (`python -m tests.evaluation`, about $0.30 a run) without asking.

## 1. What you need installed

- Docker Desktop, with at least 4 GB of memory allowed.
- VS Code with the Dev Containers extension.
- Git.

## 2. Clone the branch and open it in the dev container

```bash
git clone -b 714-project-feature-branch https://github.com/rpul351/ai-tour-26-zava-diy-dataset-plus-mcp.git
cd ai-tour-26-zava-diy-dataset-plus-mcp
code .
```

In VS Code choose **Reopen in Container**. The first build takes a few minutes. It installs Python 3.13 and the packages, starts the PostgreSQL database and restores the Zava data from `data/*.backup`, and creates the read-only `store_manager` login. You do not need a database password from anyone.

Run every command below in a terminal inside the container.

## 3. Sign in to Azure

```bash
az login --use-device-code
az account show
```

Sessions expire. If you later see a credential error, run `az login` again before debugging anything.

## 4. Settings file (`.env`)

```bash
cp .env.example .env
```

Edit `.env` and set these four lines (the file is git-ignored, so it never leaves your machine):

```text
RLS_USER_ID="00000000-0000-0000-0000-000000000000"
AZURE_OPENAI_ENDPOINT="https://rpul351-0887-resource.cognitiveservices.azure.com/"
GPT_MODEL_DEPLOYMENT_NAME="gpt-5-mini"
EMBEDDING_MODEL_DEPLOYMENT_NAME="text-embedding-3-small"
```

`RLS_USER_ID` is the service's default identity. With an access list (next step) each person's role decides what they see, so leave this one as shown.

## 5. Say who you are (access list)

```bash
cp src/python/workshop/access_list.example.json src/python/workshop/access_list.json
```

Edit `access_list.json` so it contains your name and role. Names are lower case, with dashes:

```json
{
  "users": {
    "your-name": { "role": "super_manager" },
    "your-name-kirkland": { "role": "store_manager", "store": "Zava Retail Kirkland" }
  }
}
```

- `super_manager` sees all 8 stores.
- `store_manager` sees only the one store you name. Try both roles, because the difference is the point of the project.
- Stores: Zava Retail Seattle, Bellevue, Tacoma, Spokane, Everett, Redmond, Kirkland and Online.

## 6. Make your access code

```bash
cd src/python/web_app
python temp_access.py generate your-name your-name-kirkland
cd ../../..
```

It prints one code per name, once. Keep it private. The names must match the access list exactly. The code file `temp_access_codes.json` is git-ignored.

## 7. Start the agent

```bash
bash scripts/run_agent.sh
```

Wait for the line `Ready.` Leave this terminal open. Then open http://127.0.0.1:8005 and sign in with your code. Add `?debug=1` to the address to see every tool call the agent makes.

Check the back end at http://127.0.0.1:8006/health. It should say `healthy`, with 16 tools and `semantic_search: ok`.

To stop: press `Ctrl+C` in that terminal, or run `bash scripts/run_agent.sh stop` from another one. To check: `bash scripts/run_agent.sh status`.

## 8. Questions to try

| Ask | What it shows |
|---|---|
| hi | A short greeting that names you, your role and which stores you can see |
| do you consider yourself a chatbot or an agent? | A short, factual answer about the agent itself, with no data fetched |
| how do I export our chat | It points you to the Save chat and Print / PDF buttons in the page header |
| Where is the most capital tied up in excess stock? Top 5. | A table, the `Scope:` line, value at cost described as an upper bound |
| Which stores are most and least aligned to the national seasonal pattern? | Ranking of stores (as a store manager it says it can see only one store) |
| Which products have more than 5 years of stock? Give me a CSV | A download link |
| Give me a histogram for June garden sales | A chart |
| I need something to protect electrical connections outdoors. How many months of stock do we hold of those products? | Semantic search combined with the stock analysis |
| Table of units sold by store in 2023 with a column for revenue per unit | A table with a calculated column |
| As a store manager: How many units did the Seattle store sell in 2023? | It says it cannot see Seattle |

When something looks wrong, write down the exact question, roughly the time and any error text, and send them to the owner. That is what is needed to find real faults.

## 9. If something goes wrong

| You see | Likely cause | What to do |
|---|---|---|
| Credential or 401 or 403 error | Azure sign-in expired, or no role yet | `az login`, then `az account show`. If it persists, ask the owner for the Foundry User role (section 0) |
| `/health` says `misconfigured` | `AZURE_OPENAI_ENDPOINT` or `RLS_USER_ID` is empty in `.env` | Fix `.env`, restart the script |
| `semantic_search` says it returns nothing | The embedding model is not reachable or deployed | Check `EMBEDDING_MODEL_DEPLOYMENT_NAME`, and with the owner that the deployment exists, before debugging code |
| "You are not on the access list" | The name in the code does not match `access_list.json` | Make the names identical and restart |
| The script says port 8005 or 8006 is in use | An old run is still going | `bash scripts/run_agent.sh stop` |
| The script says no access list or no access codes | Steps 5 or 6 not done | Do them, then start again |
| Queries return no rows | You signed in as a store manager for a store with little data | Use a `super_manager` name |
| An answer is slow | Each model call takes 5 to 20 seconds; some questions need several | Wait. Do not retype the question |
| Import error about `matplotlib` or another package | The container image is older than the branch | `pip install -r src/python/requirements.txt` |

## 10. Rules

- Never commit `.env`, `access_list.json` or `temp_access_codes.json`. They are git-ignored. Check with `git status` before every commit.
- Do not share your access code.
- If you share your running agent with someone through a tunnel, tunnel port **8005 only**. Port 8006 is the back end and has no login.
- The database password in the course files is a local development credential only. Never reuse it in Azure.
- The temporary access-code login is for local team testing only. It is removed before any Azure deployment.

## Where to read more

- `README.md`: overview and the same setup in short.
- `docs/architecture.md`: design, tools, security, failure modes, decision log and every evaluation run.
- `docs/evaluation.md`: the latest evaluation results.
- `docs/demo.md`: the demo script and the numbers to quote.
