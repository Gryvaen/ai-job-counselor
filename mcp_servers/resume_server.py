#!/usr/bin/env python3
"""
resume-mcp — MCP Server for resume management.

Tools: get_resume, update_skills, get_preferences
"""

import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from config.settings import settings

mcp = FastMCP("jobmatch-resume", port=8003)


def _read_resume() -> dict:
    rp = settings.resume_path
    if not rp.exists():
        return {}
    with open(rp) as f:
        return json.load(f)


def _write_resume(data: dict):
    rp = settings.resume_path
    rp.parent.mkdir(parents=True, exist_ok=True)
    with open(rp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@mcp.tool()
def get_resume() -> dict:
    """Get the user's current resume profile.

    Returns:
        Resume dict with name, skills, projects, experience, education, preferences
    """
    return _read_resume()


@mcp.tool()
def update_skills(skills: list[str], action: str = "set") -> list[str]:
    """Update the user's resume skills.

    Args:
        skills: List of skills to add or set
        action: "set" replaces all, "add" appends new skills

    Returns:
        Updated skill list
    """
    data = _read_resume()
    if action == "set":
        data["skills"] = skills
    elif action == "add":
        current = set(data.get("skills", []))
        current.update(skills)
        data["skills"] = list(current)
    _write_resume(data)
    return data.get("skills", [])


@mcp.tool()
def get_preferences() -> dict:
    """Get the user's job search preferences.

    Returns:
        Preferences dict with city, min_salary, target_roles, keywords
    """
    data = _read_resume()
    return data.get("preferences", {})


if __name__ == "__main__":
    mcp.run(transport="stdio")
