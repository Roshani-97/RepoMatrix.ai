from flask import Flask, jsonify, request
from flask_cors import CORS
from github import Github
from dotenv import load_dotenv
from groq import Groq
from tavily import TavilyClient
import os
import requests

load_dotenv()

app = Flask(__name__)
CORS(app)

github_token = os.getenv("GITHUB_TOKEN")
gitlab_token = os.getenv("GITLAB_TOKEN")
groq_key = os.getenv("GROQ_API_KEY")
tavily_key = os.getenv("TAVILY_API_KEY")
e2b_key = os.getenv("E2B_API_KEY")

g = Github(github_token)
groq_client = Groq(api_key=groq_key)
tavily_client = TavilyClient(api_key=tavily_key)


def parse_github_commit(url):
    clean = url.replace("https://github.com/", "").replace("http://github.com/", "")
    parts = clean.strip("/").split("/")
    owner = parts[0]
    repo_name = parts[1]
    sha = parts[3]

    repo = g.get_repo(f"{owner}/{repo_name}")
    commit = repo.get_commit(sha)

    files_changed = []
    for file in commit.files:
        files_changed.append({
            "filename": file.filename,
            "status": file.status,
            "additions": file.additions,
            "deletions": file.deletions,
            "patch": file.patch if file.patch else "Binary file or too large to display"
        })

    return {
        "source": "GitHub",
        "sha": commit.sha[:10],
        "full_sha": commit.sha,
        "message": commit.commit.message,
        "author": commit.commit.author.name,
        "date": commit.commit.author.date.strftime("%B %d, %Y"),
        "files_changed": files_changed,
        "total_additions": commit.stats.additions,
        "total_deletions": commit.stats.deletions,
        "repo": f"{owner}/{repo_name}",
        "url": url
    }


def parse_gitlab_commit(url):
    clean = url.replace("https://gitlab.com/", "").replace("http://gitlab.com/", "")
    parts = clean.strip("/").split("/")
    owner = parts[0]
    repo_name = parts[1]

    sha = None
    for i, part in enumerate(parts):
        if part == "commit" and i + 1 < len(parts):
            sha = parts[i + 1]
            break

    if not sha:
        raise ValueError("Could not find commit SHA in GitLab URL")

    project_path = f"{owner}/{repo_name}"
    encoded_path = project_path.replace("/", "%2F")
    headers = {}
    if gitlab_token:
        headers["PRIVATE-TOKEN"] = gitlab_token

    commit_url = f"https://gitlab.com/api/v4/projects/{encoded_path}/repository/commits/{sha}"
    commit_resp = requests.get(commit_url, headers=headers)

    if commit_resp.status_code != 200:
        raise ValueError(f"GitLab API error: {commit_resp.status_code}")

    commit_data = commit_resp.json()
    diff_url = f"https://gitlab.com/api/v4/projects/{encoded_path}/repository/commits/{sha}/diff"
    diff_resp = requests.get(diff_url, headers=headers)
    diff_data = diff_resp.json() if diff_resp.status_code == 200 else []

    files_changed = []
    total_additions = 0
    total_deletions = 0

    for diff in diff_data:
        additions = diff.get("diff", "").count("\n+")
        deletions = diff.get("diff", "").count("\n-")
        total_additions += additions
        total_deletions += deletions

        status = "modified"
        if diff.get("new_file"): status = "added"
        elif diff.get("deleted_file"): status = "removed"
        elif diff.get("renamed_file"): status = "renamed"

        files_changed.append({
            "filename": diff.get("new_path", diff.get("old_path", "unknown")),
            "status": status,
            "additions": additions,
            "deletions": deletions,
            "patch": diff.get("diff", "No diff available")
        })

    return {
        "source": "GitLab",
        "sha": sha[:10],
        "full_sha": sha,
        "message": commit_data.get("message", "No message"),
        "author": commit_data.get("author_name", "Unknown"),
        "date": commit_data.get("authored_date", "")[:10],
        "files_changed": files_changed,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "repo": f"{owner}/{repo_name}",
        "url": url
    }


def search_web_evidence(commit):
    try:
        commit_msg = commit['message'].split('\n')[0][:80]
        repo = commit.get('repo', '')

        filenames = []
        for f in commit['files_changed'][:2]:
            name = f['filename'].split('/')[-1]
            filenames.append(name)

        queries = [
            f"{repo} {commit_msg}",
            f"github {commit_msg} fix issue",
            f"{' '.join(filenames)} bug fix" if filenames else commit_msg
        ]

        all_results = []
        seen_urls = set()

        for query in queries[:2]:
            try:
                response = tavily_client.search(
                    query=query,
                    max_results=3,
                    search_depth="basic"
                )
                for r in response.get("results", []):
                    url = r.get("url", "")
                    if url not in seen_urls and url:
                        seen_urls.add(url)

                        source_type = "web"
                        if "stackoverflow.com" in url:
                            source_type = "stackoverflow"
                        elif "github.com" in url:
                            source_type = "github"
                        elif "docs." in url or "documentation" in url.lower():
                            source_type = "docs"

                        all_results.append({
                            "title": r.get("title", "")[:80],
                            "url": url,
                            "snippet": r.get("content", "")[:150],
                            "source_type": source_type
                        })
            except Exception:
                continue

        return all_results[:4]

    except Exception as e:
        return []


def find_similar_patterns(commit):
    try:
        filenames = [f['filename'].split('/')[-1] for f in commit['files_changed'][:2]]
        file_name = filenames[0] if filenames else ""
        
        search_queries = [
            f"github {file_name} similar implementation pattern",
            f"{file_name} {commit['message'].split()[0] if commit['message'] else ''} fix similar",
        ]
        
        results = []
        seen_urls = set()
        
        for query in search_queries[:2]:
            try:
                response = tavily_client.search(query=query, max_results=3, search_depth="basic")
                for r in response.get("results", []):
                    url = r.get("url", "")
                    if url not in seen_urls and "github.com" in url:
                        seen_urls.add(url)
                        results.append({
                            "title": r.get("title", "")[:80],
                            "url": url,
                            "snippet": r.get("content", "")[:150],
                            "repo": extract_repo_from_url(url)
                        })
            except Exception:
                continue
        
        return results[:4]
    except Exception as e:
        return []


def extract_repo_from_url(url):
    parts = url.replace("https://github.com/", "").replace("http://github.com/", "").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return "unknown"


def extract_code_snippets(commit):
    old_code = []
    new_code = []
    
    for f in commit["files_changed"][:2]:
        patch = f.get("patch", "")
        if not patch or patch == "Binary file or too large to display":
            continue
        
        lines = patch.split("\n")
        in_old = False
        in_new = False
        old_block = []
        new_block = []
        
        for line in lines[:50]:
            if line.startswith("@@"):
                in_old = "old" in line or "-" in line.split("@@")[0]
                in_new = "new" in line or "+" in line.split("@@")[-1]
                old_block = []
                new_block = []
            elif line.startswith("-") and not line.startswith("---"):
                old_block.append(line)
                in_old = True
            elif line.startswith("+") and not line.startswith("+++"):
                new_block.append(line)
                in_new = True
        
        if old_block or new_block:
            old_code.append({"file": f["filename"], "lines": old_block[-10:]})
            new_code.append({"file": f["filename"], "lines": new_block[-10:]})
    
    return old_code, new_code


def execute_code_proof(commit):
    if not e2b_key:
        return {"error": "E2B_API_KEY not configured", "available": False}
    
    try:
        from e2b_code_interpreter import Sandbox
        
        old_code, new_code = extract_code_snippets(commit)
        
        if not new_code:
            return {"error": "No executable code found in commit", "available": False}
        
        results = []
        image_patterns = ["matplotlib", "plt.", "plot(", "sns.", " PIL ", "Image.open", "cv2.", "ImageDraw", "graph", "figure"]
        
        with Sandbox.create() as sandbox:
            for code_block in new_code:
                if code_block["lines"]:
                    code = "\n".join(code_block["lines"])
                    code = code.lstrip("+")
                    
                    if any(pattern in code for pattern in image_patterns):
                        results.append({
                            "file": code_block["file"],
                            "code": code[:200],
                            "output": "Skipped: This code generates visual output (matplotlib/images) which cannot be displayed as text.",
                            "success": None,
                            "skipped": True
                        })
                        continue
                    
                    try:
                        execution = sandbox.run_code(code, timeout=10)
                        output = str(execution.text)[:500] if execution.text else "Executed successfully (no output)"
                        
                        if hasattr(execution, 'images') and execution.images:
                            output += "\n[Note: Visual output generated but not displayed]"
                        
                        results.append({
                            "file": code_block["file"],
                            "code": code[:200],
                            "output": output,
                            "success": True
                        })
                    except Exception as e:
                        error_msg = str(e)
                        if "image" in error_msg.lower():
                            error_msg = "This code generates visual output and cannot be analyzed as text."
                        results.append({
                            "file": code_block["file"],
                            "code": code[:200],
                            "output": f"Execution error: {error_msg[:100]}",
                            "success": False
                        })
        
        return {"available": True, "results": results}
    
    except ImportError:
        return {"error": "E2B SDK not installed. Run: pip install e2b-code-interpreter", "available": False}
    except Exception as e:
        return {"error": str(e), "available": False}


def explain_with_groq(commit, web_evidence):
    files_summary = ""
    for f in commit["files_changed"][:3]:
        files_summary += f"\nFile: {f['filename']} ({f['status']})\n"
        if f["patch"] and f["patch"] != "Binary file or too large to display":
            patch_lines = f["patch"].split("\n")[:30]
            files_summary += "\n".join(patch_lines) + "\n"

    evidence_context = ""
    if web_evidence:
        evidence_context = "\n\nRELATED WEB CONTEXT FOUND:\n"
        for e in web_evidence[:3]:
            evidence_context += f"- {e['title']}: {e['snippet']}\n"

    prompt = f"""You are an expert code archaeologist. Analyze this Git commit and explain WHY it was written.

COMMIT DETAILS:
- Message: {commit['message']}
- Author: {commit['author']}
- Date: {commit['date']}
- Repository: {commit.get('repo', 'unknown')}
- Files changed: {len(commit['files_changed'])}
- Total additions: {commit['total_additions']}
- Total deletions: {commit['total_deletions']}

CODE CHANGES:
{files_summary}
{evidence_context}

Provide your response in this EXACT format:

PROBLEM: (1-2 sentences: what problem was this commit solving?)

THINKING: (2-3 sentences: what was the developer thinking and why this approach?)

BUG_BEFORE: (start with yes or no + 1 sentence: was there a bug before this change?)

STILL_RELEVANT: (start with yes or no + 1 sentence: is this approach still valid today?)

LESSON: (1 sentence: what can a beginner developer learn from this commit?)"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
        temperature=0.3
    )

    response_text = response.choices[0].message.content

    result = {
        "problem": "",
        "thinking": "",
        "bug_before": "",
        "still_relevant": "",
        "lesson": "",
        "model": "Llama 3.3 70B via Groq"
    }

    lines = response_text.strip().split("\n")
    current_key = None

    for line in lines:
        line = line.strip()
        if line.startswith("PROBLEM:"):
            current_key = "problem"
            result["problem"] = line.replace("PROBLEM:", "").strip()
        elif line.startswith("THINKING:"):
            current_key = "thinking"
            result["thinking"] = line.replace("THINKING:", "").strip()
        elif line.startswith("BUG_BEFORE:"):
            current_key = "bug_before"
            result["bug_before"] = line.replace("BUG_BEFORE:", "").strip()
        elif line.startswith("STILL_RELEVANT:"):
            current_key = "still_relevant"
            result["still_relevant"] = line.replace("STILL_RELEVANT:", "").strip()
        elif line.startswith("LESSON:"):
            current_key = "lesson"
            result["lesson"] = line.replace("LESSON:", "").strip()
        elif line and current_key:
            result[current_key] += " " + line

    return result


@app.route("/api/commit", methods=["POST"])
def get_commit():
    data = request.json
    url = data.get("url", "").strip()
    include_execution = data.get("include_execution", False)

    if not url:
        return jsonify({"success": False, "error": "Please provide a commit URL"})

    try:
        if "github.com" in url:
            commit = parse_github_commit(url)
        elif "gitlab.com" in url:
            commit = parse_gitlab_commit(url)
        else:
            return jsonify({"success": False, "error": "URL not recognized. Please use a GitHub or GitLab commit URL."})

        web_evidence = search_web_evidence(commit)
        explanation = explain_with_groq(commit, web_evidence)
        similar_patterns = find_similar_patterns(commit)
        
        execution_result = None
        if include_execution:
            execution_result = execute_code_proof(commit)

        response = {
            "success": True,
            "commit": commit,
            "explanation": explanation,
            "web_evidence": web_evidence,
            "similar_patterns": similar_patterns
        }
        
        if execution_result:
            response["execution"] = execution_result

        return jsonify(response)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/execute", methods=["POST"])
def execute_code():
    data = request.json
    url = data.get("url", "").strip()
    
    if not url:
        return jsonify({"success": False, "error": "Please provide a commit URL"})
    
    try:
        if "github.com" in url:
            commit = parse_github_commit(url)
        elif "gitlab.com" in url:
            commit = parse_gitlab_commit(url)
        else:
            return jsonify({"success": False, "error": "URL not recognized"})
        
        result = execute_code_proof(commit)
        return jsonify({"success": True, "execution": result})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/git-guide", methods=["POST"])
def git_guide():
    data = request.json
    repo_url = data.get("repo_url", "").strip()
    concept = data.get("concept", "").strip()

    if not repo_url:
        return jsonify({"success": False, "error": "Please provide a repository URL"})

    try:
        if "github.com" not in repo_url:
            return jsonify({"success": False, "error": "Git Guide currently supports GitHub only"})

        clean = repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
        parts = clean.strip("/").split("/")
        owner = parts[0]
        repo_name = parts[1]

        repo = g.get_repo(f"{owner}/{repo_name}")

        concept_map = {
            "branching": ["feature", "branch", "main", "develop"],
            "commits": ["commit", "fix", "update", "add"],
            "pull_request": ["merge", "pull", "review"],
            "debugging": ["bug", "fix", "hotfix", "patch"],
            "refactoring": ["refactor", "cleanup", "improve", "optimize"]
        }

        search_terms = concept_map.get(concept.lower(), ["commit", "fix", "feature"])
        
        commits = list(repo.get_commits()[:20])
        
        relevant_commits = []
        for commit in commits:
            message_lower = commit.commit.message.lower()
            if any(term in message_lower for term in search_terms):
                relevant_commits.append({
                    "sha": commit.sha[:10],
                    "message": commit.commit.message.split('\n')[0],
                    "author": commit.commit.author.name,
                    "date": commit.commit.author.date.strftime("%B %d, %Y")
                })
                if len(relevant_commits) >= 5:
                    break

        explanation_prompt = f"""Explain the git concept '{concept}' using real examples from the {owner}/{repo_name} repository.
Focus on how this concept is applied in real-world development. Give beginner-friendly examples."""

        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": explanation_prompt}],
            max_tokens=600,
            temperature=0.4
        )

        guide_explanation = response.choices[0].message.content

        return jsonify({
            "success": True,
            "repo": f"{owner}/{repo_name}",
            "concept": concept,
            "explanation": guide_explanation,
            "real_examples": relevant_commits
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/issues", methods=["GET"])
def find_issues():
    query = request.args.get("q", "").strip()
    language = request.args.get("lang", "").strip()
    label = request.args.get("label", "good first issue").strip()

    if not query:
        return jsonify({"success": False, "error": "Please provide a search query"})

    try:
        search_query = f"{query}"
        if language:
            search_query += f" language:{language}"
        search_query += f" label:\"{label}\" is:issue is:open"

        search_results = g.search_issues(search_query, per_page=10)

        issues = []
        for issue in search_results[:10]:
            repo_name = issue.repository.full_name if hasattr(issue, 'repository') else "unknown"
            issues.append({
                "title": issue.title,
                "url": issue.html_url,
                "repo": repo_name,
                "labels": [l.name for l in issue.labels[:5]] if hasattr(issue, 'labels') else [],
                "body": (issue.body or "")[:200] if hasattr(issue, 'body') else "",
                "created": issue.created_at.strftime("%B %d, %Y") if hasattr(issue, 'created_at') else ""
            })

        return jsonify({
            "success": True,
            "query": query,
            "count": len(issues),
            "issues": issues
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "supports": ["GitHub", "GitLab"],
        "ai": "Groq + Llama 3.3",
        "search": "Tavily",
        "sandbox": "E2B" if e2b_key else "Not configured",
        "modes": ["commit-analyzer", "git-guide", "issue-finder"]
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
