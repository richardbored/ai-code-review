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
from typing import Any, List, Literal, Optional
import urllib.request


##################
# FUNCTION TOOLS #
##################

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
    style: str = Colour.BOLD if bold else ""
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


def estimate_token_count(text: str) -> int:
    """Estimate the number of LLM tokens in a string.

    This uses a simple heuristic based on the number of word-like tokens and
    punctuation characters. It is intended as a fast approximation when an
    exact tokenizer is unavailable.

    Args:
        text: The source code or text to estimate.

    Returns:
        An approximate token count.
    """
    word_count: int = len(re.findall(r"\w+", text))
    punctuation_count: int = len(re.findall(r"[^\w\s]", text))

    return int(word_count * 1.3 + punctuation_count * 0.35)


def set_working_directory() -> Path:
    """
    Set the process working directory to the directory from which
    the program was launched.

    Returns:
        Path: The current working directory.
    """
    cwd: Path = Path.cwd()
    os.chdir(cwd)
    return cwd


def get_path_of_script() -> Path:
    """Return the absolute path to the current Python script.

    Returns:
        Path: The fully resolved filesystem path of the current script file.
    """
    return Path(__file__).resolve()


def get_git_branch() -> Optional[str]:
    """Return the name of the currently checked out Git branch.

    Executes ``git branch --show-current`` and returns the active branch name.
    If the command fails (for example, if the current directory is not inside a
    Git repository), ``None`` is returned.

    Returns:
        Optional[str]: The current Git branch name, or ``None`` if it cannot be
        determined.
    """
    try:
        result: subprocess = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_datetime() -> str:
    """Return the current local date and time in ISO 8601 format."""
    return datetime.now().isoformat(timespec="seconds")


def write_audit_event(event: str, **data: Any) -> None:
    """Append an audit event to the current project's JSON Lines log file.

    The audit record contains the current timestamp, the event name, and any
    additional keyword data supplied by the caller. The log filename includes
    the current working directory name and active Git branch.

    Args:
        event: Name or description of the audit event.
        **data: Additional JSON-serializable values to include in the record.

    Raises:
        OSError: If the audit log file cannot be opened or written.
        TypeError: If the audit record contains values that cannot be serialized
            to JSON.
    """
    record: dict[str, Any] = {
        "timestamp": get_current_datetime(),
        "event": event,
        **data,
    }

    path_for_db: Path = get_path_of_script().parent
    branch: str | None = get_git_branch()
    cwd: Path = set_working_directory()

    log_dir: Path = path_for_db / "code_review_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    audit_log_path: Path = (
        log_dir / f"dir_{cwd.name}__br_{branch}__ai_review.log.jsonl"
    )

    with audit_log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False))
        file.write("\n")
        file.flush()


PATH_FOR_DB = get_path_of_script().parent
CWD = set_working_directory()

CACHE_DIR = PATH_FOR_DB / "code_review_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE_NAME = "ai_coding_assistant_config.ini"
CONFIG_FILE = CWD / CONFIG_FILE_NAME

BRANCH = get_git_branch()
DB_PATH = CACHE_DIR / f"dir_{CWD.name}__br_{BRANCH}__ai_review.db"

REPORT_FILENAME = f"{BRANCH}_AI_Code_Review.md"
REPORT_OUTPUT_PATH = CWD / REPORT_FILENAME


################
# DATABASE ORM #
################

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
    _db_path = "sqlite3.db"

    @classmethod
    def configure(cls, path):
        if cls._db is not None:
            cls._db.close()
        cls._db = None
        cls._db_path = path

    @classmethod
    def db(cls):
        if Model._db is None:
            Model._db = sqlite3.connect(DB_PATH)
            Model._db.row_factory = sqlite3.Row

        return Model._db

    @classmethod
    def wipe_db(cls):
        Model.close_db()
        if DB_PATH.exists():
            DB_PATH.unlink()

    @classmethod
    def close_db(cls):
        if Model._db is not None:
            Model._db.close()
            Model._db = None

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
        
        # self._db_path = 

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

###################
# DATABASE MODELS #
###################
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
    severity = Field("TEXT")
    comment = Field("TEXT")
    created_at = Field("TEXT")


class FileDiffReview(Model):
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

class ReviewFiles(Model):
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

    @classmethod
    def current(cls):
        meta = cls.get(id=1)
        if meta is None:
            meta = cls(id=1)
            meta.create()
        return meta


####################
# DATABASE HELPERS #
####################

def db_migrations():
    '''
    Database migrations
    '''
    path_for_db: Path = get_path_of_script().parent

    cache_dir = path_for_db / "code_review_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    branch = get_git_branch()
    db_path = cache_dir / f"dir_{CWD.name}__br_{branch}__ai_review.db"

    Model.configure(db_path)
    GitDiff.create_table()
    MetaData.create_table()
    HunkReview.create_table()
    WholeDiffReview.create_table()
    FileDiffReview.create_table()
    ReviewFiles.create_table()
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


#################
# CONFIG SCRIPT #
#################

def select_hardware_profile(total_memory_gb: float) -> tuple[str, int]:
    """
    Return the recommended model and maximum input-token budget.

    Uses total installed memory because the supplied recommendations
    are expressed in total-memory tiers.
    """
    if total_memory_gb <= 5:
        return [
            "gemma4:e2b-it-qat",
            "qwen3.5:2b",
            "qwen3.5:2b-mlx",
        ], 4_000

    if total_memory_gb <= 8:
        return [
            "gemma4:e2b-it-qat",
            "qwen3.5:4b-mlx",
            "qwen3.5:4b",
        ], 4_000

    if total_memory_gb <= 16:
        return [
            "gemma4:12b-it-q4_K_M",
            "gemma4:12b-mlx",
            "qwen3.5:9b",
            "qwen3.5:9b-mlx",
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
        json_format: str = (
            "The JSON must have the following structure:\n"
            "{\n"
            '  "comments": [\n'
            "    {\n"
            '      "severity": "low|medium|high",\n'
            '      "comment": "Concise actionable finding"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Each comment should describe a single issue in one or two "
            "sentences. If no issues are found, return:\n"
            '{ "comments": [] }'
        )
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
                f"{json_format}"
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
                f"{json_format}"
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
                f"{json_format}"
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
                f"{json_format}"
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
                f"{json_format}"
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
                f"{json_format}"
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
        "review_whole_files": str(review_whole_files),
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

#########
# OTHER #
#########

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


###################
# OllamaChat Class #
###################

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


def get_git_diff(args):
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


def write_git_diffs(git_diffs: str, to_ignore = []):
    total_tokens = 0

    to_ignore.append(CONFIG_FILE_NAME)
    to_ignore.append(REPORT_OUTPUT_PATH)

    for review in git_diffs:
        token_amount = estimate_token_count(review["diff"])
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
    meta.update(total_est_token_amount=total_tokens)


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


def calculate_total_review_time(total_hunk_reviews: int):
    per_test_time = 40
    est_length = (total_hunk_reviews + 7) * per_test_time
    minutes, seconds = divmod(est_length, 60)
    cprint(
        text=f"- Est time to completion: {minutes}:{seconds:02d}",
        colour=Colour.YELLOW,
        bold=True
    )


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        print(ValueError("No JSON object found."))
        return None
    return json.loads(text[start:end + 1])


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
    calculate_total_review_time(total_hunk_reviews=total_hunk_reviews)
    completed_reviews = 0

    for field_name, setting in vars(review_config).items():
        context = build_context_for_llm(config, setting.context)
        if setting.enabled is False:
            print(f"- {setting.name} is disabled in config")
            continue

        for git_diff in GitDiff.all():
            cprint(text=f"- Starting test {completed_reviews+1} of {total_hunk_reviews}... ", colour=Colour.WHITE, end="")
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
                try:
                    data = extract_json(res)
                    if data:
                        for comment in data["comments"]:
                            HunkReview(
                                git_diff_id=git_diff.id,
                                filename=git_diff.filename,
                                type_of_review=setting.name,
                                severity=comment["severity"],
                                comment=comment["comment"],
                                created_at=get_current_datetime(),
                            ).create()
                    if data["comments"] == []:
                        HunkReview(
                            git_diff_id=git_diff.id,
                            filename=git_diff.filename,
                            type_of_review=setting.name,
                            severity="None",
                            comment="None",
                            created_at=get_current_datetime(),
                        ).create()
                except json.JSONDecodeError as e:
                    cprint(
                        text="- Ollama returned a malformed JSON. Skipping git hunk review...",
                        colour=Colour.RED,
                        bold=True
                    )
                    write_audit_event("warning", message=f"Review for {git_diff.filename} failed")
                    pass

            skipped_file = ""
            if reviews:
                skipped_file = "(existing review was in cache)"

            chat.clear()
            completed_reviews += 1
            cprint(text="Completed! ", colour=Colour.GREEN, bold=True, end="")
            cprint(text=skipped_file, colour=Colour.WHITE, end="")
            cprint(text="", colour=Colour.WHITE)
    write_audit_event("info", message=f"Completed hunk review")


def review_file_diff(chat: OllamaChat):
    files = defaultdict(list)

    for hunk in GitDiff.all():
        files[hunk.filename].append(hunk.diff)

    for filename, diff_list in files.items():
        print(f"- Processing {filename}")

        existing_review = ""
        reviews = HunkReview.filter(filename=filename)
        for review in reviews:
            if review.comment != "None":
                existing_review += f"Type: {review.type_of_review} \n"
                existing_review += f"Severity: {review.severity} \n"
                existing_review += f"AI comment: {review.comment} \n\n"

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

        if len(FileDiffReview.filter(filename=filename)) > 0:
            print(f"- {filename} review already exists in cache")
            return
        res = chat.send_message(message=prompt)
        chat.clear()
        try:
            data = extract_json(res)
            if data:
                for comment in data["comments"]:
                    FileDiffReview(
                        filename=filename,
                        category=comment["category"],
                        severity=comment["severity"],
                        comment=comment["comment"]
                    ).create()
            if data["comments"] == []:
                FileDiffReview(
                    filename=filename,
                    category="None",
                    severity="None",
                    comment="None"
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
            if hunk.severity != "None":
                existing_review += f"\nType of review: {hunk.type_of_review} \n"
                existing_review += f"Severity: {hunk.severity} \n"
                existing_review += f"Comment: {hunk.comment} \n"

        file_comments = FileDiffReview.filter(filename=filename)
        for comment in file_comments:
            if comment.comment != "None":
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
    if estimate_token_count(prompt) > max_token_amount:
        print("- Context too small for entire diff review")
        return
    
    if WholeDiffReview.get(id=1) is not None:
        print("- Whole diff review already exists in cache")
        return

    res = chat.send_message(message=prompt)
    chat.clear()
    try:
        data = extract_json(res)
        if data:
            for file in data["files"]:
                filename = file["filename"]
                for comment in file["comments"]:
                    WholeDiffReview(
                        filename=filename,
                        category=comment["category"],
                        severity=comment["severity"],
                        comment=comment["comment"]
                    ).create()
        if data["files"] == []:
            WholeDiffReview(
                filename="None",
                category="None",
                severity="None",
                comment="None"
            ).create()
    except json.JSONDecodeError as e:
        print("- Ollama returned a malformed JSON. Skipping whole diff review...")
        write_audit_event("warning", message=f"Review for whole diff failed")
        pass


def review_whole_file(chat: OllamaChat):
    filenames = sorted({
        git_diff.filename
        for git_diff in GitDiff.all()
    })

    for filename in filenames:
        path = Path(filename)
        # print(path)

        if not path.is_file():
            return None
        code = path.read_text(encoding="utf-8")
        config = ConfigParser()
        config.read(CONFIG_FILE)
        max_token_amount = config.getint("General", "context")
        prompt = (
            "Review the entire code file provided below.\n\n"
            "Identify concrete issues related to:\n\n"
            "- Bugs and incorrect behavior\n"
            "- Code quality and maintainability\n"
            "- Security risks\n"
            "- Style and readability\n"
            "- Performance\n"
            "- Other relevant concerns\n\n"
            "Return only valid JSON matching this exact schema:\n\n"
            "{\n"
            '  "comments": [\n'
            "    {\n"
            '      "category": "bug|quality|security|style|performance|other",\n'
            '      "severity": "low|medium|high",\n'
            '      "comment": "Concise actionable finding"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Requirements:\n\n"
            "- Review the whole file, not only isolated sections.\n"
            "- Report only specific, actionable findings.\n"
            "- Keep each comment concise.\n"
            "- Explain what is wrong and how it should be improved.\n"
            "- Include function names, class names, variable names, or line numbers when helpful.\n"
            "- Use only one of the allowed category values.\n"
            "- Use only one of the allowed severity values.\n"
            "- Do not include praise, summaries, markdown, code fences, or text outside the JSON.\n"
            "- Do not invent issues.\n"
            "- Do not return duplicate or substantially overlapping findings.\n"
            "- If no issues are found, return:\n\n"
            "{\n"
            '  "comments": []\n'
            "}\n\n"
            "Code file:\n\n"
        ) + code

        if estimate_token_count(code) > max_token_amount:
            print("- Context too small for entire file review")
            return

        if ReviewFiles.filter(filename=filename) != []:
            print(f"- {filename} review already exists in cache")
            continue

        cprint(
            text=f"- Complete review of {filename}...  ",
            colour=Colour.WHITE,
            end=""
        )
        res = chat.send_message(message=prompt)
        chat.clear()
        try:
            data = extract_json(res)
            if data:
                for comment in data["comments"]:
                    ReviewFiles(
                        filename=filename,
                        category=comment["category"],
                        severity=comment["severity"],
                        comment=comment["comment"]
                    ).create()
            if data["comments"] == []:
                WholeDiffReview(
                    filename=filename,
                    category="None",
                    severity="None",
                    comment="None"
                ).create()

            cprint(
                text=f"Done!",
                colour=Colour.GREEN,
            )

        except json.JSONDecodeError as e:
            print("- Ollama returned a malformed JSON. Skipping whole file review...")
            write_audit_event("warning", message=f"Review for whole file failed")
            pass


def prettify_var_names(s: str):
    s = s.replace("_", " ")
    return s.capitalize()


def export_markdown_report():
    meta = MetaData.current()
    review_config = ReviewConfig(CONFIG_FILE)
    config = ConfigParser()
    config.read(CONFIG_FILE)

    data_for_markdown_export = {
        "meta": {
            "Generated": get_current_datetime(),
            "Branch": BRANCH,
            "Branch description": config.get('General', 'branch_description'),
            "Model": meta.model,
            "Number of tokens": meta.total_est_token_amount,
            "Reviewed hunks": config.get('General', 'hunks_review'),
            "Reviewed files": config.get('General', 'diff_files_review'),
            "Reviewed whole diff": config.get('General', 'whole_diff_review'),
        }
    }
    data_for_markdown_export["meta"].update({
        setting.print_str: setting.enabled
        for setting in vars(review_config).values()
    })

    data_for_markdown_export["filenames"] = {
        filename: {
            "diff_review" : []
        }
        for filename in sorted({
            git_diff.filename
            for git_diff in GitDiff.all()
        })
    }

    for filename in data_for_markdown_export["filenames"]:
        git_diffs = GitDiff.filter(filename=filename)
        for diff in git_diffs:
            d = {
                "diff": diff.diff,
                "comments": {}
            }
            reviews = HunkReview.filter(git_diff_id=diff.id)
            for setting in vars(review_config).values():
                reviews = HunkReview.filter(
                    git_diff_id=diff.id,
                    type_of_review=setting.name
                )
                is_empty = not reviews
                is_none_review = len(reviews) == 1 and reviews[0].comment == "None"
                if is_empty or is_none_review:
                    continue

                d["comments"][setting.name] = {}
                for index, review in enumerate(reviews):
                    d["comments"][setting.name][index] = {
                        "Severity": review.severity,
                        "Comment": review.comment,
                    }
            data_for_markdown_export["filenames"][filename]["diff_review"].append(d)

        file_reviews = FileDiffReview.filter(filename=filename)
        is_empty = not file_reviews
        is_none_review = len(file_reviews) == 1 and file_reviews[0].comment == "None"
        if is_empty or is_none_review:
            continue

        data_for_markdown_export["filenames"][filename]["file_review"] = {}
        for index, file_review in enumerate(file_reviews):
            data_for_markdown_export["filenames"][filename]["file_review"].setdefault(file_review.category, []).append({
                "Category": file_review.category,
                "Severity": file_review.severity,
                "Comment": file_review.comment,
            })

    
    whole_diff_review = WholeDiffReview.all()
    is_empty = not whole_diff_review
    is_none_review = len(whole_diff_review) == 1 and whole_diff_review[0].comment == "None"
    if is_empty or is_none_review:
        pass
    else:
        data_for_markdown_export["Whole diff review"] = []
        for comment in whole_diff_review:
            if comment.comment == "None":
                continue

            data_for_markdown_export["Whole diff review"].append(
                {
                    "Filename": comment.filename,
                    "Category": comment.category,
                    "Severity": comment.severity,
                    "Comment": comment.comment,
                }
            )

    whole_file_review = ReviewFiles.all()
    is_empty = not whole_file_review
    is_none_review = len(whole_file_review) == 1 and whole_file_review[0].comment == "None"
    if is_empty or is_none_review:
        pass
    else:
        data_for_markdown_export["Whole file review"] = []
        for comment in whole_file_review:
            if comment.comment == "None":
                continue

            data_for_markdown_export["Whole file review"].append(
                {
                    "Filename": comment.filename,
                    "Category": comment.category,
                    "Severity": comment.severity,
                    "Comment": comment.comment,
                }
            )

    lines = [
        "# AI Code Review Report \n\n"
        "## Overview  \n"
    ]

    for key, value in data_for_markdown_export["meta"].items():
        lines.append(f"**{key}**: {value}  ")
    
    lines.append("## Index  ")
    for key, value in data_for_markdown_export["filenames"].items():
        lines.append(f"- [{key}](#{key})  ")

    if "Whole file review" in data_for_markdown_export:
        lines.append(f"- [Whole file review](#whole_file_review)  \n")

    for key, value in data_for_markdown_export["filenames"].items():
        lines.append(f'<a id="{key}"></a>  ')
        lines.append(f"## {key}  ")
        for diff in value["diff_review"]:
            lines.append(f'```{diff["diff"]}```')
            for key, comment in diff["comments"].items():
                lines.append(
                    f'<Details style="margin-bottom:10px;" summary=\"{prettify_var_names(key)} {len(comment)}\">\n\n'
                    f'<summary style="font-size:18px;margin-bottom:10px;">&nbsp {prettify_var_names(key)} ({len(comment)})</summary> \n'
                    '<div style="margin-left: 1rem; padding-left: 1rem; border-left: 3px solid #d1d5db;"> \n'
                )
                for key, issue in comment.items():
                    lines.append(f"\n### Comment #{int(key)+1}  \n")
                    lines.append(f"**Severity**: {issue['Severity'].capitalize()}\n  ")
                    lines.append(f"**Comment**: {issue['Comment']}\n  ")
                    lines.append(f"---\n")
                lines.append(
                    "</div>"
                    "</Details>\n"
                )

        if "file_review" in value:
            lines.append(
                f'<Details style="margin-bottom:10px;" summary=\"File diff review {len(value["file_review"])}\">\n\n'
                f'<summary style="font-size:18px;margin-bottom:10px;">&nbsp File diff review ({len(value["file_review"])})</summary> \n'
                '<div style="margin-left: 1rem; padding-left: 1rem; border-left: 3px solid #d1d5db;"> \n'
            )
            for key, comment_type in value["file_review"].items():
                lines.append(f"### {prettify_var_names(key)}")
                for comment in comment_type:
                    lines.append(f"**Severity**: {prettify_var_names(comment['Severity'])}  ")
                    lines.append(f"**Comment**: {comment['Comment']}  ")

            lines.append(
                "</div>"
                "</Details>\n"
            )

    if "Whole file review" in data_for_markdown_export:
        lines.append(f'<a id="whole_file_review"></a>  ')
        lines.append("## Whole file review  ")
        for comment in data_for_markdown_export["Whole file review"]:
            lines.append(f"\n**Filename**: {comment['Filename']}  ")
            lines.append(f"**Severity**: {comment['Severity'].capitalize()}  ")
            lines.append(f"**Comment**: {comment['Comment']}  ")
            lines.append(f"\n---\n")

    report = "\n".join(lines).rstrip() + "\n"

    path = Path(REPORT_OUTPUT_PATH)
    path.write_text(report, encoding="utf-8")
    write_audit_event("warning", message=f"Exported markdown report")


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
    args = parser.parse_args()
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
        text="For the best performance, close memory-intensive applications before running the script.",
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

    db_migrations()

    git_diff: str = get_git_diff(args=args)
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

    if config.getboolean("General", "review_whole_files", fallback=False):
        review_whole_file(chat)

    chat.unload()

    export_markdown_report()

    cprint(
        text="- Code report finished!",
        colour=Colour.GREEN,
        bold=True,
    )


if __name__ == "__main__":
    main()
