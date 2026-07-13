#!/usr/bin/env python3

import argparse
from collections import defaultdict
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
from textwrap import dedent
from typing import Any, List, Literal
import urllib.request


class Colour:
    RESET = "\033[0m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def cprint(
    text: Any = "",
    colour: Colour = Colour.RESET,
    *,
    bold: bool = False,
    end: str = "\n",
) -> None:
    """Print text with ANSI colour and optional bold formatting.

    Args:
        text: The value to print. Converted to a string using ``str()``.
        colour: The ANSI colour escape sequence to apply.
        bold: If ``True``, prints the text in bold.
        end: String appended after the printed text. Defaults to a newline.
    """
    style = Colour.BOLD if bold else ""
    print(f"{style}{colour}{text}{Colour.RESET}", end=end)

banner = dedent(r"""
                          Made by Richard Bored
    ___    ____   ______          __        ____            _
   /   |  /  _/  / ____/___  ____/ /__     / __ \___ _   __(_)__ _      __
  / /| |  / /   / /   / __ \/ __  / _ \   / /_/ / _ \ | / / / _ \ | /| / /
 / ___ |_/ /_  / /___/ /_/ / /_/ /  __/  / _, _/  __/ |/ / /  __/ |/ |/ /
/_/  |_|____/  \____/\____/\__,_/\___/  /_/ |_|\___/|___/_/\___/|__/|__/

                 [ security • style • bugs ]

""").strip("\n")


def estimate_code_tokens(text: str) -> int:
    words = len(re.findall(r"\w+", text))
    punctuation = len(re.findall(r"[^\w\s]", text))

    # Rough approximation
    return int(words * 1.3 + punctuation * 0.35)


def set_working_directory() -> Path:
    """
    Set the process working directory to the directory from which
    the program was launched.

    Returns:
        Path: The current working directory.
    """
    cwd = Path.cwd()
    os.chdir(cwd)
    return cwd


def get_path_of_script():
    return Path(__file__).resolve()


def get_git_branch():
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_datetime() -> str:
    """Return the current local date and time in ISO 8601 format."""
    return datetime.now().isoformat(timespec="seconds")


PATH_FOR_DB = get_path_of_script().parent
CWD = set_working_directory()

CACHE_DIR = PATH_FOR_DB / "code_review_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = PATH_FOR_DB / "code_review_log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE_NAME = "ai_coding_assistant_config.ini"
CONFIG_FILE = CWD / CONFIG_FILE_NAME

BRANCH = get_git_branch()
DB_PATH = CACHE_DIR / f"dir_{CWD.name}__br_{BRANCH}__ai_review.db"

REPORT_FILENAME = f"{BRANCH}_AI_Code_Review.md"
REPORT_OUTPUT_PATH = CWD / REPORT_FILENAME

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

AUDIT_LOG_PATH = Path(LOG_DIR / f"dir_{CWD.name}__br_{BRANCH}__ai_review.log.jsonl")


def write_audit_event(event, **data):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **data,
    }

    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False))
        file.write("\n")
        file.flush()


def select_hardware_profile(total_memory_gb: float) -> tuple[str, int]:
    """
    Return the recommended model and maximum input-token budget.

    Uses total installed memory because the supplied recommendations
    are expressed in total-memory tiers.
    """
    if total_memory_gb <= 5:
        return [
            "qwen3.5:2b",
            "qwen3.5:2b-mlx",
        ], 4_000

    if total_memory_gb <= 8:
        return [
            "qwen3.5:4b-mlx",
            "qwen3.5:4b",
            "gemma4:e2b-it-qat",
        ], 4_000

    if total_memory_gb <= 16:
        return [
            "gemma4:12b-it-q4_K_M",
            "gemma4:12b-mlx",
            "qwen3.5:9b",
            "qwen3.5:9b-mlx"
        ], 6_000

    if total_memory_gb <= 24:
        return [
            "qwen3.6:27b",
            "qwen3.6:27b-mlx",
            "gemma4:12b-it-q4_K_M",
            "gemma4:12b-mlx",
        ], 20_000

    if total_memory_gb <= 32:
        return [
            "gemma4:26b-mlx",
            "gemma4:26b-a4b-it-q4_K_M",
            "qwen3.6:27b",
            "qwen3.6:27b-mlx"
        ], 28_000

    return [
        "qwen3.6:35b-mlx",
        "qwen3.6:35b",
        "gemma4:31b-mlx",
        "gemma4:31b-it-q4_K_M",
    ], 40_000

ReviewMode = Literal["hunks", "file_diffs", "whole_diff"]

@dataclass(frozen=True)
class ReviewPlan:
    total_memory_gb: float
    model: List[str]
    review_mode: ReviewMode
    input_tokens: int
    recommended_max_tokens: int
    reason: str


def optimise_review(
    total_memory_gb: float,
    input_tokens: int,
) -> ReviewPlan:
    """
    Choose the largest sensible review mode for the available memory
    and input-token count.

    Mode policy:
        Under 16 GB:
            hunks only

        16–24 GB:
            file diffs normally
            whole diff only when it uses at most 50% of the token budget

        24–32 GB:
            file diffs normally
            whole diff when it uses at most 65% of the token budget

        32 GB+:
            whole diff when it fits inside 80% of the token budget

    The remaining token space is kept available for prompts, code
    context, reasoning, and model output.
    """
    if input_tokens < 0:
        raise ValueError("input_tokens cannot be negative")

    model, max_tokens = select_hardware_profile(total_memory_gb)

    token_ratio = input_tokens / max_tokens if max_tokens else 1.0

    if total_memory_gb < 16:
        mode: ReviewMode = "hunks"
        reason = "Systems below 16 GB use hunk-level reviews only."

    elif total_memory_gb < 24:
        if token_ratio <= 0.50:
            mode = "whole_diff"
            reason = "The complete diff uses no more than 50% of the token budget."
        elif input_tokens <= max_tokens:
            mode = "file_diffs"
            reason = "The diff fits the budget, but is safer to review file by file."
        else:
            mode = "hunks"
            reason = "The diff exceeds the recommended token budget."

    elif total_memory_gb < 32:
        if token_ratio <= 0.65:
            mode = "whole_diff"
            reason = "The complete diff uses no more than 65% of the token budget."
        elif input_tokens <= max_tokens:
            mode = "file_diffs"
            reason = "The diff fits the budget, but file-level review leaves more headroom."
        else:
            mode = "hunks"
            reason = "The diff exceeds the recommended token budget."
    else:
        if token_ratio <= 0.80:
            mode = "whole_diff"
            reason = "The complete diff fits within the safe whole-diff budget."
        elif input_tokens <= max_tokens:
            mode = "file_diffs"
            reason = "The diff fits the maximum budget, but is too large for one complete review."
        else:
            mode = "hunks"
            reason = "The diff exceeds the recommended token budget."

    return ReviewPlan(
        total_memory_gb=total_memory_gb,
        model=model,
        review_mode=mode,
        input_tokens=input_tokens,
        recommended_max_tokens=max_tokens,
        reason=reason,
    )


@dataclass
class Setting:
    name: str
    enabled: bool
    context: str
    print_str: str

@dataclass
class ReviewConfig:
    bugs: Setting
    code_quality: Setting
    security: Setting
    secrets: Setting
    style: Setting
    spelling_and_grammar: Setting

    def __init__(self, config_path: str):
        config = ConfigParser()
        config.read(config_path)
        self.bugs=Setting(
            "bugs",
            config.getboolean("Review", "bugs", fallback=False),
            (
                "INSTRUCTIONS: \n"
                "Review the following code and identify any bugs or correctness issues. "
                "Focus on logic errors, edge cases, incorrect assumptions, potential "
                "runtime exceptions, and behavior that could produce incorrect results. "
                "Ignore code style, formatting, and non-functional improvements. "
                "For each issue you find, explain why it is a bug, describe its "
                "potential impact, and suggest a fix if appropriate. "
                "If you do not find any bugs, state that clearly."
            ),
            "Bugs"
        )
        self.code_quality=Setting(
            "code_quality",
            config.getboolean("Review", "code_quality", fallback=False),
            (
                "Review the following code with a focus on code quality. "
                "Identify issues related to readability, maintainability, simplicity, "
                "naming, structure, duplication, error handling, and adherence to best "
                "practices. Ignore stylistic preferences unless they affect clarity or "
                "maintainability. Provide concise, actionable recommendations with brief "
                "explanations."
            ),
            "Code quality"
        )
        self.security=Setting(
            "security",
            config.getboolean("Review", "security", fallback=False),
            (
                "Review the following code with a focus on security. "
                "Identify potential vulnerabilities, insecure patterns, input validation "
                "issues, authentication or authorization flaws, injection risks, sensitive "
                "data exposure, and other security concerns. Ignore purely stylistic issues. "
                "Provide concise, actionable recommendations with brief explanations."
            ),
            "Security"
        )
        self.secrets=Setting(
            "secrets",
            config.getboolean("Review", "secrets", fallback=False),
            (
                "Review the following code for exposed secrets or sensitive information. "
                "Look for API keys, passwords, tokens, credentials, private keys, connection "
                "strings, personal data, and other PII that may have been committed accidentally. "
                "Report only credible findings and briefly explain the risk."
            ),
            "Secrets"
        )
        self.style=Setting(
            "style",
            config.getboolean("Review", "style", fallback=False),
            (
                "Review the following code with a focus on style. "
                "Identify issues related to formatting, consistency, naming, idiomatic language "
                "usage, and adherence to the project's style conventions. Ignore functional, "
                "performance, and security concerns. Provide concise, actionable recommendations "
                "with brief explanations."
            ),
            "Style"
        )
        self.spelling_and_grammar=Setting(
            "spelling_and_grammar",
            config.getboolean("Review", "spelling_and_grammar", fallback=False),
            (
                "Review the following  code for spelling and grammar only. "
                "Identify spelling mistakes, grammatical errors, punctuation issues, and "
                "awkward or unidiomatic phrasing. Ignore style, tone, factual accuracy, "
                "and content unless they directly affect grammar or clarity. "
            ),
            "Spelling and grammar"
        )


def create_config():
    config = ConfigParser()

    memory = None
    project_description = None
    branch_description = None
    if Path(CONFIG_FILE).is_file():
        config = ConfigParser()
        config.read(CONFIG_FILE)
        memory = config.getint("General", "memory_gb", fallback=None)
        project_description = config.get("General", "project_description", fallback="")
        if config.get("General", "branch_name", fallback=None) == BRANCH:
            branch_description = config.get("General", "branch_description", fallback="")

    if memory is None:
        print("Welcome! Let's configure your assistant.\n")
        while True:
            memory = input("How much memory (in GB) does your computer have? ")
            try:
                memory = int(memory)
                if memory > 0:
                    break
            except ValueError:
                pass
            print("Please enter a whole number.\n")

        while True:
            project_description = input("Write a brief description of your project: ")
            if project_description != "":
                break
            print("Please enter a brief description of your project.\n")

        while True:
            branch_description = input("Write a brief description of your branch: ")
            if branch_description != "":
                break
            print("Please enter a brief description of your branch.\n")

    meta = MetaData.current()
    plan = optimise_review(
        total_memory_gb=memory,
        input_tokens=meta.total_est_token_amount,
    )

    review_hunks = True
    review_diff_files = False
    review_whole_files = False

    if plan.review_mode == "whole_diff":
        review_diff_files = True
        review_whole_files = True
    elif plan.review_mode == "file_diffs":
        review_diff_files = True
        review_whole_files = False

    config["General"] = {
        "project_description": project_description,
        "branch_name": BRANCH,
        "branch_description": branch_description,
        "memory_gb": str(memory),
        "model": ",".join(plan.model),
        "debug": "false",
        "hunks_review": str(review_hunks),
        "diff_files_review": str(review_diff_files),
        "whole_diff_review": str(review_whole_files),
        "context": str(plan.recommended_max_tokens)
    }

    config["Review"] = {
        "bugs": "True",
        "code_quality": "True",
        "security": "True",
        "secrets": "True",
        "style": "True",
        "spelling_and_grammar": "True",
    }

    config["Context"] = {
        "exclude": ".git,__pycache__,venv",
    }

    with CONFIG_FILE.open("w") as f:
        config.write(f)

    write_audit_event("info", message=f"created_config_at_{CONFIG_FILE}")


def quote_ident(name):
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


class Field:
    def __init__(self, typ="TEXT", pk=False, default=None):
        self.typ = typ
        self.pk = pk
        self.default = default


class Model:
    _db = None

    @classmethod
    def db(cls):
        if Model._db is None:
            Model._db = sqlite3.connect(DB_PATH)
            Model._db.row_factory = sqlite3.Row

        return Model._db

    @classmethod
    def close_db(cls):
        if Model._db is not None:
            Model._db.close()
            Model._db = None

    @classmethod
    def wipe_db(cls):
        Model.close_db()

        if DB_PATH.exists():
            DB_PATH.unlink()

    @classmethod
    def table_name(cls):
        return quote_ident(cls.__name__)

    @classmethod
    def fields(cls):
        return {
            k: v for k, v in cls.__dict__.items()
            if isinstance(v, Field)
        }

    @classmethod
    def create_table(cls):
        cols = []

        for name, field in cls.fields().items():
            col = f"{quote_ident(name)} {field.typ}"

            if field.pk:
                if field.typ.upper() == "INTEGER":
                    col += " PRIMARY KEY AUTOINCREMENT"
                else:
                    col += " PRIMARY KEY"

            cols.append(col)

        sql = f"CREATE TABLE IF NOT EXISTS {cls.table_name()} ({', '.join(cols)})"
        cls.db().execute(sql)
        cls.db().commit()

    def __init__(self, **kwargs):
        for name, field in self.fields().items():
            setattr(self, name, kwargs.get(name, field.default))

    def create(self):
        fields = self.fields()

        pk_fields = [name for name, field in fields.items() if field.pk]
        pk_name = pk_fields[0] if pk_fields else None

        # If integer PK is None, let SQLite autogenerate it
        cols = []
        vals = []

        for name, field in fields.items():
            value = getattr(self, name)

            if field.pk and field.typ.upper() == "INTEGER" and value is None:
                continue

            cols.append(name)
            vals.append(value)

        quoted_cols = ", ".join(quote_ident(c) for c in cols)
        placeholders = ", ".join("?" for _ in cols)

        sql = (
            f"INSERT INTO {self.table_name()} "
            f"({quoted_cols}) VALUES ({placeholders})"
        )

        cur = self.db().execute(sql, vals)

        if pk_name and getattr(self, pk_name) is None:
            setattr(self, pk_name, cur.lastrowid)

        self.db().commit()
        return self

    def update(self, **changes):
        fields = self.fields()

        for key in changes:
            if key not in fields:
                raise ValueError(f"Unknown field: {key}")

        pk_fields = [name for name, field in fields.items() if field.pk]

        if not pk_fields:
            raise ValueError("Cannot update without a primary key.")

        pk_name = pk_fields[0]
        pk_value = getattr(self, pk_name)

        if pk_value is None:
            raise ValueError("Cannot update unsaved object.")

        assignments = ", ".join(
            f"{quote_ident(key)}=?" for key in changes
        )

        vals = list(changes.values()) + [pk_value]

        sql = (
            f"UPDATE {self.table_name()} "
            f"SET {assignments} "
            f"WHERE {quote_ident(pk_name)}=?"
        )

        self.db().execute(sql, vals)
        self.db().commit()

        for key, value in changes.items():
            setattr(self, key, value)

        return self

    def delete(self):
        fields = self.fields()
        pk_fields = [name for name, field in fields.items() if field.pk]

        if not pk_fields:
            raise ValueError("Cannot delete without a primary key.")

        pk_name = pk_fields[0]
        pk_value = getattr(self, pk_name)

        if pk_value is None:
            raise ValueError("Cannot delete unsaved object.")

        sql = (
            f"DELETE FROM {self.table_name()} "
            f"WHERE {quote_ident(pk_name)}=?"
        )

        self.db().execute(sql, (pk_value,))
        self.db().commit()

    @classmethod
    def all(cls):
        rows = cls.db().execute(
            f"SELECT * FROM {cls.table_name()}"
        ).fetchall()

        cols = list(cls.fields())

        return [
            cls(**dict(zip(cols, row)))
            for row in rows
        ]

    @classmethod
    def filter(cls, **where):
        fields = cls.fields()

        for key in where:
            if key not in fields:
                raise ValueError(f"Unknown field: {key}")

        if where:
            clause = " AND ".join(
                f"{quote_ident(key)}=?" for key in where
            )
            sql = f"SELECT * FROM {cls.table_name()} WHERE {clause}"
            vals = tuple(where.values())
        else:
            sql = f"SELECT * FROM {cls.table_name()}"
            vals = ()

        rows = cls.db().execute(sql, vals).fetchall()
        cols = list(fields)

        return [
            cls(**dict(zip(cols, row)))
            for row in rows
        ]

    @classmethod
    def get(cls, **where):
        results = cls.filter(**where)

        if not results:
            return None

        if len(results) > 1:
            raise ValueError("Multiple rows returned.")

        return results[0]

    @classmethod
    def sum(cls, field):
        if field not in cls.fields():
            raise ValueError(f"Unknown field: {field}")

        sql = (
            f"SELECT SUM({quote_ident(field)}) "
            f"FROM {cls.table_name()}"
        )

        result = cls.db().execute(sql).fetchone()[0]
        return result or 0


class GitDiff(Model):
    id = Field("INTEGER", pk=True)
    filename = Field("TEXT")
    old_filename = Field("TEXT")
    active = Field("INTEGER", default=True)
    hunk_index = Field("INTEGER")
    hunk_header = Field("TEXT")
    diff = Field("TEXT")
    diff_token_amount = Field("INTEGER", default=None)
    created_at = Field("TEXT")


class HunkReview(Model):
    id = Field("INTEGER", pk=True)
    git_diff_id = Field("INTEGER")
    filename = Field("TEXT")
    type_of_review = Field("TEXT")
    ai_comments = Field("TEXT")
    created_at = Field("TEXT")


class FileReview(Model):
    id = Field("INTEGER", pk=True)
    filename = Field("TEXT")
    category = Field("TEXT")
    severity = Field("TEXT")
    comment = Field("TEXT")
    created_at = Field("TEXT")


class WholeDiffReview(Model):
    id = Field("INTEGER", pk=True)
    filename = Field("TEXT")
    category = Field("TEXT")
    severity = Field("TEXT")
    comment = Field("TEXT")
    created_at = Field("TEXT")


class MetaData(Model):
    id = Field("INTEGER", pk=True)
    git_diff_hash = Field("TEXT", default=None)
    model = Field("TEXT", default=None)
    total_est_token_amount = Field("INTEGER", default=None)
    highest_file_token_amount = Field("INTEGER", default=None)

    @classmethod
    def current(cls):
        meta = cls.get(id=1)
        if meta is None:
            meta = cls(id=1)
            meta.create()
        return meta


def db_migrations():
    '''
    Database 'Migrations'
    '''
    GitDiff.create_table()
    MetaData.create_table()
    HunkReview.create_table()
    WholeDiffReview.create_table()
    FileReview.create_table()
    cprint(
        text="- DB successfully initialised!",
        colour=Colour.WHITE,
        bold=False,
    )
    write_audit_event("info", message="completed_db_migrations")

def reset_db_cache():
    Model.wipe_db()
    cprint(
        text="- Cleaned cache",
        colour=Colour.WHITE,
        bold=False,
    )
    db_migrations()
    write_audit_event("info", message="reset_db_cache")


def check_if_code_has_changed_since_last_review_and_reset(git_diff: str) -> bool:
    if git_diff == "":
        cprint(
            text="WARNING: Git diff is empty",
            colour=Colour.RED,
            bold=True,
        )
        write_audit_event("error", message="git diff is empty")
        sys.exit()

    git_diff_hash: str = hashlib.sha256(git_diff.encode("utf-8")).hexdigest()
    meta = MetaData.current()
    if meta.git_diff_hash != git_diff_hash:
        reset_db_cache()
        meta = MetaData.current()
        meta.update(git_diff_hash=git_diff_hash)
        write_audit_event("info", message=f"Detected changes in code")
        return False

    return True


class OllamaChat:
    def __init__(
        self,
        models=None,
        host="http://localhost:11434",
        num_ctx=32768,
    ):
        """
        models:
            A model name or an ordered list of acceptable models.

            The first locally installed model is selected. If none are
            installed, the user is asked whether to download one.

        Examples:
            OllamaChat("llama3.1")
            OllamaChat(["llama3.1", "qwen3:8b", "gemma3:4b"])
        """

        if models is None:
            models = ["llama3.1"]
        elif isinstance(models, str):
            models = [models]

        self.models = models
        self.host = host.rstrip("/")
        self.messages = []

        self.model = self._select_model()
        meta = MetaData.current()
        meta.update(model=self.model)
        write_audit_event("info", message=f"Using {self.model}")
        self.num_ctx = num_ctx

    def _request(self, path, payload=None, method=None):
        """Send a JSON request to the Ollama API."""

        data = None
        headers = {}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.host}{path}",
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}

        except urllib.error.HTTPError as error:
            try:
                details = error.read().decode("utf-8")
            except Exception:
                details = ""

            message = f"Ollama returned HTTP {error.code}"
            if details:
                message += f": {details}"

            raise RuntimeError(message) from error

        except urllib.error.URLError as error:
            raise RuntimeError(
                "Could not connect to Ollama. "
                "Make sure Ollama is installed and running."
            ) from error

    def get_installed_models(self):
        """Return the names of all locally installed Ollama models."""

        result = self._request("/api/tags", method="GET")
        return {
            model["name"]
            for model in result.get("models", [])
            if "name" in model
        }

    @staticmethod
    def _normalise_model_name(model):
        """
        Ollama treats an omitted tag as ':latest'.

        This allows 'llama3.1' to match an installed
        model named 'llama3.1:latest'.
        """

        if ":" not in model:
            return f"{model}:latest"

        return model
    
    def format_size(self, num_bytes):
        units = ["B", "KB", "MB", "GB", "TB"]

        size = float(num_bytes)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024

    def pull_model(self, model):
        """Download a model using Ollama, displaying progress."""

        print(f"Downloading {model}. This may take a while...")

        payload = json.dumps({
            "model": model,
            "stream": True,
        }).encode("utf-8")

        request = urllib.request.Request(
            f"{self.host}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request) as response:
                last_percent = -1

                for line in response:
                    if not line:
                        continue

                    update = json.loads(line.decode("utf-8"))

                    status = update.get("status", "")

                    if "completed" in update and "total" in update:
                        completed = update["completed"]
                        total = update["total"]

                        if total > 0:
                            percent = int(completed * 100 / total)

                            # Only print when the percentage changes.
                            if percent != last_percent:
                                print(
                                    f"\rDownloading... "
                                    f"{percent:3d}% "
                                    f"({self.format_size(completed)} / {self.format_size(total)})",
                                    end="",
                                    flush=True,
                                )
                                last_percent = percent
                    else:
                        # Print status messages like:
                        # "pulling manifest", "verifying sha256 digest", etc.
                        print(f"\n{status}")

                    if status == "success":
                        break

            print(f"\nDownloaded {model}.")
            write_audit_event("info", message=f"Downloaded {model}")
            return model

        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Failed to download model {model!r}."
            ) from e

    def _select_model(self):
        """
        Select the first installed model from self.models.

        If none are installed, ask the user which one to download.
        """

        installed = self.get_installed_models()
        normalised_installed = {
            self._normalise_model_name(name)
            for name in installed
        }

        # Use the first acceptable model that is already installed.
        for model in self.models:
            normalised = self._normalise_model_name(model)

            if normalised in normalised_installed:
                # print(f"Using installed model: {model}")
                cprint(
                    text="- Using installed model: ",
                    colour=Colour.WHITE,
                    bold=False,
                    end=""
                )
                cprint(
                    text=model,
                    colour=Colour.GREEN,
                )
                return model

        print("None of the requested models are installed.")
        print("Tip: MLX is recommended for Mac OS")
        for index, model in enumerate(self.models, start=1):
            print(f"{index}. {model}")

        while True:
            answer = input(
                "Enter the number of a model to download, "
                "or 'q' to quit: "
            ).strip()

            if answer.lower() in {"q", "quit", "n", "no"}:
                raise RuntimeError(
                    "No installed model was selected."
                )

            try:
                index = int(answer) - 1
                model = self.models[index]
            except (ValueError, IndexError):
                print("Please enter a valid model number.")
                continue

            confirmation = input(
                f"Download {model}? [y/N]: "
            ).strip().lower()

            if confirmation in {"y", "yes"}:
                return self.pull_model(model)

    def send_message(self, message):
        """
        Send a message to Ollama and return the assistant response.
        Keeps conversation history automatically.
        """

        self.messages.append({
            "role": "user",
            "content": message,
        })

        try:
            result = self._request(
                "/api/chat",
                payload={
                    "model": self.model,
                    "messages": self.messages,
                    "stream": False,
                    "options": {
                        "num_ctx": self.num_ctx,
                    },
                },
                method="POST",
            )

            assistant_message = result["message"]["content"]

        except Exception:
            # Do not retain a user message that was never successfully sent.
            self.messages.pop()
            raise

        self.messages.append({
            "role": "assistant",
            "content": assistant_message,
        })

        write_audit_event("info", message=f"sent message to ollama")

        return assistant_message

    def clear(self):
        self.messages = []
        write_audit_event("info", message=f"Clear messages in ollama")

    def unload(self):
        """Unload the current model from Ollama."""

        self._request(
            "/api/chat",
            payload={
                "model": self.model,
                "messages": [],
                "keep_alive": 0,
            },
            method="POST",
        )
        write_audit_event("info", message=f"Disconnected from ollama")


def split_diff_by_hunk(diff_text):
    """
    Split a unified Git diff into individual hunks.

    Each returned item contains:
    - filename
    - old_filename
    - hunk_index
    - hunk_header
    - diff: file metadata plus one hunk
    """

    file_chunks = re.split(
        r"(?=^diff --git )",
        diff_text,
        flags=re.MULTILINE,
    )

    hunks = []

    for file_chunk in file_chunks:
        if not file_chunk.strip():
            continue

        lines = file_chunk.splitlines(keepends=True)

        first_line = lines[0].rstrip("\r\n")

        match = re.match(
            r"^diff --git a/(.*?) b/(.*)$",
            first_line,
        )
        if not match:
            continue

        old_name = match.group(1)
        new_name = match.group(2)

        # Locate each unified-diff hunk header.
        hunk_starts = [
            index
            for index, line in enumerate(lines)
            if line.startswith("@@ ")
        ]

        # Some file diffs contain no textual hunks, for example:
        # - binary files
        # - file mode changes
        # - empty-file changes
        # - certain rename-only changes
        if not hunk_starts:
            hunks.append({
                "filename": new_name,
                "old_filename": old_name,
                "hunk_index": None,
                "hunk_header": None,
                "diff": file_chunk,
            })
            continue

        # Everything before the first @@ line is file-level metadata.
        file_header = "".join(lines[:hunk_starts[0]])

        for hunk_index, start in enumerate(hunk_starts):
            if hunk_index + 1 < len(hunk_starts):
                end = hunk_starts[hunk_index + 1]
            else:
                end = len(lines)

            hunk_lines = lines[start:end]
            hunk_header = hunk_lines[0].rstrip("\r\n")

            hunks.append({
                "filename": new_name,
                "old_filename": old_name,
                "hunk_index": hunk_index,
                "hunk_header": hunk_header,
                "diff": file_header + "".join(hunk_lines),
            })
    write_audit_event("info", message="split_diff_by_hunk")
    return hunks


def get_complete_git_diff():
    """Return a single git diff containing all changes."""

    def git(*args):
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    diff = ""

    # Unstaged tracked changes
    diff += git("diff")

    # Staged changes
    diff += git("diff", "--cached")

    # Untracked files
    untracked = git(
        "ls-files",
        "--others",
        "--exclude-standard",
    ).splitlines()

    for filename in untracked:
        diff += subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                os.devnull,
                filename,
            ],
            capture_output=True,
            text=True,
        ).stdout

    return diff


def get_git_diff():
    diff = None
    if args.all_changes:
        diff = get_complete_git_diff()
        write_audit_event("info", message="collected_complete_git_diff_all_changes")
    elif args.only_staged:
        diff = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        write_audit_event("info", message="collected_complete_git_diff_cached")
    else:
        diff = subprocess.run(
            ["git", "diff"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        write_audit_event("info", message="collected_complete_git_diff")

    return diff


def tally_diff_tokens_by_file(git_diffs):
    totals = {}
    for review in git_diffs:
        filename = review["filename"]
        token_amount = estimate_code_tokens(review["diff"])
        totals[filename] = totals.get(filename, 0) + token_amount
    return totals


def write_git_diffs(git_diffs: str, to_ignore = []):
    total_tokens = 0

    to_ignore.append(CONFIG_FILE_NAME)
    to_ignore.append(REPORT_OUTPUT_PATH)

    for review in git_diffs:
        token_amount = estimate_code_tokens(review["diff"])
        total_tokens += token_amount

        existing = GitDiff.get(
            filename=review["filename"],
            hunk_index=review["hunk_index"],
        )

        if existing is None:
            GitDiff(
                filename=review["filename"],
                old_filename=review["old_filename"],
                hunk_index=review["hunk_index"],
                hunk_header=review["hunk_header"],
                diff=review["diff"],
                diff_token_amount=token_amount,
                created_at=get_current_datetime(),
            ).create()
        write_audit_event("info", message="recorded_git_diff", file=review["filename"], hunk_index=review["hunk_index"])

    meta = MetaData.current()
    highest_file_token_amount = max(tally_diff_tokens_by_file(git_diffs).values())
    meta.update(
        total_est_token_amount=total_tokens,
        highest_file_token_amount=highest_file_token_amount,
    )


def mark_which_files_to_ignore(files_to_ignore = []):
    files_to_ignore.append(CONFIG_FILE_NAME)
    ignored_dirs = {d.rstrip("/") for d in files_to_ignore}
    for review in GitDiff.all():
        if not ignored_dirs.isdisjoint(PurePosixPath(review.filename).parts):
            review.update(active=False)


def build_context_for_llm(config, additional_context: str):
    context = ""
    project_description = config.get("General", "project_description", fallback="")
    if project_description != "" and project_description != "Write brief description of the project":
        context += f"""Project description: {project_description} \n"""
    context += f"""Branch name: {BRANCH} \n"""

    branch_description = config.get("General", "branch_description", fallback="")
    if branch_description != "" and branch_description != "Write brief description of the branch":
        context += f"""Project description: {branch_description} \n"""

    context += additional_context

    return context


def review_hunks(chat: OllamaChat):
    review_config = ReviewConfig(CONFIG_FILE)
    config = ConfigParser()
    config.read(CONFIG_FILE)
    number_of_git_hunks = len(GitDiff.all())
    number_of_reviews = sum(
        setting.enabled
        for setting in vars(review_config).values()
    )
    total_hunk_reviews = number_of_reviews * number_of_git_hunks
    completed_reviews = 0

    for field_name, setting in vars(review_config).items():
        context = build_context_for_llm(config, setting.context)
        if setting.enabled is False:
            print(f"- {setting.name} is disabled in config")
            continue

        for git_diff in GitDiff.all():
            if git_diff.active == 0:
                continue
            reviews = HunkReview.filter(
                git_diff_id=git_diff.id,
                type_of_review=setting.name,
            )
            if reviews == []:
                message = (
                    f"{str(context)} \n\n"
                    "--- GIT DIFF --- \n\n"
                    f"{git_diff.diff}"
                )
                res = chat.send_message(message=message)
                # res = f"test stand in {completed_reviews} of {total_hunk_reviews} completed..."
                HunkReview(
                    git_diff_id=git_diff.id,
                    filename=git_diff.filename,
                    type_of_review=setting.name,
                    ai_comments=res,
                    created_at=datetime.now().isoformat(),
                ).create()

            skipped_file = ""
            if reviews:
                skipped_file = "(existing review was in cache)"

            chat.clear()
            completed_reviews += 1
            print(f"- {completed_reviews} of {total_hunk_reviews} completed {skipped_file}")
    write_audit_event("info", message=f"Completed hunk review")


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("No JSON object found.")

    return json.loads(text[start:end + 1])


def review_file_diff(chat: OllamaChat):
    files = defaultdict(list)

    for hunk in GitDiff.all():
        files[hunk.filename].append(hunk.diff)

    for filename, diff_list in files.items():
        print(f"- Processing {filename}")

        existing_review = ""
        reviews = HunkReview.filter(filename=filename)
        for review in reviews:
            existing_review += f"Type: {review.type_of_review} \n"
            existing_review += f"AI comment: {review.ai_comments} \n\n"

        diff = "\n".join(diff_list)
        prompt = (
            "You are reviewing a single file from a git diff.\n\n"

            "You will be given:\n"
            "1. The git diff for one file.\n"
            "2. The previous review comments for that file.\n\n"

            "Review the diff in the context of the existing comments. "
            "Identify only new issues that were missed by the previous review. "
            "Do not repeat, reword, or expand on existing findings unless the diff "
            "provides new context that materially changes their severity or impact.\n\n"

            "Return valid JSON only using the following schema:\n"
            "{"
            '"comments": ['
            "{"
            '"category": "bug|quality|security|style|performance|other",'
            '"severity": "low|medium|high",'
            '"comment": "Concise actionable finding"'
            "}"
            "]"
            "}\n\n"

            'If there are no additional findings, return {"comments": []}.\n\n'

            "GIT DIFF:\n"
            f"{diff}\n\n"

            "PREVIOUS REVIEW COMMENTS:\n"
            f"{existing_review}"
        )

        if len(FileReview.filter(filename=filename)) > 0:
            print(f"- {filename} review already exists in cache")
            return
        res = chat.send_message(message=prompt)
        chat.clear()
        try:
            data = extract_json(res)
            for comment in data["comments"]:
                FileReview(
                    filename=filename,
                    category=comment["category"],
                    severity=comment["severity"],
                    comment=comment["comment"]
                ).create()
        except json.JSONDecodeError as e:
            print("- Ollama returned a malformed JSON. Skipping file diff review...")
            write_audit_event("warning", message=f"Review for {filename} failed")
            pass
    write_audit_event("info", message=f"Completed file diff review")


def review_whole_diff(chat: OllamaChat):
    print("- Starting whole diff review...")
    config = ConfigParser()
    config.read(CONFIG_FILE)

    entire_diff = ""
    for git_diff in GitDiff.all():
        entire_diff += git_diff.diff

    existing_review = ""

    filenames = sorted({
        git_diff.filename
        for git_diff in GitDiff.all()
    })

    existing_review += "\n"

    for filename in filenames:
        hunks = HunkReview.filter(filename=filename)
        existing_review += f"\nFILENAME: {filename} \n"
        existing_review += f"--- Individual comments --- \n"
        for hunk in hunks:
            existing_review += f"\nType of review: {hunk.type_of_review} \n"
            existing_review += f"Comment: \n{hunk.ai_comments} \n"

        file_comments = FileReview.filter(filename=filename)
        for comment in file_comments:
            existing_review += f"Category: {comment.category} \n"
            existing_review += f"Severity: {comment.severity} \n"
            existing_review += f"Comment: {comment.comment} \n"
            existing_review += "\n"

    prompt = (
        "You are performing the final pass of a code review.\n\n"

        "You will be given:\n"
        "1. The complete git diff.\n"
        "2. The concatenated hunk-level reviews.\n\n"

        "Review the entire diff in the context of the existing reviews. "
        "Identify only issues that were missed by the hunk reviews. "
        "Do not repeat existing findings unless additional context from other "
        "files materially changes their severity or impact.\n\n"

        "Return valid JSON only using the following schema:\n"
        "{"
        '"files": ['
        "{"
        '"filename": "path/to/file.py",'
        '"comments": ['
        "{"
        '"category": "bug|quality|security|style|performance|other",'
        '"severity": "low|medium|high",'
        '"comment": "Concise actionable finding"'
        "}"
        "]"
        "}"
        "]"
        "}\n\n"

        "Only include files with new findings. "
        'If there are no additional findings, return {"files": []}.\n\n'

        "COMPLETE GIT DIFF:\n"
        f"{entire_diff}\n\n"

        "EXISTING HUNK REVIEWS:\n"
        f"{existing_review}"
    )

    max_token_amount = config.getint("General", "context")
    if estimate_code_tokens(prompt) > max_token_amount:
        print("- Context too small for entire diff review")
        return
    
    if WholeDiffReview.get(id=1) is not None:
        print("- Whole diff review already exists in cache")
        return

    res = chat.send_message(message=prompt)
    chat.clear()
    try:
        data = extract_json(res)
        for file in data["files"]:
            filename = file["filename"]
            for comment in file["comments"]:
                WholeDiffReview(
                    filename=filename,
                    category=comment["category"],
                    severity=comment["severity"],
                    comment=comment["comment"]
                ).create()
    except json.JSONDecodeError as e:
        print("- Ollama returned a malformed JSON. Skipping whole diff review...")
        write_audit_event("warning", message=f"Review for whole diff failed")
        pass

def export_markdown_report():
    meta = MetaData.current()
    review_config = ReviewConfig(CONFIG_FILE)
    config = ConfigParser()
    config.read(CONFIG_FILE)
    lines = [
        "# AI Code Review Report",
        "",
        "## Overview",
        "",
        f"**Generated**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Branch**: {BRANCH}  ",
        f"**Branch description**: {config.get('General', 'branch_description')}  ",
        f"**Model**: {meta.model}  ",
        f"**Est. number of tokens in git diff**:  {meta.total_est_token_amount}    ",
        f"**Reviewed hunks**: {config.get('General', 'hunks_review')}  ",
        f"**Reviewed files**: {config.get('General', 'diff_files_review')}  ",
        f"**Reviewed whole diff**: {config.get('General', 'whole_diff_review')}  ",
        f"**{review_config.bugs.print_str}**: {review_config.bugs.enabled}  ",
        f"**{review_config.code_quality.print_str}**: {review_config.code_quality.enabled}  ",
        f"**{review_config.security.print_str}**: {review_config.security.enabled}  ",
        f"**{review_config.secrets.print_str}**: {review_config.secrets.enabled}  ",
        f"**{review_config.style.print_str}**: {review_config.style.enabled}  ",
        f"**{review_config.spelling_and_grammar.print_str}**: {review_config.spelling_and_grammar.enabled}  ",
        "",
    ]

    filenames = sorted({
        git_diff.filename
        for git_diff in GitDiff.all()
    })

    # Create anchor links
    lines.append("## Files")
    for filename in filenames:
        lines.append(f"- [{filename}](#{filename})  ")

    complete_diff_index_name : str = "Final diff review"
    complete_diff_anchor_link: str = "complete_file"
    if len(WholeDiffReview.all()) > 0:
        lines.append(f"- [{complete_diff_index_name}](#{complete_diff_anchor_link})  ")

    for filename in filenames:
        git_diffs = GitDiff.filter(filename=filename)
        lines.append(f'<a id="{filename}"></a>  ')
        lines.append(f"## {filename}  ")
        for diff in git_diffs:
            lines.append(f"```{diff.diff}```")
            reviews = HunkReview.filter(git_diff_id=diff.id)
            for review in reviews:
                setting = getattr(review_config, review.type_of_review)
                review_section = (
                    f"<Details summary=\"{review.type_of_review}\">\n\n"
                    f'<summary style="font-size:18px;margin-bottom:10px;">&nbsp {setting.print_str}</summary>'
                    '<div style="margin-left: 1rem; padding-left: 1rem; border-left: 3px solid #d1d5db;"> \n'
                    f"\n{review.ai_comments}\n  "
                    "</div>"
                    "</Details>"
                    "\n"
                )
                lines.append(review_section)
        file_reviews = FileReview.filter(filename=filename)
        if len(file_reviews) > 0:
            number_of_comments = len(file_reviews)
            lines.append(f"<Details summary=\"File Review\">\n\n")
            lines.append(f'<summary style="font-size:18px;margin-bottom:10px;">&nbsp File Review ({number_of_comments} comments)</summary>')
            lines.append('<div style="margin-left: 1rem; padding-left: 1rem; border-left: 3px solid #d1d5db;"> \n')
            for index, review in enumerate(file_reviews):
                category = review.category[:1].upper() + review.category[1:]
                severity = review.severity[:1].upper() + review.severity[1:]
                lines.append(f"### Comment #{index+1}  ")
                lines.append(f"**Category**: {category}  ")
                lines.append(f"**Severity**: {severity}  ")
                lines.append(f"**Comment**  ")
                lines.append(f"{review.comment}")
            lines.append("\n")
            lines.append("</div>")
            lines.append("</Details>")
            lines.append("\n")
            lines.append("\n")

    whole_diff_review = WholeDiffReview.all()
    number_of_comments = len(whole_diff_review)
    if number_of_comments:
        lines.append(f'<a id="{complete_diff_anchor_link}"></a>  ')
        lines.append(f"## Final diff review  ")
        for index, review in enumerate(whole_diff_review):
            category = review.category[:1].upper() + review.category[1:]
            severity = review.severity[:1].upper() + review.severity[1:]
            lines.append(f"### Comment #{index+1}  ")
            lines.append(f"**Filename**: {review.filename}  ")
            lines.append(f"**Category**: {category}  ")
            lines.append(f"**Severity**: {severity}  ")
            lines.append(f"**Comment**  ")
            lines.append(f"{review.comment}")

    report = "\n".join(lines).rstrip() + "\n"

    path = Path(REPORT_OUTPUT_PATH)
    path.write_text(report, encoding="utf-8")
    write_audit_event("warning", message=f"Exported markdown report")

import time


def main() -> None:
    """Entry point when run as a script."""
    parser = argparse.ArgumentParser()
    parser = argparse.ArgumentParser(
        prog="ai-code-review",
        description=banner,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--all_changes",
        action="store_true",
        help="Includes unstaged, staged, and untracked changes",
    )

    parser.add_argument(
        "--only_staged",
        action="store_true",
        help="Includes only staged changes",
    )

    parser.add_argument(
        "--clean_cache",
        action="store_true",
        help="Removes the cache used for the code reviews",
    )

    parser.add_argument(
        "--no_cache",
        action="store_true",
        help="Removes the cache and starts the code review again",
    )

    args = parser.parse_args()
    start = time.perf_counter()
    cprint(
        text="Launching AI Code Assistant...",
        colour=Colour.WHITE,
        bold=True,
    )
    cprint(
        text="Warning: ",
        colour=Colour.RED,
        bold=True,
        end=""
    )
    cprint(
        text="Be kind to your computer. Quit memory hungry apps before starting.",
        colour=Colour.WHITE,
    )
    cprint(
        text="- Working directory:     ",
        colour=Colour.WHITE,
        bold=False,
        end=""
    )
    cprint(
        text=CWD,
        colour=Colour.GREEN,
        bold=False,
    )
    cprint(
        text="- Script and cache path: ",
        colour=Colour.WHITE,
        bold=False,
        end=""
    )
    cprint(
        text=PATH_FOR_DB,
        colour=Colour.GREEN,
        bold=False,
    )

    if args.clean_cache:
        write_audit_event("user_input", message="user_triggered_clean_cache")
        reset_db_cache()
        return

    if args.no_cache:
        reset_db_cache()
        write_audit_event("user_input", message="user_triggered_no_cache")
    else:
        db_migrations()
    
    git_diff: str = get_git_diff()
    code_is_the_same = check_if_code_has_changed_since_last_review_and_reset(git_diff)

    if code_is_the_same:
        write_audit_event("info", message="code has not changed since last execution")
        cprint(
            text="- Code has not changed, pulling from cache",
            colour=Colour.GREEN,
            bold=True,
        )
    else:
        write_audit_event("info", message="code has changed, resetting cache")
        wrangled_git_diff = split_diff_by_hunk(git_diff)
        write_git_diffs(wrangled_git_diff)
        cprint(
            text="- Code has changed, loaded diffs into cache",
            colour=Colour.GREEN,
            bold=True,
        )
        write_audit_event("info", message="diffs loaded to cache")

    if not CONFIG_FILE.exists():
        create_config()

    config = ConfigParser()
    config.read(CONFIG_FILE)
    write_audit_event("info", message=f"loaded_config_from_{CONFIG_FILE}")
    if BRANCH != config.get("General", "branch_name", fallback=None):
        create_config()
        config = ConfigParser()
        config.read(CONFIG_FILE)
        write_audit_event("info", message=f"loaded_config_from_{CONFIG_FILE}")

    user_defined_folder_files_to_ignore = config.get("Context", "exclude", fallback="").split(",")
    ignored = [d.rstrip("/") for d in user_defined_folder_files_to_ignore]
    mark_which_files_to_ignore(ignored)

    config_models = config.get("General", "model")
    config_models = config_models.split(",")
    context_size = config.getint("General", "context", fallback=32768)
    chat = OllamaChat(models=config_models, num_ctx=context_size)

    if config.getboolean("General", "hunks_review", fallback=False):
        review_hunks(chat)

    if config.getboolean("General", "diff_files_review", fallback=False):
        review_file_diff(chat)

    if config.getboolean("General", "whole_diff_review", fallback=False):
        review_whole_diff(chat)

    chat.unload()

    export_markdown_report()

    cprint(
        text="- Code report finished!",
        colour=Colour.GREEN,
        bold=True,
    )
    print(f"Took {time.perf_counter() - start:.2f}s")


if __name__ == "__main__":
    main()
