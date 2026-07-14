# AI Code Review

A security-focused AI code review tool that runs entirely on your machine.

- 🔒 Local only
- 📦 Zero Python dependencies
- 📝 Auditable
- 🚀 Single-file script

## Features
- Reviews Git diffs without executing your code
- Uses local LLMs through Ollama
- Automatic model selection based on your hardware
- JSONL audit logging
- Generates Markdown reports
- Configurable review categories
- No cloud services or telemetry

## Software requirements

- Ollama
- Python 3.9+

## Hardware requirements

### macOS

Minimum:
- Apple Silicon (M1 or newer)
- 8 GB unified memory

Recommended:
- M4 Pro or newer
- 16 GB+ unified memory

### Windows / Linux

Minimum:
- 8 GB VRAM

Recommended:
- 16 GB+ VRAM


**Note:** For the best performance, close memory-intensive applications before running the script.

## Install

Run:

```
curl -fsSL https://raw.githubusercontent.com/richardbored/ai-code-review/main/ai_code_review_install.sh | bash
```

Restart your terminal and verify the installation with:

`ai-code-review --help`

## How to use

On first launch, ai-code-review guides you through a short setup. It asks for:

The amount of memory available on your machine
A brief description of your project
A description of your current Git branch

If a suitable Ollama model is not already installed, the tool recommends one and offers to download it automatically.

A configuration file is then generated using the recommended settings. You can edit this file at any time to change:

- Review granularity
- Enabled review categories
- The LLM model
- Excluded files and folders
- Context size

Review Modes
Option	Description
(default)	Reviews unstaged changes
--all_changes	Reviews unstaged, staged, and untracked changes
--only_staged	Reviews staged changes only (ideal before opening a pull request)
--clean_cache	Clears the review cache and forces a fresh review

After the review completes, a Markdown report named `YOURBRANCH_AI_Code_Review.md` is generated in the root of your project.

## Optional 

Add the following entries to your `.gitignore`

```
*_AI_Code_Review.md
ai_coding_assistant_config.ini
```

## Caching

Reviews are cached automatically. If the LLM crashes, is interrupted, or produces an invalid response, simply run the command again. The tool resumes from the cached results instead of starting from scratch.

The cache is automatically invalidated whenever your Git diff changes, ensuring reviews always reflect the current state of your code.